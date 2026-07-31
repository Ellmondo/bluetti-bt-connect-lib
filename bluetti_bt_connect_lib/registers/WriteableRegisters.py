import struct

from . import DeviceRegister, RegisterAction


class WriteableRegisters(DeviceRegister):
    """Writes multiple consecutive registers in a single command, using
    Modbus function code 16 (Write Multiple Registers). Needed for values
    spanning more than one 16-bit register, such as fixed-width ASCII
    strings (e.g. an 8-character password across 4 registers).

    PDU body after slave id + function code:
      starting address (2 bytes)
      quantity of registers (2 bytes)
      byte count (1 byte)
      register values (byte count bytes)
    """

    def __init__(self, address: int, values: list[int]):
        quantity = len(values)
        byte_count = quantity * 2

        body = struct.pack("!HHB", address, quantity, byte_count)
        for v in values:
            body += struct.pack("!H", v)

        super().__init__(RegisterAction.WRITE_MULTIPLE, body)
        self.address = address
        self.values = values

    def response_size(self):
        return 8

    def parse_response(self, response: bytes):
        return bytes(response[2:6])

    def __repr__(self):
        return f"WriteableRegisters(address={self.address}, values={self.values})"
