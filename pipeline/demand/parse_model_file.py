"""
Parse modelgen output files (la_model.txt, nyc_model.txt, etc.).

These files are produced by an activity-based population synthesizer that
integrates OpenStreetMap road networks, LandScan population grids, and
U.S. Census PUMS microdata into a single flat-text model.

Files post-processed by the cityscape ScheduleGenerator
(github.com/raodj/cityscape, Schedule-generator branch) additionally carry
per-person activity schedules in the trailing field of `per` records.

This module extracts building, household, and person records, optionally
filtering to a geographic bounding box, and returns structured data
suitable for census-calibrated demand generation.

Record format (fields are space-separated):
  bld  ID levels population attributes isHome kind sqFoot
       topLon topLat botLon botLat wayID wayLat wayLon pumaID #households
  hld  bldID "SMARTPHONE,SERIALNO" bedRooms BLDtype pumaID WGTP HINCP
       #people peopleIDs...
  per  perID HldID #info AGEP WAGP JWMNP JWTRNS schedule

The trailing `schedule` is an empty string `""` for persons without a
schedule (non-workers, transit/walk/WFH/taxi/other commuters), or a
sequence of `(activity_type subtype time_s bld_id)` tuples for persons
the schedule generator covered. In the current cityscape output every
populated schedule is exactly two tuples — `(1 5 28800 <work_bld_id>)`
followed by `(1 5 61200 <home_bld_id>)` — i.e. workplace at 8 AM,
return home at 5 PM. The 8 AM / 5 PM times are constants set by
cityscape; only the destination bld_id varies per person.

JWTRNS codes (ACS/PUMS):
  1  = Car, truck, or van — drove alone
  2  = Car, truck, or van — carpooled
  3  = Bus
  4  = Streetcar / trolley
  5  = Subway / elevated rail
  6  = Railroad
  7  = Ferryboat
  8  = Bicycle
  9  = Walked
  10 = Worked from home
  11 = Taxicab / rideshare
  12 = Other
  -1 = Not a worker / not applicable
"""

import logging
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Building:
    """A building from the model file."""
    bld_id: int
    levels: int
    population: int
    is_home: bool
    kind: str           # e.g. "apartments:", "office:", "yes:"
    sq_foot: int
    top_lon: float      # bounding box
    top_lat: float
    bot_lon: float
    bot_lat: float
    way_id: int         # OSM way ID the building is near
    way_lat: float      # snap point on nearest road
    way_lon: float
    puma_id: int
    num_households: int
    # Centroid derived from bounding box
    lat: float = 0.0
    lon: float = 0.0

    def __post_init__(self):
        self.lat = (self.top_lat + self.bot_lat) / 2.0
        self.lon = (self.top_lon + self.bot_lon) / 2.0


@dataclass
class Household:
    """A household from the model file."""
    bld_id: int
    serial_no: str
    bedrooms: int
    bld_type: int
    puma_id: int
    weight: int         # WGTP — household weight for expansion
    income: int         # HINCP — household income
    num_people: int
    person_ids: list[int] = field(default_factory=list)


@dataclass
class ScheduleActivity:
    """A single activity in a person's daily schedule.

    In current cityscape output: a populated schedule is always two
    activities — workplace arrival at 8 AM and home return at 5 PM.
    Only ``bld_id`` varies per person; the other fields are constants
    (`activity_type=1`, `subtype=5`, `time_s` ∈ {28800, 61200}).
    """
    activity_type: int
    subtype: int
    time_s: int     # seconds from midnight
    bld_id: int     # destination building


@dataclass
class Person:
    """A person from the model file."""
    per_id: int
    hld_serial: str
    num_info: int
    age: int            # AGEP
    wages: int          # WAGP (-1 = N/A)
    commute_min: int    # JWMNP — commute time in minutes (-1 = N/A)
    transport_mode: int # JWTRNS code (-1 = N/A)
    # Activity schedule from cityscape ScheduleGenerator (empty list for
    # persons whose mode the generator does not cover — see module docstring).
    schedule: list[ScheduleActivity] = field(default_factory=list)


