"""Tests for `adapters/common/vehicle_types.py` and the V11+ cross-engine
vehicle parameter alignment.

Pre-V11 the SUMO adapter relied on SUMO's silent ``DEFAULT_VEHTYPE`` and
the MATSim adapter hardcoded ``length=7.5`` / ``width=1.0``. The two
ostensibly disagreed (5.0 m vs 7.5 m) but were actually equivalent
(7.5 m = 5.0 m + 2.5 m gap, with the gap conventions differing). V11+
publishes a single canonical car description and lets each adapter
translate to its idiom.

These tests pin:
  - the canonical constants (any future change is a deliberate edit, not
    a silent drift)
  - the SUMO vType XML actually contains the canonical values
  - the MATSim vehicleDefinitions XML actually contains the canonical values
  - the SUMO physical (length+gap) ≡ MATSim effective length identity
"""

from __future__ import annotations

import re

from adapters.common.vehicle_types import (
    CAR_ACCEL_MPS2,
    CAR_DECEL_MPS2,
    CAR_DRIVER_IMPERFECTION,
    CAR_EFFECTIVE_LENGTH_M,
    CAR_LENGTH_M,
    CAR_MAX_SPEED_MPS,
    CAR_MIN_GAP_M,
    CAR_PCE,
    CAR_WIDTH_M,
    SIMFORGE_CAR_VTYPE_ID,
    SUMO_VCLASS,
    matsim_vehicle_type_xml,
    sumo_vtype_xml,
)


class TestCanonicalConstants:
    """Pin the V11+ canonical values. Any change here is a deliberate
    realism call, not a silent drift."""

    def test_car_length_is_passenger_default(self):
        assert CAR_LENGTH_M == 5.0

    def test_min_gap_matches_sumo_default(self):
        assert CAR_MIN_GAP_M == 2.5

    def test_effective_length_is_length_plus_gap(self):
        """The MATSim/SUMO equivalence relies on this identity:
        SUMO physical length + minGap == MATSim effective length."""
        assert CAR_EFFECTIVE_LENGTH_M == CAR_LENGTH_M + CAR_MIN_GAP_M
        assert CAR_EFFECTIVE_LENGTH_M == 7.5

    def test_width_is_realistic(self):
        # Pre-V11 MATSim hardcoded 1.0 m which is a motorcycle, not a car.
        assert CAR_WIDTH_M == 1.8

    def test_max_speed_covers_motorways(self):
        # 40 m/s = 144 km/h covers all US road classes; edge speed_limit
        # clamps to the road's actual limit in practice.
        assert CAR_MAX_SPEED_MPS == 40.0

    def test_pce_is_one(self):
        # Heavy trucks would be 1.5-2.0 and motorcycles 0.4-0.5; out of
        # V11 scope.
        assert CAR_PCE == 1.0

    def test_dynamics_match_sumo_passenger_class(self):
        assert CAR_ACCEL_MPS2 == 2.6
        assert CAR_DECEL_MPS2 == 4.5
        assert 0.0 <= CAR_DRIVER_IMPERFECTION <= 1.0
        assert CAR_DRIVER_IMPERFECTION == 0.5


class TestSumoVTypeXml:
    """The emitted ``<vType>`` element must carry the canonical values
    so SUMO doesn't silently fall back to ``DEFAULT_VEHTYPE``."""

    def test_emits_vtype_element(self):
        xml = sumo_vtype_xml()
        assert xml.lstrip().startswith("<vType")
        assert xml.rstrip().endswith("/>")

    def test_carries_simforge_car_id(self):
        xml = sumo_vtype_xml()
        assert f'id="{SIMFORGE_CAR_VTYPE_ID}"' in xml
        assert SIMFORGE_CAR_VTYPE_ID == "simforge_car"

    def test_carries_canonical_length_and_gap(self):
        xml = sumo_vtype_xml()
        assert f'length="{CAR_LENGTH_M}"' in xml
        assert f'minGap="{CAR_MIN_GAP_M}"' in xml

    def test_carries_canonical_speed_and_dynamics(self):
        xml = sumo_vtype_xml()
        assert f'maxSpeed="{CAR_MAX_SPEED_MPS}"' in xml
        assert f'accel="{CAR_ACCEL_MPS2}"' in xml
        assert f'decel="{CAR_DECEL_MPS2}"' in xml
        assert f'sigma="{CAR_DRIVER_IMPERFECTION}"' in xml

    def test_carries_passenger_vclass(self):
        xml = sumo_vtype_xml()
        assert f'vClass="{SUMO_VCLASS}"' in xml
        assert SUMO_VCLASS == "passenger"


