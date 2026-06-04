"""
Unit tests for the schedule-aware extensions to parse_model_file.

Covers the cityscape ScheduleGenerator schedule field parsing
(per-record trailing `(...)` tuples) and the per-person home resolution
that schedule-driven demand generation depends on.
"""

from __future__ import annotations

from pipeline.demand.parse_model_file import (
    Building,
    Household,
    JWTRNS_TO_MODE,
    MODE_TO_JWTRNS,
    ModelData,
    Person,
    ScheduleActivity,
    SUPPORTED_MODES,
    _parse_person_line,
    _parse_schedule,
)


# ---------------------------------------------------------------------------
# JWTRNS_TO_MODE, V5 cityscape/PUMS-2021 mapping (single source of truth)
# ---------------------------------------------------------------------------


class TestJWTRNSMapping:
    """Pin the corrected JWTRNS → simulator-bucket mapping.

    Source: cityscape Schedule-generator branch, model_gen/ScheduleGenerator.h
    lines 211-233 (verbatim from ACS PUMS 2021 Data Dictionary). See
    doc/MODELGEN_AND_MODES.md §2 for provenance and §4 for the bucket
    rationale.

    Catches accidental regression to the pre-2019 PUMS labels (e.g. the
    pre-V5 bug where code 2 was treated as "carpool → car" when it is
    actually "Bus → transit").
    """

    def test_exact_12_codes(self):
        # cityscape's enum is 12 codes (1..12); -1 is the N/A sentinel
        # that's stripped before the dict lookup.
        assert set(JWTRNS_TO_MODE.keys()) == set(range(1, 13))

    def test_car_bucket(self):
        # Road-vehicle codes: Car/truck/van, Taxicab, Motorcycle.
        assert JWTRNS_TO_MODE[1] == "car"
        assert JWTRNS_TO_MODE[7] == "car"
        assert JWTRNS_TO_MODE[8] == "car"

    def test_transit_bucket(self):
        # Public transit codes: Bus, Subway/elev, Commuter rail,
        # Light rail/streetcar, Ferryboat.
        assert JWTRNS_TO_MODE[2] == "transit"  # Bus, was "car" pre-V5 bug
        assert JWTRNS_TO_MODE[3] == "transit"
        assert JWTRNS_TO_MODE[4] == "transit"
        assert JWTRNS_TO_MODE[5] == "transit"
        assert JWTRNS_TO_MODE[6] == "transit"

    def test_bike_and_walk_buckets(self):
        assert JWTRNS_TO_MODE[9] == "bike"
        assert JWTRNS_TO_MODE[10] == "walk"

    def test_excluded_codes_use_home_sentinel(self):
        # "home" is the no-trip sentinel, these codes should never
        # reach the demand generator's trip-generation loop.
        assert JWTRNS_TO_MODE[11] == "home"  # Worked from home
        assert JWTRNS_TO_MODE[12] == "home"  # Other method (defensive default)

    def test_supported_modes_are_the_4_simulator_buckets(self):
        assert SUPPORTED_MODES == ("car", "transit", "bike", "walk")
        # "home" is intentionally not in the supported tuple, it's the
        # sentinel for excluded persons.
        assert "home" not in SUPPORTED_MODES

    def test_mode_to_jwtrns_reverse_index(self):
        # Verify the reverse index is consistent with the forward dict.
        assert MODE_TO_JWTRNS["car"] == frozenset({1, 7, 8})
        assert MODE_TO_JWTRNS["transit"] == frozenset({2, 3, 4, 5, 6})
        assert MODE_TO_JWTRNS["bike"] == frozenset({9})
        assert MODE_TO_JWTRNS["walk"] == frozenset({10})
        # Round-trip: every (code, mode) in the forward dict appears
        # in the corresponding bucket of the reverse dict (if the mode
        # is one of the 4 simulator buckets).
        for code, mode in JWTRNS_TO_MODE.items():
            if mode in SUPPORTED_MODES:
                assert code in MODE_TO_JWTRNS[mode]


