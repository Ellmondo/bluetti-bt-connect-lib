from typing import Any

from . import FieldName, WriteableUIntField

SOC_LIMIT_MIN = 5
"""Lowest SOC limit BLUETTI's app lets you set (its slider starts at 5%)."""

SOC_LIMIT_MAX = 100

SOC_LIMIT_MIN_GAP = 5
"""Smallest gap kept between the low and high limit, in percent."""


class SocLimitField(WriteableUIntField):
    """A battery state-of-charge limit in percent (discharge floor or charge
    ceiling), writable in 1% steps.

    Every reading from 0 to 100 is reported, so a value set outside the
    write range by another tool still shows up instead of vanishing. Writes
    are limited to `min`..`max` (5-100 by default, matching BLUETTI's app).
    """

    def __init__(
        self,
        name: FieldName,
        address: int,
        min: int = SOC_LIMIT_MIN,
        max: int = SOC_LIMIT_MAX,
    ):
        super().__init__(name, address, min=min, max=max)

    def in_range(self, value: int) -> bool:
        return 0 <= value <= 100

    def allowed_write_type(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        if value != int(value):
            return False
        return self.min <= value <= self.max


def check_soc_limits(low: int, high: int, gap: int = SOC_LIMIT_MIN_GAP) -> str | None:
    """Why a low/high SOC limit pair is not allowed, or None if it is fine."""
    if low < SOC_LIMIT_MIN or high > SOC_LIMIT_MAX:
        return f"SOC limits must be between {SOC_LIMIT_MIN}% and {SOC_LIMIT_MAX}%"
    if high - low < gap:
        return (
            f"SOC high ({high}%) must be at least {gap}% above SOC low ({low}%)"
        )
    return None
