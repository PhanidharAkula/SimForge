"""
Unit tests for the schedule-aware extensions to parse_model_file.

Covers the cityscape ScheduleGenerator schedule field parsing
(per-record trailing `(...)` tuples) and the per-person home resolution
that schedule-driven demand generation depends on.
"""

from __future__ import annotations

import pytest

from pipeline.demand.parse_model_file import (
    Building,
    Household,
    ModelData,
    Person,
    ScheduleActivity,
    _parse_person_line,
    _parse_schedule,
)


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
        assert out[0] == ScheduleActivity(activity_type=1, subtype=5,
                                          time_s=28800, bld_id=163346754)
        assert out[1] == ScheduleActivity(activity_type=1, subtype=5,
                                          time_s=61200, bld_id=832748)

    def test_extra_whitespace_inside_tuples(self):
        raw = '"(1   5   28800   12345)"'
        out = _parse_schedule(raw)
        assert len(out) == 1
        assert out[0].bld_id == 12345

    def test_malformed_garbage_silently_dropped(self):
        # No matching tuples — should return [] rather than raise.
        assert _parse_schedule('"this is not a schedule"') == []

    def test_partial_tuple_dropped(self):
        # Three ints isn't a valid tuple, four-int neighbour is kept.
        raw = '"(1 5 28800)(1 5 61200 999)"'
        out = _parse_schedule(raw)
        assert len(out) == 1
        assert out[0].bld_id == 999


# ---------------------------------------------------------------------------
# _parse_person_line — full per record including schedule field
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
# ModelData.home_bld_by_per_id — needed by schedule-aware demand generation
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
        # list contains them) — even when several households share a serial.
        data = ModelData(
            buildings=[_make_bld(100), _make_bld(200), _make_bld(300)],
            households=[
                # Three households all with the same serial — different bld_ids,
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