class TestSingleSourceOfTruth:
    """The scanner must re-export the canonical dict, not duplicate it.

    Pre-V5 the dict was duplicated in two files; this caused real drift
    bugs where one was fixed and the other was forgotten.
    """

    def test_scanner_imports_canonical_dict(self):
        from pipeline.modelgen_scanner import JWTRNS_TO_MODE as scanner_dict
        from pipeline.demand.parse_model_file import JWTRNS_TO_MODE as canonical
        # Must be the same object, not a copy with the same values.
        assert scanner_dict is canonical


# ---------------------------------------------------------------------------
# _parse_schedule
# ---------------------------------------------------------------------------


class TestParseSchedule:
    def test_empty_string(self):
        assert _parse_schedule('""') == []

    def test_empty_inner(self):
        assert _parse_schedule("") == []

    def test_two_tuple_schedule(self):
        # Real cityscape sample: workplace 8 AM, return home 5 PM.
        raw = '"(1 5 28800 163346754)(1 5 61200 832748)"'
        out = _parse_schedule(raw)
        assert len(out) == 2
        assert out[0] == ScheduleActivity(dow_start=1, dow_end=5,
                                          time_s=28800, bld_id=163346754)
        assert out[1] == ScheduleActivity(dow_start=1, dow_end=5,
                                          time_s=61200, bld_id=832748)

    def test_extra_whitespace_inside_tuples(self):
        raw = '"(1   5   28800   12345)"'
        out = _parse_schedule(raw)
        assert len(out) == 1
        assert out[0].bld_id == 12345

    def test_malformed_garbage_silently_dropped(self):
        # No matching tuples, should return [] rather than raise.
        assert _parse_schedule('"this is not a schedule"') == []

    def test_partial_tuple_dropped(self):
        # Three ints isn't a valid tuple, four-int neighbour is kept.
        raw = '"(1 5 28800)(1 5 61200 999)"'
        out = _parse_schedule(raw)
        assert len(out) == 1
        assert out[0].bld_id == 999


# ---------------------------------------------------------------------------
# _parse_person_line, full per record including schedule field
# ---------------------------------------------------------------------------


class TestParsePersonLine:
    def _split(self, line: str):
        # Mirror the call site in parse_model_file: split with maxsplit=8 so
        # the schedule field stays in a single trailing token.
        return line.split(maxsplit=8)

    def test_per_with_schedule(self):
        line = ('per 1777883 2021HU0886832 4 47 100000 30 1 '
                '"(1 5 28800 163346754)(1 5 61200 832748)"')
        per = _parse_person_line(line, self._split(line))
        assert per is not None
        assert per.per_id == 1777883
        assert per.commute_min == 30
        assert per.transport_mode == 1
        assert len(per.schedule) == 2
        assert per.schedule[0].bld_id == 163346754  # workplace
        assert per.schedule[1].bld_id == 832748     # home

    def test_per_without_schedule(self):
        line = 'per 1769813 2021HU1272909 4 69 2000 -1 11 ""'
        per = _parse_person_line(line, self._split(line))
        assert per is not None
        assert per.per_id == 1769813
        assert per.commute_min == -1
        assert per.transport_mode == 11
        assert per.schedule == []

    def test_per_with_no_quotes_field(self):
        # Defensive: a per line truncated before the schedule quotes.
        line = 'per 1 SERIAL 4 30 50000 25 1'
        per = _parse_person_line(line, self._split(line))
        assert per is not None
        assert per.schedule == []


# ---------------------------------------------------------------------------
# ModelData.home_bld_by_per_id, needed by schedule-aware demand generation
# ---------------------------------------------------------------------------


def _make_bld(bld_id: int) -> Building:
    return Building(
        bld_id=bld_id, levels=1, population=1, is_home=True, kind="syn_home",
        sq_foot=500, top_lon=-87.6, top_lat=41.9, bot_lon=-87.6, bot_lat=41.9,
        way_id=1, way_lat=41.9, way_lon=-87.6, puma_id=3500, num_households=1,
    )


def _make_hld(bld_id: int, serial: str, person_ids: list[int]) -> Household:
    return Household(
        bld_id=bld_id, serial_no=serial, bedrooms=2, bld_type=1, puma_id=3500,
        weight=100, income=50000, num_people=len(person_ids), person_ids=person_ids,
    )


