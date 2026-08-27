from typing import Any, List

from ..registers import ReadableRegisters, WriteableRegister, WriteableRegisters
from ..fields import (
    DeviceField,
    BoolField,
    BoolFieldNonZero,
    SwitchField,
    SelectField,
    WriteableStringField,
    WriteableUIntField,
)


DEFAULT_MAX_REGISTER_GAP = 8
"""How many unused registers may sit between two fields before they are read
separately rather than merged into one request.

Field addresses cluster tightly, so merging across small gaps collapses a
large number of round trips into a handful at the cost of transferring a few
extra words per poll. BLE round trips dominate poll time by a wide margin, so
this trade is heavily worth making."""

DEFAULT_MAX_REGISTER_QUANTITY = 32
"""Largest number of registers to request in a single read.

Kept well below the Modbus ceiling of 125 so a merged response stays small
enough to be reassembled comfortably from BLE notification fragments."""


class BluettiDevice:
    def __init__(
        self,
        fields: List[DeviceField],
        pack_fields: List[DeviceField] = [],
        max_packs: int = 0,
        max_register_gap: int | None = DEFAULT_MAX_REGISTER_GAP,
        max_register_quantity: int = DEFAULT_MAX_REGISTER_QUANTITY,
    ):
        self.fields = fields
        self.pack_fields = pack_fields
        self.max_packs = max_packs
        self.max_register_gap = max_register_gap
        self.max_register_quantity = max_register_quantity

        self.fields.sort(key=lambda f: f.address)
        self.pack_fields.sort(key=lambda f: f.address)

        # Write-only fields (e.g. password/unlock fields) are never included
        # in regular polling - there's no need to continuously re-read them.
        self.polling_registers: List[ReadableRegisters] = self._group_registers(
            [f for f in self.fields if not isinstance(f, WriteableStringField)]
        )
        self.pack_polling_registers: List[ReadableRegisters] = []

        # Check if we even have battery pack fields defined
        if len(self.pack_fields) == 0 or max_packs == 0:
            return

        self.pack_polling_registers = self._group_registers(self.pack_fields)

    def _group_registers(self, fields: List[DeviceField]) -> List[ReadableRegisters]:
        """Merge nearby field reads into a smaller number of requests.

        Reading each field with its own request costs one BLE round trip per
        field, which dominates the time a poll takes. Fields whose addresses
        sit within `max_register_gap` of each other are read together in one
        request instead, up to `max_register_quantity` registers.

        Merged requests keep a list of the individual reads they replaced, so
        a caller can retry them one at a time if the device rejects the wider
        range (see `DeviceReader._read_registers`). Setting `max_register_gap`
        to None disables merging entirely and restores one request per field.
        """

        if len(fields) == 0:
            return []

        singles = [
            ReadableRegisters(f.address, f.size)
            for f in sorted(fields, key=lambda f: f.address)
        ]

        if self.max_register_gap is None:
            return singles

        groups: List[ReadableRegisters] = []
        members = [singles[0]]
        start = singles[0].starting_address
        end = start + singles[0].quantity

        for register in singles[1:]:
            register_end = register.starting_address + register.quantity

            # Fields can overlap (two fields reading the same words), in
            # which case the gap is negative and the merge is free.
            gap = register.starting_address - end
            quantity = register_end - start

            if gap <= self.max_register_gap and quantity <= self.max_register_quantity:
                members.append(register)
                end = max(end, register_end)
                continue

            groups.append(self._build_group(start, end, members))
            members = [register]
            start = register.starting_address
            end = register_end

        groups.append(self._build_group(start, end, members))

        return groups

    @staticmethod
    def _build_group(
        start: int, end: int, members: List[ReadableRegisters]
    ) -> ReadableRegisters:
        """Build one request covering `members`, or return it unchanged."""

        if len(members) == 1:
            return members[0]

        group = ReadableRegisters(start, end - start)
        group.members = members

        return group

    def get_polling_registers(self) -> List[ReadableRegisters]:
        """Returns all registers required to poll device fields"""
        return self.polling_registers

    def get_pack_polling_registers(self) -> List[ReadableRegisters]:
        """Returns all registers required to poll device battery pack fields"""
        return self.pack_polling_registers

    def get_full_registers_range(self) -> List[ReadableRegisters]:
        """Returns all registers which are tested with the readall command"""
        raise NotImplementedError

    def get_device_type_registers(self) -> List[ReadableRegisters]:
        """Returns the register storing the type of the device"""
        raise NotImplementedError

    def get_device_sn_registers(self) -> List[ReadableRegisters]:
        """Returns the register storing the serial number of the device"""
        raise NotImplementedError

    def get_iot_version(self) -> int:
        """Get the IoT protocol version of the device"""
        raise NotImplementedError

    def get_pack_selector(self, pack: int) -> WriteableRegister:
        """Returns the register to request a specific battery pack"""
        raise NotImplementedError

    def parse(
        self, starting_address: int, data: bytes, pack_num: int | None = None
    ) -> dict:
        """Parse data"""

        # Offsets and size are counted in 2 byte chunks, so for the range we
        # need to divide the byte size by 2
        data_size = int(len(data) / 2)

        # Filter out fields not in range
        r = range(starting_address, starting_address + data_size)
        fields = [
            f
            for f in (self.fields + self.pack_fields)
            if f.address in r and f.address + f.size - 1 in r
        ]

        # Parse fields
        parsed = {}
        for f in fields:
            data_start = 2 * (f.address - starting_address)
            field_data = data[data_start : data_start + 2 * f.size]
            value = f.parse(field_data)
            if not f.in_range(value):
                continue
            if pack_num is not None and f in self.pack_fields:
                parsed[f"pack_{str(pack_num)}_{f.name}"] = value
            else:
                parsed[f.name] = value

        return parsed

    def build_write_command(
        self, name: str, value: Any
    ) -> WriteableRegister | WriteableRegisters | None:
        """Build a command to write values to the device"""

        matches = [f for f in self.fields if f.name == name]
        fields = [f for f in matches if f.is_writeable()]

        if len(fields) == 0:
            return None

        field = next(iter(fields))

        if isinstance(field, WriteableStringField):
            registers = field.encode_for_write(value)
            return WriteableRegisters(field.address, registers)

        # Convert value to an integer if its not already
        if isinstance(field, SelectField):
            if not isinstance(value, int):
                value = field.e[value].value
        elif isinstance(field, SwitchField):
            value = 1 if value else 0

        return WriteableRegister(field.address, value)

    def get_bool_fields(self):
        """Returns all bool fields for this device"""
        return [
            f
            for f in self.fields
            if (isinstance(f, BoolField) or isinstance(f, BoolFieldNonZero))
            and not isinstance(f, SwitchField)
        ]

    def get_switch_fields(self):
        """Returns all switch fields for this device"""
        return [f for f in self.fields if isinstance(f, SwitchField)]

    def get_select_fields(self):
        """Returns all select fields for this device"""
        return [f for f in self.fields if isinstance(f, SelectField)]

    def get_text_fields(self):
        """Returns all writeable string fields for this device"""
        return [f for f in self.fields if isinstance(f, WriteableStringField)]

    def get_number_fields(self):
        """Returns all writeable numeric (slider/box) fields for this device"""
        return [f for f in self.fields if isinstance(f, WriteableUIntField)]

    def get_sensor_fields(self):
        """Returns all sensor fields for this device"""
        return [
            f
            for f in self.fields
            if not isinstance(f, BoolField)
            and not isinstance(f, BoolFieldNonZero)
            and not isinstance(f, SwitchField)
            and not isinstance(f, SelectField)
            and not isinstance(f, WriteableStringField)
            and not isinstance(f, WriteableUIntField)
        ]
