"""Fields for status words, bit flags and multi-register records.

Layouts follow BLUETTI's own app (ProtocolParserV2), checked against a real
EP2000 + EBOX. Byte order is big-endian within a register; 32-bit values are
low word first.
"""

import struct
from enum import Enum
from typing import List, Type, TypeVar

from . import BoolField, DeviceField, FieldName
from .alarm_codes import TABLE_B, TABLE_E

E = TypeVar("E", bound=Enum)


def _words(data: bytes) -> List[int]:
    return list(struct.unpack(f"!{len(data) // 2}H", data))


def _signed(word: int) -> int:
    return word - 0x10000 if word & 0x8000 else word


class MaskedEnumField(DeviceField):
    """An enum held in part of a register, e.g. its low byte or low nibble."""

    def __init__(self, name: FieldName, address: int, e: Type[E], mask: int = 0xFFFF):
        super().__init__(name, address, 1)
        self.e = e
        self.mask = mask

    def parse(self, data: bytes) -> E | None:
        val = struct.unpack("!H", data)[0] & self.mask
        if val not in [m.value for m in self.e]:
            return None
        return self.e(val)


class BitMaskField(BoolField):
    """True when any of the bits in `mask` is set. Shown as a binary sensor."""

    def __init__(self, name: FieldName, address: int, mask: int):
        super().__init__(name, address)
        self.mask = mask

    def parse(self, data: bytes) -> bool:
        return bool(struct.unpack("!H", data)[0] & self.mask)


class LowByteOffsetField(DeviceField):
    """The register's low byte plus an offset; 0 means no reading.

    The EBOX reports WiFi signal strength this way: dBm = low byte - 256.
    """

    def __init__(self, name: FieldName, address: int, offset: int):
        super().__init__(name, address, 1)
        self.offset = offset

    def parse(self, data: bytes) -> int | None:
        low = struct.unpack("!H", data)[0] & 0xFF
        if low == 0:
            return None
        return low + self.offset


class FirmwareVersionField(DeviceField):
    """One firmware version from the inverter's software list.

    The list starts with a count word, followed by entries of three registers:
    the MCU type (1 ARM, 2 DSP, 3 BMS, ...) and a 32-bit version, low word
    first, shown with two decimals (503222 -> 5032.22).
    """

    def __init__(self, name: FieldName, address: int, mcu_type: int, entries: int = 6):
        super().__init__(name, address, 1 + 3 * entries)
        self.mcu_type = mcu_type
        self.entries = entries

    def parse(self, data: bytes) -> str | None:
        words = _words(data)
        count = min(words[0] & 0xFF, self.entries)
        for i in range(count):
            mcu, low, high = words[1 + 3 * i : 4 + 3 * i]
            if mcu == self.mcu_type:
                version = low + (high << 16)
                if version == 0:
                    return None
                return f"{version // 100}.{version % 100:02d}"
        return None


class ScheduleAction(Enum):
    OFF = 0
    CHARGE = 1
    DISCHARGE = 2
    STANDBY = 3


class ScheduleSlotField(DeviceField):
    """One time-control slot: action, start (hour, minute), end (hour, minute).

    Three registers: the action, then start and end with the hour in the high
    byte and the minute in the low byte. Reported as text, e.g.
    "Charge 11:01-13:59", or "Off".
    """

    def __init__(self, name: FieldName, address: int):
        super().__init__(name, address, 3)

    def parse(self, data: bytes) -> str | None:
        action, start, end = _words(data)
        if action not in [a.value for a in ScheduleAction]:
            return None
        if action == ScheduleAction.OFF.value:
            return "Off"
        label = ScheduleAction(action).name.capitalize()
        return (
            f"{label} {start >> 8:02d}:{start & 0xFF:02d}"
            f"-{end >> 8:02d}:{end & 0xFF:02d}"
        )


ALARM_BLOCK_START = 122
"""Register 122 (power type) to 138 (last fault word): 17 registers."""


def active_alarms(words: List[int]) -> List[str]:
    """Decode the alarm block (122-138) into "CODE Description" strings."""
    table = TABLE_B if (words[0] & 0xFF) == 3 else TABLE_E
    found = []
    for offset, word in enumerate(words):
        register = ALARM_BLOCK_START + offset
        if not (126 <= register <= 129 or 133 <= register <= 138):
            continue
        for bit in range(16):
            if word & (1 << bit):
                code, text = table.get((register, bit), (f"R{register}.{bit}", "Unknown"))
                found.append(f"{code} {text}")
    return found


class AlarmListField(DeviceField):
    """Active inverter warnings and faults as text ("None" when clear)."""

    def __init__(self, name: FieldName, address: int = ALARM_BLOCK_START):
        super().__init__(name, address, 17)

    def parse(self, data: bytes) -> str:
        alarms = active_alarms(_words(data))
        if not alarms:
            return "None"
        text = "; ".join(alarms)
        # Home Assistant states are capped at 255 characters.
        return text if len(text) <= 255 else text[:252] + "..."


class AlarmCountField(DeviceField):
    """How many inverter warnings and faults are active."""

    def __init__(self, name: FieldName, address: int = ALARM_BLOCK_START):
        super().__init__(name, address, 17)

    def parse(self, data: bytes) -> int:
        return len(active_alarms(_words(data)))


AC_PV_SLOT_TYPE = 101
"""PV slot type for an AC-coupled (metered) PV phase. DC strings are 100."""


class AcPvSlotField(DeviceField):
    """Power or voltage of one AC-coupled PV phase from the PV slot table.

    Each slot is eight registers: status, type, power, voltage /10,
    current /10, ... The value is only reported when the slot's type is AC
    PV, so a DC string in the same position is never mistaken for it.
    """

    def __init__(self, name: FieldName, address: int, value: str = "power"):
        # Reads status, type, power, voltage.
        super().__init__(name, address, 4)
        self.value = value

    def parse(self, data: bytes) -> float | int | None:
        _, slot_type, power, voltage = _words(data)
        if slot_type & 0xFF != AC_PV_SLOT_TYPE:
            return None
        if self.value == "voltage":
            return round(voltage / 10, 1)
        return _signed(power)


class AcPvTotalField(DeviceField):
    """Sum of the AC-coupled PV phases over consecutive eight-register slots."""

    def __init__(self, name: FieldName, address: int, slots: int):
        super().__init__(name, address, 8 * (slots - 1) + 3)
        self.slots = slots

    def parse(self, data: bytes) -> int | None:
        words = _words(data)
        total = None
        for i in range(self.slots):
            slot_type, power = words[8 * i + 1], words[8 * i + 2]
            if slot_type & 0xFF == AC_PV_SLOT_TYPE:
                total = (total or 0) + _signed(power)
        return total


class U32VersionField(DeviceField):
    """A 32-bit firmware version, low word first, shown as 9052.26."""

    def __init__(self, name: FieldName, address: int):
        super().__init__(name, address, 2)

    def parse(self, data: bytes) -> str | None:
        low, high = _words(data)
        version = low + (high << 16)
        if version == 0:
            return None
        return f"{version // 100}.{version % 100:02d}"
