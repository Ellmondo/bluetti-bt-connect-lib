"""Custom exceptions for Modbus protocol and response validation errors.

These are distinct from connection-level errors (BleakError, TimeoutError):
a ModbusError or ParseError means the connection itself is fine and a
response was received, but it was either an explicit protocol-level
error from the device, or the data was corrupted/incomplete. These are
recoverable at the single-register level - the read loop should log and
move on to the next register, not abort the whole connection.
"""


class ParseError(Exception):
    """Raised when a response fails CRC validation (corrupted/incomplete data)."""

    pass


class ModbusError(Exception):
    """Raised when the device returns an explicit Modbus exception response."""

    pass
