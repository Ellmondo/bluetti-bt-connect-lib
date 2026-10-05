from enum import Enum, unique


@unique
class EmsControlMode(Enum):
    """Register 2241, low nibble: who is in charge of the battery.

    Values from BLUETTI's app. 3, 5 and 7 are set by the cloud (VPP, dynamic
    pricing); the app treats the unit as remotely controlled while they are
    active and only lets the user switch between 0/4 (local) and 8 (AI).
    """

    LOCAL = 0
    CLOUD = 3
    LOCAL_SELECTED = 4
    DYNAMIC_PRICING = 5
    VPP = 7
    AI = 8


CLOUD_CONTROLLED_EMS_MODES = (
    EmsControlMode.CLOUD,
    EmsControlMode.DYNAMIC_PRICING,
    EmsControlMode.VPP,
)


@unique
class InverterStatus(Enum):
    """Home data register 161, low byte (EBOX, slave 0)."""

    OFF = 0
    OFF_GRID = 1
    GRID_BYPASS = 2
    GRID_CONNECTED = 3
    GRID_CONNECTED_CHARGING = 4
    GRID_CONNECTED_DISCHARGING = 5
    ERROR = 6
    OFF_GRID_ABNORMAL = 7


@unique
class BatteryStatus(Enum):
    """Home data register 103 (EBOX, slave 0)."""

    IDLE = 0
    CHARGING = 1
    DISCHARGING = 2
