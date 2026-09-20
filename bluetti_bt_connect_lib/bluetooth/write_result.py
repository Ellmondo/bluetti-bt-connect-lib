from enum import Enum
from typing import Any


class WriteOutcome(Enum):
    """What the device did with a write."""

    ACCEPTED = "accepted"
    """The device echoed the value back. Modbus function 6 replies with a copy
    of the request, so a matching echo is the device's acknowledgement."""

    REFUSED = "refused"
    """The device returned a Modbus exception. `exception_code` says why."""

    MISMATCHED = "mismatched"
    """An echo came back, but not of the value written. Unexpected - worth
    logging loudly rather than treating as success."""

    NO_RESPONSE = "no_response"
    """Nothing came back before the timeout. The write may or may not have
    landed; there is no way to tell from here."""

    FAILED = "failed"
    """The write could not be sent at all - not connected, field unknown, or
    the link dropped mid-command."""


# Modbus application protocol exception codes.
EXCEPTION_MEANINGS = {
    0x01: "Illegal function",
    0x02: "Illegal data address",
    0x03: "Illegal data value",
    0x04: "Server device failure",
    0x05: "Acknowledge (accepted, still processing)",
    0x06: "Server device busy",
    0x08: "Memory parity error",
    0x0A: "Gateway path unavailable",
    0x0B: "Gateway target failed to respond",
}


class WriteResult:
    """The outcome of a single register write.

    Exists because "no exception was raised" is not the same as "the device
    accepted it". Modbus function 6 answers every write - either echoing the
    value or returning an exception - and that answer is the only honest
    signal about whether a setting took.
    """

    def __init__(
        self,
        outcome: WriteOutcome,
        field: str,
        requested: Any = None,
        echoed: Any = None,
        exception_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.outcome = outcome
        self.field = field
        self.requested = requested
        self.echoed = echoed
        self.exception_code = exception_code
        self.detail = detail

    @property
    def accepted(self) -> bool:
        """True only when the device confirmed the write."""
        return self.outcome is WriteOutcome.ACCEPTED

    @property
    def exception_meaning(self) -> str | None:
        if self.exception_code is None:
            return None
        return EXCEPTION_MEANINGS.get(self.exception_code, "Unknown exception code")

    def __str__(self) -> str:
        if self.outcome is WriteOutcome.ACCEPTED:
            return f"{self.field}: accepted ({self.echoed})"

        if self.outcome is WriteOutcome.REFUSED:
            return (
                f"{self.field}: refused by device - exception "
                f"0x{self.exception_code:02x} ({self.exception_meaning})"
            )

        if self.outcome is WriteOutcome.MISMATCHED:
            return (
                f"{self.field}: echo did not match - wrote {self.requested}, "
                f"device echoed {self.echoed}"
            )

        if self.outcome is WriteOutcome.NO_RESPONSE:
            return f"{self.field}: no response from device"

        return f"{self.field}: failed{f' - {self.detail}' if self.detail else ''}"

    def __repr__(self) -> str:
        return f"WriteResult({self})"
