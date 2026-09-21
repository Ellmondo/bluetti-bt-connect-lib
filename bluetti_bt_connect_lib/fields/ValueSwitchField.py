import struct
from typing import Any

from . import SwitchField, FieldName


class ValueSwitchField(SwitchField):
    """A switch whose on/off states are arbitrary register values, not 1/0.

    Example: EMS/AI control mode lives in a register where 8 means "on"
    (Bluetti's AI/EMS is actively managing the system) and 0 means "off"
    (manual control - writes to grid limits and working mode then persist).
    A plain SwitchField would write 1, which the device would not recognise.
    """

    def __init__(self, name: FieldName, address: int, on_value: int, off_value: int = 0):
        super().__init__(name, address)
        self.on_value = on_value
        self.off_value = off_value

    def parse(self, data: bytes) -> bool | None:
        num = struct.unpack("!H", data)[0]
        if num == self.on_value:
            return True
        if num == self.off_value:
            return False
        return None

    def allowed_write_type(self, value: Any) -> bool:
        return isinstance(value, bool)