@dataclass
class ModelData:
    """Parsed and filtered model data for a city."""
    buildings: list[Building]
    households: list[Household]
    persons: list[Person]
    # Indexes for fast lookup
    bld_by_id: dict[int, Building] = field(default_factory=dict)
    hld_by_bld: dict[int, list[Household]] = field(default_factory=dict)
    home_bld_by_per_id: dict[int, int] = field(default_factory=dict)
    per_by_id: dict[int, Person] = field(default_factory=dict)

    def __post_init__(self):
        self.bld_by_id = {b.bld_id: b for b in self.buildings}
        self.hld_by_bld = {}
        for h in self.households:
            self.hld_by_bld.setdefault(h.bld_id, []).append(h)
        # Per-person home resolution: PUMS replicates SERIALNO across many
        # synthesised households (each with its own bld_id), so a SERIALNO
        # lookup is ambiguous. Each `hld` record's person_ids list, however,
        # uniquely names which synthesised home holds each person — use that.
        self.home_bld_by_per_id = {}
        for h in self.households:
            for pid in h.person_ids:
                self.home_bld_by_per_id[pid] = h.bld_id
        self.per_by_id = {p.per_id: p for p in self.persons}


# ---------------------------------------------------------------------------
# JWTRNS → canonical mode mapping
# ---------------------------------------------------------------------------