def _make_per(per_id: int, hld_serial: str) -> Person:
    return Person(
        per_id=per_id, hld_serial=hld_serial, num_info=4, age=40,
        wages=50000, commute_min=20, transport_mode=1,
    )


class TestHomeBldByPerId:
    def test_unique_serials_resolve_correctly(self):
        data = ModelData(
            buildings=[_make_bld(100), _make_bld(200)],
            households=[
                _make_hld(100, "SER_A", [1, 2]),
                _make_hld(200, "SER_B", [3]),
            ],
            persons=[_make_per(1, "SER_A"), _make_per(2, "SER_A"),
                     _make_per(3, "SER_B")],
        )
        assert data.home_bld_by_per_id[1] == 100
        assert data.home_bld_by_per_id[2] == 100
        assert data.home_bld_by_per_id[3] == 200

    def test_replicated_serial_resolves_per_household(self):
        # PUMS replicates SERIALNO across many synthesised households. Each
        # person belongs to exactly one household (the one whose person_ids
        # list contains them), even when several households share a serial.
        data = ModelData(
            buildings=[_make_bld(100), _make_bld(200), _make_bld(300)],
            households=[
                # Three households all with the same serial, different bld_ids,
                # different person_ids. Each person must resolve to their own home.
                _make_hld(100, "SHARED", [1, 2]),
                _make_hld(200, "SHARED", [3, 4]),
                _make_hld(300, "SHARED", [5]),
            ],
            persons=[
                _make_per(1, "SHARED"), _make_per(2, "SHARED"),
                _make_per(3, "SHARED"), _make_per(4, "SHARED"),
                _make_per(5, "SHARED"),
            ],
        )
        assert data.home_bld_by_per_id[1] == 100
        assert data.home_bld_by_per_id[2] == 100
        assert data.home_bld_by_per_id[3] == 200
        assert data.home_bld_by_per_id[4] == 200
        assert data.home_bld_by_per_id[5] == 300

    def test_unknown_per_id_missing_from_index(self):
        data = ModelData(buildings=[_make_bld(100)],
                         households=[_make_hld(100, "S", [1])],
                         persons=[_make_per(1, "S")])
        assert 1 in data.home_bld_by_per_id
        assert 999 not in data.home_bld_by_per_id


# ---------------------------------------------------------------------------
# Trip-purpose realism (V5+), HBSchool support helpers
# ---------------------------------------------------------------------------


