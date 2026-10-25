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


@unique
class BatteryMaintenanceStatus(Enum):
    """Home data register 106, bits 0-3 (EBOX, slave 0).

    BLUETTI's battery maintenance ("pack aging"): a full discharge followed
    by a full charge, which the app suggests every 3-6 months to rebalance
    the cells. Values as the app shows them.
    """

    NOT_NEEDED = 0
    DUE = 1
    IN_PROGRESS = 2
    FINISHED = 3
    STOPPED = 4
    DUE_CONDITIONS_NOT_MET = 5


@unique
class BatteryMaintenanceStopReason(Enum):
    """Home data register 106, bits 8-11: why a maintenance run stopped.

    1-6 are the app's reasons. The app treats 7-15 alike ("maintenance
    conditions not triggered, no maintenance needed"); they are all reported
    as NOT_TRIGGERED.
    """

    NONE = 0
    GRID_OFFLINE = 1
    TEMPERATURE_HIGH = 2
    TEMPERATURE_LOW = 3
    PACK_COUNT_ABNORMAL = 4
    CHARGE_FAILED = 5
    DISCHARGE_FAILED = 6
    NOT_TRIGGERED = 7
