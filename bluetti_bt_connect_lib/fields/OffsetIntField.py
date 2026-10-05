import struct

from . import DeviceField, FieldName


class OffsetIntField(DeviceField):
    """A 16-bit register whose value is the raw reading plus a fixed offset.

    BLUETTI encodes temperatures this way: the register holds the reading
    in °C plus 40, so -40 °C is sent as 0 and the value is always positive.
    The vendor's own app decodes it as raw - 40, for the pack, cell NTC and
    inverter temperatures alike.
    """

    def __init__(
        self,
        name: FieldName,
        address: int,
        offset: int,
        min: int | None = None,
        max: int | None = None,
    ):
        super().__init__(name, address, 1)
        self.offset = offset
        self.min = min
        self.max = max

    def parse(self, data: bytes) -> int:
        return struct.unpack("!H", data)[0] + self.offset

    def in_range(self, value: int) -> bool:
        if self.min is not None and value < self.min:
            return False
        if self.max is not None and value > self.max:
            return False
        return True
