from typing import Any

from . import UIntField, FieldName


class WriteableUIntField(UIntField):
    """A writable unsigned integer field with a min/max range, intended
    for slider-style controls (e.g. a power limit in watts). Plain,
    single-register write - no special verification sequence, matching
    every other writeable field in this library."""

    def __init__(
        self,
        name: FieldName,
        address: int,
        min: int,
        max: int,
        multiplier: float = 1,
    ):
        super().__init__(name, address, multiplier=multiplier, min=min, max=max)

    def is_writeable(self) -> bool:
        return True

    def allowed_write_type(self, value: Any) -> bool:
        if not isinstance(value, (int, float)):
            return False
        return self.in_range(value)
