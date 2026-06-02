"""One car definition, shared by the SUMO, MATSim, and DTALite adapters.

The point is fairness: if the three engines disagree on how big a car is
or how much road it takes up in a queue, the travel-time spread we report
in audit Q4 stops being about the paradigm and starts being about vehicle
parameters. So we describe the car once, physically, and let each adapter
say it in its own dialect.

The dialects differ in how they account for the gap between vehicles:
SUMO keeps length and minGap separate (queue spacing is length + minGap);
MATSim folds both into a single ``length`` on ``<vehicleType>``; DTALite
has no per-vehicle length at all and expresses the same storage through
passenger-car-equivalents, so PCE = 1.0 lines it up with the other two.

Before V11 these values had drifted apart on their own: SUMO leaned on the
implicit 5.0 m DEFAULT_VEHTYPE, MATSim hardcoded 7.5 m (which happens to be
the right cross-engine equivalent, but nobody had written that down), and
the widths didn't even agree (1.8 vs 1.0 m). Keeping them here means one
edit updates all three adapters.

Values are a typical US sedan plus a 2.5 m comfort gap, matching SUMO's
``passenger`` vClass. Trucks, motorcycles, and TNCs wait for V12.
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------------
# Physical dimensions (meters)
# ---------------------------------------------------------------------------

# Bumper-to-bumper car length, same as SUMO's passenger vClass.
CAR_LENGTH_M: Final[float] = 5.0

# Comfort gap to the car ahead. SUMO carries this in minGap; MATSim folds it
# into length (see CAR_EFFECTIVE_LENGTH_M).
CAR_MIN_GAP_M: Final[float] = 2.5

# What MATSim's <length> actually means: the road one queued car occupies,
# body plus gap.
CAR_EFFECTIVE_LENGTH_M: Final[float] = CAR_LENGTH_M + CAR_MIN_GAP_M  # 7.5

# SUMO passenger width. MATSim used to hardcode an unrealistic 1.0; V11 fixed it.
CAR_WIDTH_M: Final[float] = 1.8


# ---------------------------------------------------------------------------
# Speed (meters per second)
# ---------------------------------------------------------------------------

# Ceiling speed before the edge speed_limit clamps. 40 m/s (144 km/h) is
# above anything a US road class will actually ask for, motorways included.
CAR_MAX_SPEED_MPS: Final[float] = 40.0


# ---------------------------------------------------------------------------
# Microscopic dynamics (SUMO micro / Krauss model)
# ---------------------------------------------------------------------------

# Comfortable accel/decel, both SUMO passenger defaults.
CAR_ACCEL_MPS2: Final[float] = 2.6
CAR_DECEL_MPS2: Final[float] = 4.5

# Krauss driver imperfection: 0.0 is a perfect driver, 1.0 is pure noise.
# SUMO's 0.5 gives realistic small jitter, and it's why SUMO-micro's
# reproducibility R-score sits just under 1.0 (see Table 5.2).
CAR_DRIVER_IMPERFECTION: Final[float] = 0.5


# ---------------------------------------------------------------------------
# Mesoscopic / DTA-relevant
# ---------------------------------------------------------------------------

# Passenger-car equivalents for capacity math: one car counts as one.
# Trucks would be 1.5-2.0, motorcycles 0.4-0.5, but those are past V11 scope.
CAR_PCE: Final[float] = 1.0


# ---------------------------------------------------------------------------
# Engine-specific helpers
# ---------------------------------------------------------------------------

#: SUMO vClass: sets default colour, lane access, and signal compatibility.
#: "passenger" is the standard private car.
SUMO_VCLASS: Final[str] = "passenger"

#: SUMO guiShape: rendering only, no effect on physics.
SUMO_GUI_SHAPE: Final[str] = "passenger"

#: The vType id SUMO routes and vehicles point at. We name it explicitly so
#: it can't be confused with SUMO's built-in DEFAULT_VEHTYPE, whose silent
#: fallback was what hid the V4 cross-engine drift in the first place.
SIMFORGE_CAR_VTYPE_ID: Final[str] = "simforge_car"


def sumo_vtype_xml() -> str:
    """The SUMO <vType> element, ready to drop into routes.rou.xml right
    after <routes>."""
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
    """The whole MATSim vehicles.xml document. Just the one car type for now."""
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