JWTRNS_TO_MODE = {
    1: "car",       # Drove alone
    2: "car",       # Carpooled (still a car trip on the road)
    3: "transit",   # Bus
    4: "transit",   # Streetcar/trolley
    5: "transit",   # Subway/elevated rail
    6: "transit",   # Railroad
    7: "transit",   # Ferryboat
    8: "bike",
    9: "walk",
    10: "home",     # Worked from home (no trip)
    11: "car",      # Taxicab/rideshare
    12: "car",      # Other — default to car
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_building_line(parts: list[str]) -> Optional[Building]:
    """Parse a single 'bld' line into a Building object."""
    try:
        # bld ID levels population attributes isHome kind sqFoot
        #     topLon topLat botLon botLat wayID wayLat wayLon pumaID #households
        # Fields are space-split, but 'kind' is quoted and may contain spaces
        # The raw line was already split respecting quotes by the caller
        bld_id = int(parts[1])
        levels = int(parts[2])
        population = int(parts[3])
        # parts[4] = attributes (integer)
        is_home = parts[5].lower() == "true"
        kind = parts[6].strip('"')
        sq_foot = int(parts[7])
        top_lon = float(parts[8])
        top_lat = float(parts[9])
        bot_lon = float(parts[10])
        bot_lat = float(parts[11])
        way_id = int(parts[12])
        way_lat = float(parts[13])
        way_lon = float(parts[14])
        puma_id = int(parts[15])
        num_households = int(parts[16])

        return Building(
            bld_id=bld_id, levels=levels, population=population,
            is_home=is_home, kind=kind, sq_foot=sq_foot,
            top_lon=top_lon, top_lat=top_lat,
            bot_lon=bot_lon, bot_lat=bot_lat,
            way_id=way_id, way_lat=way_lat, way_lon=way_lon,
            puma_id=puma_id, num_households=num_households,
        )
    except (IndexError, ValueError) as e:
        logger.debug("Skipping malformed bld line: %s", e)
        return None


def _parse_household_line(parts: list[str]) -> Optional[Household]:
    """Parse a single 'hld' line into a Household object."""
    try:
        bld_id = int(parts[1])
        serial_raw = parts[2].strip('"')
        # serial_raw is like "1,2019HU0061303" — take the part after comma
        serial_parts = serial_raw.split(",", 1)
        serial_no = serial_parts[1] if len(serial_parts) > 1 else serial_raw
        bedrooms = int(parts[3])
        bld_type = int(parts[4])
        puma_id = int(parts[5])
        weight = int(parts[6])
        income = int(parts[7])
        num_people = int(parts[8])
        person_ids = [int(parts[i]) for i in range(9, 9 + num_people)
                      if i < len(parts)]
        return Household(
            bld_id=bld_id, serial_no=serial_no, bedrooms=bedrooms,
            bld_type=bld_type, puma_id=puma_id, weight=weight,
            income=income, num_people=num_people, person_ids=person_ids,
        )
    except (IndexError, ValueError) as e:
        logger.debug("Skipping malformed hld line: %s", e)
        return None


# Schedule activity tuple inside the trailing quoted field.
# Captures four whitespace-separated integers between matching parentheses.
# Defensive: tolerates extra whitespace; ignores anything that is not a 4-int tuple.
_SCHEDULE_TUPLE_RE = re.compile(r"\((-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\)")


def _parse_schedule(raw: str) -> list[ScheduleActivity]:
    """Extract a list of ScheduleActivity from the trailing quoted schedule field.

    Empty string ``""`` (the common case for non-workers and uncovered modes)
    returns an empty list. Malformed content is silently dropped — the
    upstream cityscape generator is the source of truth for schema, and a
    bad tuple should not crash the whole parse.
    """
    inner = raw.strip().strip('"')
    if not inner:
        return []
    return [
        ScheduleActivity(
            activity_type=int(m.group(1)),
            subtype=int(m.group(2)),
            time_s=int(m.group(3)),
            bld_id=int(m.group(4)),
        )
        for m in _SCHEDULE_TUPLE_RE.finditer(inner)
    ]


def _parse_person_line(line: str, parts: list[str]) -> Optional[Person]:
    """Parse a single 'per' line into a Person object.

    ``parts`` is the whitespace-split prefix (used for the seven scalar fields);
    ``line`` is the raw line from which we recover the trailing quoted schedule
    field — split() would shred the parentheses inside the quotes.
    """
    try:
        per_id = int(parts[1])
        hld_serial = parts[2]
        num_info = int(parts[3])
        age = int(parts[4])
        wages = int(parts[5])
        commute_min = int(parts[6])
        transport_mode = int(parts[7])
        # Schedule is everything inside the first pair of double-quotes after
        # the seven scalar fields. Empty string → no schedule (most persons).
        schedule: list[ScheduleActivity] = []
        first_q = line.find('"')
        if first_q != -1:
            last_q = line.rfind('"')
            if last_q > first_q:
                schedule = _parse_schedule(line[first_q : last_q + 1])
        return Person(
            per_id=per_id, hld_serial=hld_serial, num_info=num_info,
            age=age, wages=wages, commute_min=commute_min,
            transport_mode=transport_mode, schedule=schedule,
        )
    except (IndexError, ValueError) as e:
        logger.debug("Skipping malformed per line: %s", e)
        return None


def parse_model_file(
    model_path: Path,
    bbox: Optional[tuple[float, float, float, float]] = None,
    car_only: bool = True,
    modes: Optional[list[str]] = None,
) -> ModelData:
    """
    Parse a modelgen output file and return structured data.

    Args:
        model_path: Path to the model file (e.g. la_model.txt).
        bbox: Optional (south, north, west, east) bounding box in WGS84.
              Only buildings whose centroid falls inside will be kept.
              If None, all buildings are kept.
        car_only: If True, only keep persons with car-compatible transport
                  modes (JWTRNS in {1, 2, 11, 12}).  Default True since
                  SimForge v0 only simulates car traffic.
                  Ignored if `modes` is provided.
        modes: Optional list of canonical modes to keep (e.g. ["car", "transit"]).
               When provided, overrides `car_only`.  Persons whose JWTRNS
               maps to a mode in this list are kept.

    Returns:
        ModelData with buildings, households, and persons.
    """
    model_path = Path(model_path)
    if not model_path.is_file():
        raise FileNotFoundError(f"Model file not found: {model_path}")

    logger.info("Parsing model file: %s (%.0f MB)",
                model_path.name, model_path.stat().st_size / 1e6)

    # --- Pass 1: parse buildings, filter by bbox ---
    all_buildings: list[Building] = []
    all_households: list[Household] = []
    all_persons: list[Person] = []

    # For very large files we do a single-pass streaming read
    bld_count = hld_count = per_count = 0
    kept_bld_ids: Optional[set[int]] = None  # will be set after bbox filter

    with open(model_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("#") or line.startswith("\n"):
                continue

            if line.startswith("bld "):
                bld_count += 1
                try:
                    parts = shlex.split(line, posix=True)
                except ValueError:
                    # Malformed quoting in building line — skip gracefully
                    logger.debug("Skipping bld line with malformed quoting: %r", line[:80])
                    continue
                bld = _parse_building_line(parts)
                if bld is None:
                    continue
                # Spatial filter
                if bbox is not None:
                    south, north, west, east = bbox
                    if not (south <= bld.lat <= north and west <= bld.lon <= east):
                        continue
                all_buildings.append(bld)

            elif line.startswith("hld "):
                hld_count += 1
                parts = line.split()
                hld = _parse_household_line(parts)
                if hld is not None:
                    all_households.append(hld)

            elif line.startswith("per "):
                per_count += 1
                # Split for scalar fields, but keep the raw line so the
                # parenthesised schedule field survives the split() shredding.
                parts = line.split(maxsplit=8)
                per = _parse_person_line(line, parts)
                if per is not None:
                    all_persons.append(per)

    logger.info("Raw records: %d bld, %d hld, %d per",
                bld_count, hld_count, per_count)

    # --- Filter households and persons to kept buildings ---
    kept_bld_ids = {b.bld_id for b in all_buildings}

    filtered_hlds = [h for h in all_households if h.bld_id in kept_bld_ids]

    # Collect kept person IDs from kept households
    kept_per_ids: set[int] = set()
    for h in filtered_hlds:
        kept_per_ids.update(h.person_ids)

    filtered_persons = [p for p in all_persons if p.per_id in kept_per_ids]

    # Optionally filter to car commuters only
    if modes is not None:
        # User specified explicit modes — filter by those
        allowed_jwtrns = {code for code, m in JWTRNS_TO_MODE.items() if m in modes}
        filtered_persons = [
            p for p in filtered_persons
            if p.transport_mode in allowed_jwtrns and p.commute_min > 0
        ]
    elif car_only:
        car_modes = {1, 2, 11, 12}  # drove alone, carpool, taxi/rideshare, other
        filtered_persons = [
            p for p in filtered_persons
            if p.transport_mode in car_modes and p.commute_min > 0
        ]

    logger.info(
        "After filtering: %d buildings, %d households, %d persons",
        len(all_buildings), len(filtered_hlds), len(filtered_persons),
    )

    # --- Build result ---
    result = ModelData(
        buildings=all_buildings,
        households=filtered_hlds,
        persons=filtered_persons,
    )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    """CLI entry point for testing the parser."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse a modelgen output file and print summary statistics."
    )
    parser.add_argument("model_path", type=str, help="Path to model file")
    parser.add_argument("--bbox", type=str, default=None,
                        help="Bounding box as 'south,north,west,east'")
    args = parser.parse_args()

    bbox = None
    if args.bbox:
        try:
            parts = [float(x.strip()) for x in args.bbox.split(",")]
        except ValueError as exc:
            print(f"Error: --bbox must be 4 comma-separated numbers, got: '{args.bbox}'")
            print("  Format: --bbox 'south,north,west,east'")
            print("  Example: --bbox '41.8,42.0,-87.7,-87.5'")
            raise SystemExit(1) from exc
        if len(parts) != 4:
            print(f"Error: --bbox expects 4 values (south,north,west,east), got {len(parts)}")
            raise SystemExit(1)
        bbox = (parts[0], parts[1], parts[2], parts[3])

    data = parse_model_file(Path(args.model_path), bbox=bbox)

    # Summary
    residential = [b for b in data.buildings if b.is_home]
    total_pop = sum(b.population for b in data.buildings)
    commuters = [p for p in data.persons if p.commute_min > 0]
    commute_times = [p.commute_min for p in commuters]
    scheduled = [p for p in data.persons if p.schedule]

    print(f"\n{'='*50}")
    print(f"  Model file: {args.model_path}")
    print(f"  Buildings:  {len(data.buildings)} ({len(residential)} residential)")
    print(f"  Population: {total_pop}")
    print(f"  Households: {len(data.households)}")
    print(f"  Persons:    {len(data.persons)} ({len(commuters)} car commuters)")
    if commute_times:
        avg = sum(commute_times) / len(commute_times)
        print(f"  Commute:    avg {avg:.0f} min, range {min(commute_times)}-{max(commute_times)} min")
    pct = (len(scheduled) / len(data.persons) * 100) if data.persons else 0.0
    print(f"  Schedules:  {len(scheduled)} ({pct:.1f}% of persons have a workplace destination)")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
