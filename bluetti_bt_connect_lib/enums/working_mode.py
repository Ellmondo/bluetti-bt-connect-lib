from enum import Enum, unique


@unique
class WorkingMode(Enum):
    CUSTOM = 1
    SELF_CONSUMPTION = 2
    BACKUP = 4
    TIME_OF_USE = 5
    # Self-consumption with export to the grid. BLUETTI's app offers it only
    # on the EP2000 and EP19K.
    SELF_CONSUMPTION_EXPORT = 11
