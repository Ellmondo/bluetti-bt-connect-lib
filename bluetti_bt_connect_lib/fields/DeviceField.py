from typing import Any

from ..fields import FieldName


class DeviceField:
    slave: int = 1
    """Modbus slave address this field is read from.

    Almost everything lives on slave 1 (the inverter). On EBOX systems some
    blocks are only populated on slave 0, the EBOX itself - see at_slave().
    """

    def __init__(self, name: FieldName, address: int, size: int):
        self.name = name.value
        self.address = address
        self.size = size

    def at_slave(self, slave: int) -> "DeviceField":
        """Read this field from another slave address. Returns the field.

        Fields on different slaves are never merged into one request, and a
        response is only matched against fields of the slave it came from,
        so the same address can be read from two slaves side by side.
        """
        self.slave = slave
        return self

    def parse(self, data: bytes) -> Any:
        raise NotImplementedError

    def is_writeable(self) -> bool:
        return False

    def allowed_write_type(self, value: Any) -> bool:
        return False

    def in_range(self, value: Any) -> bool:
        return True
