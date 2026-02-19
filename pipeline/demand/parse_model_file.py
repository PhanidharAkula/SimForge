"""
Parse modelgen output files (la_model.txt, nyc_model.txt, etc.).

These files are produced by an activity-based population synthesizer that
integrates OpenStreetMap road networks, LandScan population grids, and
U.S. Census PUMS microdata into a single flat-text model.

This module extracts building, household, and person records, optionally
filtering to a geographic bounding box, and returns structured data
suitable for census-calibrated demand generation.

Record format (fields are space-separated):
  bld  ID levels population attributes isHome kind sqFoot
       topLon topLat botLon botLat wayID wayLat wayLon pumaID #households
  hld  bldID "SMARTPHONE,SERIALNO" bedRooms BLDtype pumaID WGTP HINCP
       #people peopleIDs...
  per  perID HldID #info AGEP WAGP JWMNP JWTRNS schedule

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
class Person:
    """A person from the model file."""
    per_id: int
    hld_serial: str
    num_info: int
    age: int            # AGEP
    wages: int          # WAGP (-1 = N/A)
    commute_min: int    # JWMNP — commute time in minutes (-1 = N/A)
    transport_mode: int # JWTRNS code (-1 = N/A)


@dataclass
class ModelData:
    """Parsed and filtered model data for a city."""
    buildings: list[Building]
    households: list[Household]
    persons: list[Person]
    # Indexes for fast lookup
    bld_by_id: dict[int, Building] = field(default_factory=dict)
    hld_by_bld: dict[int, list[Household]] = field(default_factory=dict)
    per_by_id: dict[int, Person] = field(default_factory=dict)

    def __post_init__(self):
        self.bld_by_id = {b.bld_id: b for b in self.buildings}
        self.hld_by_bld = {}
        for h in self.households:
            self.hld_by_bld.setdefault(h.bld_id, []).append(h)
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


def _parse_person_line(parts: list[str]) -> Optional[Person]:
    """Parse a single 'per' line into a Person object."""
    try:
        per_id = int(parts[1])
        hld_serial = parts[2]
        num_info = int(parts[3])
        age = int(parts[4])
        wages = int(parts[5])
        commute_min = int(parts[6])
        transport_mode = int(parts[7])
        return Person(
            per_id=per_id, hld_serial=hld_serial, num_info=num_info,
            age=age, wages=wages, commute_min=commute_min,
            transport_mode=transport_mode,
        )
    except (IndexError, ValueError) as e:
        logger.debug("Skipping malformed per line: %s", e)
        return None


def parse_model_file(
    model_path: Path,
    bbox: Optional[tuple[float, float, float, float]] = None,
    car_only: bool = True,
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
                parts = shlex.split(line, posix=True)
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
                parts = line.split()
                per = _parse_person_line(parts)
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
    if car_only:
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
        parts = [float(x.strip()) for x in args.bbox.split(",")]
        bbox = (parts[0], parts[1], parts[2], parts[3])

    data = parse_model_file(Path(args.model_path), bbox=bbox)

    # Summary
    residential = [b for b in data.buildings if b.is_home]
    total_pop = sum(b.population for b in data.buildings)
    commuters = [p for p in data.persons if p.commute_min > 0]
    commute_times = [p.commute_min for p in commuters]

    print(f"\n{'='*50}")
    print(f"  Model file: {args.model_path}")
    print(f"  Buildings:  {len(data.buildings)} ({len(residential)} residential)")
    print(f"  Population: {total_pop}")
    print(f"  Households: {len(data.households)}")
    print(f"  Persons:    {len(data.persons)} ({len(commuters)} car commuters)")
    if commute_times:
        avg = sum(commute_times) / len(commute_times)
        print(f"  Commute:    avg {avg:.0f} min, range {min(commute_times)}-{max(commute_times)} min")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