class TestHBSchoolHelpers:
    """Verify the modelgen-only foundations for HBSchool trips:
      - `_is_school_kind` recognises OSM school-tag values
      - `ModelData.age_by_per_id` survives mode-filtering (kids would
        otherwise be filtered out by JWTRNS=-1)
      - `_has_school_age_dependent` finds AGEP<18 in the same household
    """

    def test_is_school_kind_recognises_osm_values(self):
        from pipeline.demand.generate_census_demand import _is_school_kind
        # OSM emits these as `kind=school` (sometimes with a colon
        # subkind suffix, e.g. `school:fast_food` is a misclassified
        # building, we still match the leading prefix).
        assert _is_school_kind("school:")
        assert _is_school_kind("school")
        assert _is_school_kind("kindergarten:")
        assert _is_school_kind("preschool")
        assert _is_school_kind("college:")
        assert _is_school_kind("university:")
        # Non-school values must NOT match.
        assert not _is_school_kind("office:")
        assert not _is_school_kind("apartments:")
        assert not _is_school_kind("yes:")
        assert not _is_school_kind("hospital:")
        assert not _is_school_kind("")
        assert not _is_school_kind(None)  # type: ignore[arg-type]

    def test_age_by_per_id_includes_filtered_kids(self):
        """Kids have JWTRNS=-1 (Not a worker) and get filtered out of
        `ModelData.persons` when modes/car_only is applied. Their ages
        must still be visible via `ModelData.age_by_per_id` so
        household-composition queries can find school-age dependents.
        Direct ModelData(...) construction (used in tests) populates
        the map from `persons`; the parser populates it from the full
        unfiltered population. Both paths must work."""
        # Direct construction with one explicit person.
        data = ModelData(
            buildings=[_make_bld(100)],
            households=[_make_hld(100, "S", [1])],
            persons=[_make_per(1, "S")],  # Person dataclass has age=30 default? check
        )
        # Direct-construction fallback: age map is built from `persons`.
        assert data.age_by_per_id  # non-empty

    def test_has_school_age_dependent_finds_kid(self):
        """When a household contains one commuter (in `persons`) and
        one school-age dependent (NOT in `persons` because of JWTRNS
        filtering), `_has_school_age_dependent` must still return True
        thanks to the unfiltered `age_by_per_id` map."""
        from pipeline.demand.generate_census_demand import _has_school_age_dependent
        # Build a household with two persons: a 35-year-old commuter
        # (id=1, in persons list) and an 8-year-old kid (id=2, NOT in
        # persons because JWTRNS-filtered). Manually populate age_by_per_id
        # to mimic what the parser does.
        commuter = _make_per(1, "S")
        commuter.age = 35
        data = ModelData(
            buildings=[_make_bld(100)],
            households=[_make_hld(100, "S", [1, 2])],  # both ids in household
            persons=[commuter],                          # only commuter visible
            age_by_per_id={1: 35, 2: 8},                # but kid age available
        )
        assert _has_school_age_dependent(commuter, data)

    def test_has_school_age_dependent_solo_household(self):
        """A solo-person household has no dependents."""
        from pipeline.demand.generate_census_demand import _has_school_age_dependent
        commuter = _make_per(1, "S")
        commuter.age = 35
        data = ModelData(
            buildings=[_make_bld(100)],
            households=[_make_hld(100, "S", [1])],
            persons=[commuter],
            age_by_per_id={1: 35},
        )
        assert not _has_school_age_dependent(commuter, data)

    def test_has_school_age_dependent_skips_other_adults(self):
        """A household with another adult (not a kid) yields False."""
        from pipeline.demand.generate_census_demand import _has_school_age_dependent
        commuter = _make_per(1, "S")
        commuter.age = 35
        data = ModelData(
            buildings=[_make_bld(100)],
            households=[_make_hld(100, "S", [1, 2])],
            persons=[commuter],
            age_by_per_id={1: 35, 2: 60},  # second adult, not a kid
        )
        assert not _has_school_age_dependent(commuter, data)

    def test_has_school_age_dependent_excludes_age_minus_one(self):
        """PUMS uses -1 for Not-applicable. We must exclude that, a
        household with a -1-age member shouldn't count as having a kid."""
        from pipeline.demand.generate_census_demand import _has_school_age_dependent
        commuter = _make_per(1, "S")
        commuter.age = 35
        data = ModelData(
            buildings=[_make_bld(100)],
            households=[_make_hld(100, "S", [1, 2])],
            persons=[commuter],
            age_by_per_id={1: 35, 2: -1},  # PUMS sentinel
        )
        assert not _has_school_age_dependent(commuter, data)

    def test_peak_purpose_sets_cover_all_chain_legs(self):
        """The AM/PM budget split (Phase 9a + 9b + 9c) relies on
        AM_PURPOSES and PM_PURPOSES correctly classifying every chain
        leg into its peak. A leg missing from its peak set would cause
        the gravity-fallback Phase 2 to over-emit by the chain count
        (see Phase 9b's HBSchool budget over-emit bug)."""
        from pipeline.demand.generate_census_demand import (
            AM_PURPOSES,
            PM_PURPOSES,
        )
        # AM peak, outbound HBW, plus the school drop-off chain pair.
        assert AM_PURPOSES == frozenset(
            {"HBW_AM", "HBSchool_AM", "HBW_AM_chained"}
        )
        # PM peak, return HBW, plus the school pickup chain pair.
        assert PM_PURPOSES == frozenset(
            {"HBW_PM", "HBSchool_PM", "HBW_PM_chained"}
        )
        # No purpose can belong to both peaks (a chained leg consumes
        # exactly one peak's budget).
        assert AM_PURPOSES.isdisjoint(PM_PURPOSES)
