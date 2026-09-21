"""Authenticating a BLE session so protected settings actually take.

Background
----------
The EBOX (and other Bluetti units) will happily *echo* a write to a protected
register - grid export/import limits, working mode, expert parameters - and
then quietly revert it. Reading the echo back is not enough: the device
acknowledges the frame but does not apply it.

The official Bluetti app has an extra step the fork never sent. On entering the
advanced/settings menus over Bluetooth it writes the unit's Bluetooth settings
password to **register 7** using Modbus function 16 (write-multiple, 3
registers). Once that write is accepted, the session is authenticated and
protected writes stick until the link drops. This module reproduces exactly
that write.

Encoding
--------
The password is up to 6 ASCII characters packed into 3 x 16-bit registers.
Within each register the two characters are **byte-swapped**: the character at
the higher string index goes in the high byte, the lower index in the low byte
(this matches the app's `ProtocolParse.bluetoothPswSetupData`). Missing
characters are zero. An empty password therefore encodes as three zero
registers, which is the correct unlock frame for a unit with no password set.

    ""     -> [0x0000, 0x0000, 0x0000]
    "1234" -> [0x3231, 0x3433, 0x0000]

The device reports its own current password in its base-config block when a
password is enabled, so a user who has forgotten it can read it there or from
the app; this module only needs the value to send.
"""

from ..registers import WriteableRegisters

BT_PASSWORD_REGISTER = 7
"""Register the Bluetooth settings password is written to, to unlock a session."""

BT_PASSWORD_REGISTER_COUNT = 3
"""Registers the password spans - 3 x 16-bit words = up to 6 ASCII chars."""

BT_PASSWORD_MAX_CHARS = BT_PASSWORD_REGISTER_COUNT * 2


def encode_bt_password(password: str | None) -> list[int]:
    """Encode a Bluetooth settings password into 3 register values.

    Byte-swapped within each register, zero-padded, matching the Bluetti app.
    ``None`` and ``""`` both encode as three zero registers (the unlock frame
    for a unit with no password set).
    """
    raw = (password or "").encode("ascii", errors="ignore")[:BT_PASSWORD_MAX_CHARS]
    raw = raw.ljust(BT_PASSWORD_MAX_CHARS, b"\x00")

    registers = []
    for i in range(0, BT_PASSWORD_MAX_CHARS, 2):
        low = raw[i]        # character at the lower string index
        high = raw[i + 1]   # character at the higher string index
        registers.append((high << 8) | low)
    return registers


def build_unlock_command(password: str | None) -> WriteableRegisters:
    """Build the func-16 write to register 7 that authenticates the session."""
    return WriteableRegisters(BT_PASSWORD_REGISTER, encode_bt_password(password))
