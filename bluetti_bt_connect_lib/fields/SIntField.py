import struct

from . import DeviceField, FieldName


class SIntField(DeviceField):
    """A signed 16-bit integer register field.

    Some registers (notably bidirectional power readings such as grid,
    AC output, and smart-meter power on hybrid inverters) are transmitted
    as signed 16-bit values so that direction (import/export,
    charge/discharge) can be encoded via the sign, rather than a separate
    flag register. Parsing these with an unsigned format (as UIntField
    does) causes negative values to wrap around to large positive numbers
    (e.g. -6647 is read as 58889).

    This field parses the same 2-byte register as UIntField, but interprets
    it as a signed short, so negative readings come through correctly.
    """

    def __init__(
        self,
        name: FieldName,
        address: int,
        multiplier: float = 1,
        min: int | None = None,
        max: int | None = None,
    ):
        super().__init__(name, address, 1)
        self.multiplier = multiplier
        self.min = min
        self.max = max

    def parse(self, data: bytes) -> int:
        val = struct.unpack("!h", data)[0]
        if self.multiplier != 1:
            val = round(val * self.multiplier, 2)
        return val

    def in_range(self, value: int) -> bool:
        if self.min is not None and self.min > value:
            return False
        if self.max is not None and self.max < value:
            return False
        return True
