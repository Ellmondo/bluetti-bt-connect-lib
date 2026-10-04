"""Result of a one-off raw register read."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


MAX_RAW_READ_COUNT = 32
"""Largest number of registers one raw read may request.

Matches the largest request normal polling sends, so a raw read never asks
the device for a bigger response than it already handles every poll."""


class RawReadOutcome(Enum):
    OK = "ok"
    """The device answered with the requested registers."""

    REFUSED = "refused"
    """The device answered with a Modbus exception - see exception_code."""

    NO_REPLY = "no_reply"
    """The device stayed silent. Some addresses are answered this way."""

    NOT_CONNECTED = "not_connected"
    """No connection to the device could be made."""

    ERROR = "error"
    """Anything else: the link dropped, a corrupted reply, and so on."""


@dataclass
class RawReadResult:
    address: int
    count: int
    outcome: RawReadOutcome
    words: List[int] = field(default_factory=list)
    """Unsigned 16-bit register values, in address order. Empty unless OK."""

    exception_code: int | None = None
    """Modbus exception code when the device refused the read."""

    detail: str | None = None
    """Human-readable reason for an ERROR outcome."""

    slave: int = 1
    """Slave address the read was sent to."""

    @property
    def ok(self) -> bool:
        return self.outcome is RawReadOutcome.OK

    def as_dict(self) -> dict:
        """A plain dict, with each word also shown signed and in hex."""
        result: dict = {
            "slave": self.slave,
            "address": self.address,
            "count": self.count,
            "outcome": self.outcome.value,
        }

        if self.ok:
            result["registers"] = [
                {
                    "address": self.address + i,
                    "value": word,
                    "signed": word - 0x10000 if word & 0x8000 else word,
                    "hex": f"0x{word:04x}",
                }
                for i, word in enumerate(self.words)
            ]

        if self.exception_code is not None:
            result["exception_code"] = f"0x{self.exception_code:02x}"

        if self.detail:
            result["detail"] = self.detail

        return result
