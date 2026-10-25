"""The EP2000 time-control schedule: up to six charge/discharge periods a day.

Layout as BLUETTI's app reads and writes it, at the EBOX (slave 0):

- 2029: time control on (1) / off (0)
- 2030 + 3n, n = 0..5: action (0 off, 1 charge, 2 discharge, 3 standby),
  start and end, each with the hour in the high byte and the minute in the
  low byte

The app writes all six periods (2030-2047, 18 registers) in one function-16
request, earliest first, unused slots left as off 00:00-00:00. It only offers
periods within one day that do not overlap. The schedule acts only in the
Custom working mode.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from datetime import time
from typing import Iterable, List

from .fields.StatusFields import ScheduleAction

TIME_CONTROL_ENABLE_ADDRESS = 2029
SCHEDULE_ADDRESS = 2030
SCHEDULE_SLOTS = 6
SCHEDULE_REGISTERS = 3 * SCHEDULE_SLOTS


class ScheduleError(ValueError):
    """A schedule the device should not be given, with the reason."""


@dataclass(frozen=True)
class SchedulePeriod:
    """One period: what the battery does between `start` and `end`."""

    action: ScheduleAction
    start: time
    end: time

    @property
    def start_minutes(self) -> int:
        return self.start.hour * 60 + self.start.minute

    @property
    def end_minutes(self) -> int:
        return self.end.hour * 60 + self.end.minute

    def __str__(self) -> str:
        return (
            f"{self.action.name.capitalize()} "
            f"{self.start.hour:02d}:{self.start.minute:02d}"
            f"-{self.end.hour:02d}:{self.end.minute:02d}"
        )


def validate_schedule(periods: Iterable[SchedulePeriod]) -> List[SchedulePeriod]:
    """Check a schedule and return its periods earliest first.

    Raises ScheduleError when there are more than six periods, a period is
    "off", ends at or before its start, or two periods overlap. Periods may
    touch (one ends at 14:00, the next starts at 14:00). Seconds are ignored.
    """
    ordered = sorted(periods, key=lambda p: p.start_minutes)

    if len(ordered) > SCHEDULE_SLOTS:
        raise ScheduleError(
            f"At most {SCHEDULE_SLOTS} periods can be set, got {len(ordered)}"
        )

    for period in ordered:
        if not isinstance(period.action, ScheduleAction):
            raise ScheduleError(f"Unknown action: {period.action!r}")
        if period.action == ScheduleAction.OFF:
            raise ScheduleError(
                "Leave a period out instead of setting it to off"
            )
        if period.end_minutes <= period.start_minutes:
            raise ScheduleError(
                f"{period}: the end must be after the start, on the same day"
            )

    for earlier, later in zip(ordered, ordered[1:]):
        if later.start_minutes < earlier.end_minutes:
            raise ScheduleError(f"{earlier} overlaps {later}")

    return ordered


def encode_schedule(periods: Iterable[SchedulePeriod]) -> List[int]:
    """The 18 register values for 2030-2047, validated and earliest first."""
    words: List[int] = []
    for period in validate_schedule(periods):
        words += [
            period.action.value,
            period.start.hour << 8 | period.start.minute,
            period.end.hour << 8 | period.end.minute,
        ]
    words += [0] * (SCHEDULE_REGISTERS - len(words))
    return words


def decode_schedule(data: bytes) -> List[SchedulePeriod]:
    """The active periods in a 2030-2047 read, skipping off and unknown slots."""
    words = struct.unpack(f"!{len(data) // 2}H", data)
    periods = []
    for n in range(len(words) // 3):
        action, start, end = words[3 * n : 3 * n + 3]
        if action not in (a.value for a in ScheduleAction):
            continue
        if action == ScheduleAction.OFF.value:
            continue
        try:
            periods.append(
                SchedulePeriod(
                    ScheduleAction(action),
                    time(start >> 8, start & 0xFF),
                    time(end >> 8, end & 0xFF),
                )
            )
        except ValueError:
            continue
    return periods
