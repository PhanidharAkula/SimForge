"""
Parse the modelgen output files (la_model.txt, nyc_model.txt, etc.).

An activity-based population synthesizer produces these: it fuses
OpenStreetMap road networks, LandScan population grids, and U.S. Census
PUMS microdata into one flat-text model.

When a file has been run through the cityscape ScheduleGenerator
(github.com/raodj/cityscape, Schedule-generator branch), the `per` records
also carry a per-person activity schedule in their trailing field.

This module pulls out the building, household, and person records,
optionally clipping to a bounding box, and returns structured data ready
for census-calibrated demand generation.

Record format (fields are space-separated):
  bld  ID levels population attributes isHome kind sqFoot
       topLon topLat botLon botLat wayID wayLat wayLon pumaID #households
  hld  bldID "SMARTPHONE,SERIALNO" bedRooms BLDtype pumaID WGTP HINCP
       #people peopleIDs...
  per  perID HldID #info AGEP WAGP JWMNP JWTRNS schedule

The trailing `schedule` is `""` for anyone without one (non-workers, plus
transit/walk/WFH/taxi/other commuters), or a sequence of
`(dow_start dow_end time_s bld_id)` tuples for the people the schedule
generator covered. The first two ints are day-of-week bounds (0=Sunday,
1=Monday, ..., 5=Friday, 6=Saturday, -1=unspecified); see
`model_gen/ScheduleEntry.h` in the cityscape repo. In today's cityscape
output a populated schedule is always exactly two tuples,
`(1 5 28800 <work_bld_id>)` then `(1 5 61200 <home_bld_id>)`: Monday to
Friday, work at 8 AM, home at 5 PM. The days and clock times are cityscape
constants; only the destination bld_id changes from person to person.

JWTRNS codes (cityscape Schedule-generator branch, verbatim from the ACS
PUMS 2021 Data Dictionary, see model_gen/ScheduleGenerator.h:211-233):
   1 = Car, truck, or van             (drove alone + carpool combined,
                                        merged in ACS 2019+)
   2 = Bus
   3 = Subway or elevated rail
   4 = Long-distance train or commuter rail
   5 = Light rail, streetcar, or trolley
   6 = Ferryboat
   7 = Taxicab
   8 = Motorcycle
   9 = Bicycle
  10 = Walked
  11 = Worked from home
  12 = Other method
  -1 = N/A, not a worker  (cityscape's "bb" sentinel, converted to -1
                            on emit; see PUMS.cpp / PUMSPerson::write)

JWTRNS_TO_MODE below folds these 12 codes into SimForge's 4 simulator
buckets (car/transit/bike/walk) plus a "home" sentinel that keeps the trip
out of the demand entirely. See doc/MODELGEN_AND_MODES.md §4.
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
    weight: int         # WGTP: household weight for expansion
    income: int         # HINCP: household income
    num_people: int
    person_ids: list[int] = field(default_factory=list)


@dataclass
class ScheduleActivity:
    """A single activity in a person's daily schedule.

    Field semantics come from cityscape's ``model_gen/ScheduleEntry.h``:
    the first two ints encode the day-of-week range this activity
    applies to (0=Sunday, 1=Monday, ..., 5=Friday, 6=Saturday,
    -1=unspecified); the third is seconds from midnight; the fourth is
    the destination ``bld_id``.

    In today's cityscape output a populated schedule is always two
    activities: arrive at work at 8 AM, home again at 5 PM, Monday through
    Friday. Only ``bld_id`` changes per person; the day bounds and clock
    times are constants (`dow_start=1`, `dow_end=5`,
    `time_s` in {28800, 61200}).
    """
    dow_start: int  # day of week start (0=Sun, 1=Mon, ..., 6=Sat, -1=unspecified)
    dow_end: int    # day of week end (same encoding)
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
    commute_min: int    # JWMNP: commute time in minutes (-1 = N/A)
    transport_mode: int # JWTRNS code (-1 = N/A)
    # Activity schedule from the cityscape ScheduleGenerator (empty for
    # persons whose mode the generator doesn't cover, see module docstring).
    schedule: list[ScheduleActivity] = field(default_factory=list)


@dataclass
class ModelData:
    """Parsed and filtered model data for a city."""
    buildings: list[Building]
    households: list[Household]
    persons: list[Person]
    # `age_by_per_id` is populated by the parser BEFORE mode-filtering so
    # that household-composition queries (e.g. "does this commuter live
    # with a school-age dependent?") can see ages of *every* household
    # member, including non-commuters (kids, retirees) whose JWTRNS=-1
    # would otherwise be excluded from `persons` by the mode filter.
    # Empty if built without a prior all-persons pass; callers should read
    # an absence as "data unavailable", not "no kids".
    age_by_per_id: dict[int, int] = field(default_factory=dict)
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
        # Resolving each person's home: PUMS reuses SERIALNO across many
        # synthesised households (each with its own bld_id), so looking up by
        # SERIALNO is ambiguous. But each `hld` record's person_ids list pins
        # exactly which home holds each person, so we use that instead.
        self.home_bld_by_per_id = {}
        for h in self.households:
            for pid in h.person_ids:
                self.home_bld_by_per_id[pid] = h.bld_id
        self.per_by_id = {p.per_id: p for p in self.persons}
        # If the parser didn't supply `age_by_per_id`, build it from
        # `persons`. That gets the commuters' ages right but misses
        # non-commuter household members (kids and so on). Most callers use
        # the parser-supplied version; this fallback just keeps direct
        # `ModelData(...)` construction working in tests.
        if not self.age_by_per_id:
            self.age_by_per_id = {p.per_id: p.age for p in self.persons}


# ---------------------------------------------------------------------------
# JWTRNS to canonical mode mapping
# ---------------------------------------------------------------------------

JWTRNS_TO_MODE = {
    1:  "car",      # Car, truck, or van  (drove alone + carpool combined)
    2:  "transit",  # Bus
    3:  "transit",  # Subway or elevated rail
    4:  "transit",  # Long-distance train or commuter rail
    5:  "transit",  # Light rail, streetcar, or trolley
    6:  "transit",  # Ferryboat
    7:  "car",      # Taxicab          (road vehicle)
    8:  "car",      # Motorcycle       (road vehicle)
    9:  "bike",     # Bicycle
    10: "walk",     # Walked
    11: "home",     # Worked from home: excluded (no commute trip)
    12: "home",     # Other method:     excluded (unclassified)
}

# The four canonical simulator buckets, pulled from JWTRNS_TO_MODE.
# `home` is left out on purpose; it's the "no trip" sentinel.
SUPPORTED_MODES = ("car", "transit", "bike", "walk")

# JWTRNS codes that map to each canonical mode. Computed from the dict
# so there is exactly one source of truth; downstream filters should
# look up here rather than hardcoding code sets.
MODE_TO_JWTRNS = {
    mode: frozenset(c for c, m in JWTRNS_TO_MODE.items() if m == mode)
    for mode in SUPPORTED_MODES
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
        # serial_raw looks like "1,2019HU0061303", so keep the part after the comma
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
        # A truncated line can leave fewer person ids than num_people claims.
        # Reconcile num_people to the count we actually parsed so downstream
        # consumers never index past the real list.
        if len(person_ids) != num_people:
            logger.debug(
                "hld bld_id=%d declared %d people but parsed %d ids; "
                "reconciling num_people to %d",
                bld_id, num_people, len(person_ids), len(person_ids),
            )
            num_people = len(person_ids)
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
    """Pull the ScheduleActivity list out of the trailing quoted schedule field.

    An empty ``""`` (the usual case for non-workers and uncovered modes)
    gives back an empty list. Malformed content is dropped quietly: the
    cityscape generator owns the schema, and one bad tuple shouldn't take
    down the whole parse.
    """
    inner = raw.strip().strip('"')
    if not inner:
        return []
    return [
        ScheduleActivity(
            dow_start=int(m.group(1)),
            dow_end=int(m.group(2)),
            time_s=int(m.group(3)),
            bld_id=int(m.group(4)),
        )
        for m in _SCHEDULE_TUPLE_RE.finditer(inner)
    ]


def _parse_person_line(line: str, parts: list[str]) -> Optional[Person]:
    """Parse one 'per' line into a Person.

    ``parts`` is the whitespace-split prefix, which covers the seven scalar
    fields. ``line`` is the raw line, which we need to recover the trailing
    quoted schedule from, since split() would tear apart the parentheses
    inside the quotes.
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
    """Parse a modelgen file into structured data.

    Args:
        model_path: the model file (e.g. la_model.txt).
        bbox: optional (south, north, west, east) box in WGS84. With it, only
              buildings whose centroid lands inside are kept; without it, all
              of them are.
        car_only: when True (the default, since SimForge runs car traffic),
                  keep only car-compatible commuters (JWTRNS in {1, 7, 8}:
                  car/truck/van, taxicab, motorcycle, all of which map to
                  canonical car). Ignored when `modes` is given.
        modes: optional list of canonical modes to keep (e.g.
               ["car", "transit"]). When set, it overrides `car_only` and
               keeps anyone whose JWTRNS maps into the list.

    Returns:
        A ModelData with the buildings, households, and persons.
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
                    # Bad quoting on a building line, skip it rather than crash
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
        # Caller asked for specific modes, so filter to those.
        allowed_jwtrns = {code for code, m in JWTRNS_TO_MODE.items() if m in modes}
        filtered_persons = [
            p for p in filtered_persons
            if p.transport_mode in allowed_jwtrns and p.commute_min > 0
        ]
    elif car_only:
        # Derive from JWTRNS_TO_MODE so this filter can't drift away from the
        # dict. That drift is exactly what hid bus and WFH trips inflating the
        # car pool for months back in v0-v4.
        car_modes = MODE_TO_JWTRNS["car"]
        filtered_persons = [
            p for p in filtered_persons
            if p.transport_mode in car_modes and p.commute_min > 0
        ]

    logger.info(
        "After filtering: %d buildings, %d households, %d persons",
        len(all_buildings), len(filtered_hlds), len(filtered_persons),
    )

    # Capture ages for every parsed person, including the non-commuters the
    # mode/car_only filter just dropped (kids with JWTRNS=-1 especially).
    # Downstream household-composition queries need them, e.g. HBSchool
    # detection.
    age_by_per_id = {p.per_id: p.age for p in all_persons}

    # --- Build result ---
    result = ModelData(
        buildings=all_buildings,
        households=filtered_hlds,
        persons=filtered_persons,
        age_by_per_id=age_by_per_id,
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
