"""Canonical SimForge vehicle parameters — applied uniformly across the
SUMO, MATSim, and DTALite adapters so cross-engine travel-time spread
(audit Q4) is paradigm-driven rather than vehicle-parameter-driven.

Each engine has its own length/gap convention; we publish a single
*physical* car description and let each adapter translate to that
engine's idiom:

- SUMO splits length (physical) and minGap (gap to next vehicle).
  Effective queue spacing per vehicle = ``length + minGap``.
- MATSim packs length + gap into a single ``length`` attribute on
  ``<vehicleType>``. Effective queue spacing = ``length``.
- DTALite has no per-vehicle length — link capacity expresses the same
  storage via passenger-car-equivalents (PCE). PCE = 1.0 keeps it
  consistent with SUMO/MATSim's queue-storage interpretation.

The pre-V11 adapters disagreed on these values (SUMO defaulted to 5.0 m
length implicit via DEFAULT_VEHTYPE; MATSim hardcoded 7.5 m which IS
the cross-engine equivalent but was never documented as such; widths
disagreed at 1.8 m vs 1.0 m). Centralising here removes the silent
drift and lets future contributors change one number to update all
three adapters.

Picked values reflect a typical US sedan + 2.5 m comfort gap, which is
the SUMO ``passenger`` vClass default. Heavy trucks, motorcycles, and
TNCs are out of scope until V12 (per-JWTRNS vehicle types).
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# Physical dimensions (meters)
# ---------------------------------------------------------------------------

# Physical car length — the body-on-bumper-to-bumper measurement. Matches
# SUMO ``passenger`` vClass default.
CAR_LENGTH_M: Final[float] = 5.0

# Comfort gap to the vehicle in front. SUMO's ``minGap`` attribute carries
# this directly; MATSim folds it into ``length`` (see CAR_EFFECTIVE_LENGTH_M).
CAR_MIN_GAP_M: Final[float] = 2.5

# Effective queue-spacing per vehicle = physical length + minimum gap. This
# is what MATSim's ``<length>`` attribute represents.
CAR_EFFECTIVE_LENGTH_M: Final[float] = CAR_LENGTH_M + CAR_MIN_GAP_M  # 7.5

# Vehicle width — SUMO uses 1.8 for ``passenger`` vClass. MATSim previously
# hardcoded 1.0 (unrealistic) — fixed by V11.
CAR_WIDTH_M: Final[float] = 1.8


# ---------------------------------------------------------------------------
# Speed (meters per second)
# ---------------------------------------------------------------------------

# Maximum free-flow speed before the edge ``speed_limit`` clamps. 40 m/s =
# 144 km/h covers all realistic US road classes including motorways.
CAR_MAX_SPEED_MPS: Final[float] = 40.0


# ---------------------------------------------------------------------------
# Microscopic dynamics (SUMO micro / Krauss model)
# ---------------------------------------------------------------------------

# Comfortable acceleration capability. SUMO ``passenger`` default.
CAR_ACCEL_MPS2: Final[float] = 2.6

# Comfortable deceleration. SUMO ``passenger`` default.
CAR_DECEL_MPS2: Final[float] = 4.5

# Driver imperfection in the Krauss car-following model — 0.0 is perfect,
# 1.0 is maximum noise. SUMO default 0.5 produces realistic small-amplitude
# jitter. Drives the SUMO-micro reproducibility R-score being slightly
# below 1.0 (visible in Table 5.2).
CAR_DRIVER_IMPERFECTION: Final[float] = 0.5


# ---------------------------------------------------------------------------
# Mesoscopic / DTA-relevant
# ---------------------------------------------------------------------------

# Passenger-car equivalents — 1.0 means "this vehicle counts as one PCE"
# in capacity / saturation-flow calculations. Heavy trucks would be 1.5-2.0
# and motorcycles 0.4-0.5; outside V11 scope.
CAR_PCE: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Engine-specific helpers
# ---------------------------------------------------------------------------

#: SUMO ``vClass`` — drives default colour, lane access, traffic-signal
#: compatibility. ``passenger`` is the standard private car class.
SUMO_VCLASS: Final[str] = "passenger"

#: SUMO ``guiShape`` — visual rendering only, no physics impact.
SUMO_GUI_SHAPE: Final[str] = "passenger"

#: Canonical id used to reference the vehicle type from SUMO routes and
#: vehicles. Picked to be unambiguous in adapter output (vs SUMO's built-in
#: ``DEFAULT_VEHTYPE`` whose silent fallback hid the V4 cross-engine drift).
SIMFORGE_CAR_VTYPE_ID: Final[str] = "simforge_car"


def sumo_vtype_xml() -> str:
    """Return the SUMO ``<vType>`` element as a string ready to be embedded
    in a ``routes.rou.xml`` immediately after ``<routes>``."""
    return (
        f'  <vType id="{SIMFORGE_CAR_VTYPE_ID}" '
        f'vClass="{SUMO_VCLASS}" '
        f'guiShape="{SUMO_GUI_SHAPE}" '
        f'length="{CAR_LENGTH_M}" '
        f'minGap="{CAR_MIN_GAP_M}" '
        f'width="{CAR_WIDTH_M}" '
        f'maxSpeed="{CAR_MAX_SPEED_MPS}" '
        f'accel="{CAR_ACCEL_MPS2}" '
        f'decel="{CAR_DECEL_MPS2}" '
        f'sigma="{CAR_DRIVER_IMPERFECTION}"/>'
    )


def matsim_vehicle_type_xml() -> str:
    """Return the full MATSim ``vehicles.xml`` document — only one vehicle
    type for now, the canonical SimForge car."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd"
                    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                    xsi:schemaLocation="http://www.matsim.org/files/dtd http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd">
    <vehicleType id="car">
        <capacity seats="5" standingRoomInPersons="0"/>
        <length meter="{CAR_EFFECTIVE_LENGTH_M}"/>
        <width meter="{CAR_WIDTH_M}"/>
        <maximumVelocity meterPerSecond="{CAR_MAX_SPEED_MPS}"/>
        <passengerCarEquivalents pce="{CAR_PCE}"/>
        <networkMode networkMode="car"/>
        <flowEfficiencyFactor factor="1.0"/>
    </vehicleType>
</vehicleDefinitions>'''