class TestMatsimVehicleTypeXml:
    """MATSim's vehicleDefinitions document must carry the canonical
    values translated to its idiom (length = effective spacing, not
    physical body length)."""

    def test_emits_complete_document(self):
        xml = matsim_vehicle_type_xml()
        assert xml.startswith('<?xml')
        assert "<vehicleDefinitions" in xml
        assert "</vehicleDefinitions>" in xml

    def test_uses_effective_length_not_physical(self):
        """MATSim's <length> attribute is physical+gap (its convention).
        Pre-V11 the value was 7.5 but the rationale was undocumented;
        V11+ ties it to the canonical CAR_EFFECTIVE_LENGTH_M constant."""
        xml = matsim_vehicle_type_xml()
        m = re.search(r'<length meter="([\d.]+)"/>', xml)
        assert m is not None, "MATSim XML missing <length> element"
        assert float(m.group(1)) == CAR_EFFECTIVE_LENGTH_M
        assert float(m.group(1)) == 7.5

    def test_width_is_canonical(self):
        xml = matsim_vehicle_type_xml()
        m = re.search(r'<width meter="([\d.]+)"/>', xml)
        assert m is not None
        assert float(m.group(1)) == CAR_WIDTH_M
        # Pre-V11 MATSim emitted width=1.0 (motorcycle), verify the fix.
        assert float(m.group(1)) == 1.8

    def test_max_speed_matches_canonical(self):
        xml = matsim_vehicle_type_xml()
        m = re.search(
            r'<maximumVelocity meterPerSecond="([\d.]+)"/>', xml
        )
        assert m is not None
        assert float(m.group(1)) == CAR_MAX_SPEED_MPS

    def test_pce_matches_canonical(self):
        xml = matsim_vehicle_type_xml()
        m = re.search(r'<passengerCarEquivalents pce="([\d.]+)"/>', xml)
        assert m is not None
        assert float(m.group(1)) == CAR_PCE


class TestCrossEngineEquivalence:
    """The whole point of V11+ is that SUMO and MATSim physically agree
    on per-vehicle queue spacing despite their different conventions."""

    def test_sumo_physical_plus_gap_equals_matsim_effective(self):
        sumo_xml = sumo_vtype_xml()
        matsim_xml = matsim_vehicle_type_xml()

        sumo_length = float(re.search(r'length="([\d.]+)"', sumo_xml).group(1))
        sumo_gap = float(re.search(r'minGap="([\d.]+)"', sumo_xml).group(1))
        matsim_length = float(
            re.search(r'<length meter="([\d.]+)"/>', matsim_xml).group(1)
        )

        assert sumo_length + sumo_gap == matsim_length

    def test_sumo_and_matsim_max_speed_agree(self):
        sumo_xml = sumo_vtype_xml()
        matsim_xml = matsim_vehicle_type_xml()

        sumo_speed = float(
            re.search(r'maxSpeed="([\d.]+)"', sumo_xml).group(1)
        )
        matsim_speed = float(
            re.search(r'<maximumVelocity meterPerSecond="([\d.]+)"/>',
                      matsim_xml).group(1)
        )

        assert sumo_speed == matsim_speed
