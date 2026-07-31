from typing import Any

from . import DeviceField, FieldName


class WriteableStringField(DeviceField):
    """A fixed-width ASCII string field that can be written, spanning
    multiple registers (e.g. an 8-character password across 4 registers).

    Unverified assumption: uses plain (non-swapped) byte order, matching
    the existing read-only StringField convention, since this register was
    documented simply as "ASCII" rather than explicitly noting a swap.
    """

    def __init__(self, name: FieldName, address: int, size: int):
        # size is in registers (2 bytes each)
        super().__init__(name, address, size)

    def parse(self, data: bytes) -> str:
        return data.rstrip(b"\0").decode("ascii", errors="ignore")

    def is_writeable(self) -> bool:
        return True

    def allowed_write_type(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        max_len = self.size * 2
        return len(value.encode("ascii", errors="ignore")) <= max_len

    def encode_for_write(self, value: str) -> list[int]:
        """Pads/truncates the string to the field's byte width and packs
        it into a list of 16-bit register values, ready for a Write
        Multiple Registers command."""
        max_len = self.size * 2
        raw = value.encode("ascii", errors="ignore")[:max_len]
        raw = raw.ljust(max_len, b"\0")

        registers = []
        for i in range(0, max_len, 2):
            registers.append((raw[i] << 8) | raw[i + 1])
        return registers
