import unittest

from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.fields import FieldName, WriteableUIntField
from bluetti_bt_connect_lib.utils.device_builder import build_device


class TestWriteSlave(unittest.TestCase):
    def test_default_write_slave_is_one(self):
        d = BluettiDevice(fields=[WriteableUIntField(FieldName.MAX_GRID_EXPORT_POWER, 2215, min=0, max=6666)])
        cmd = d.build_write_command(FieldName.MAX_GRID_EXPORT_POWER.value, 1433)
        self.assertEqual(bytes(cmd)[0], 1)

    def test_write_slave_addr_is_used_in_the_frame(self):
        d = BluettiDevice(
            fields=[WriteableUIntField(FieldName.MAX_GRID_EXPORT_POWER, 2215, min=0, max=6666)],
            write_slave_addr=0,
        )
        cmd = d.build_write_command(FieldName.MAX_GRID_EXPORT_POWER.value, 1433)
        frame = bytes(cmd)
        self.assertEqual(frame[0], 0)   # slave 0
        self.assertEqual(frame[1], 6)   # function 6

    def test_ep2000_writes_target_slave_zero(self):
        d = build_device("EP2000123")
        self.assertEqual(d.write_slave_addr, 0)
        cmd = d.build_write_command(FieldName.MAX_GRID_EXPORT_POWER.value, 1433)
        self.assertEqual(bytes(cmd)[0], 0)


if __name__ == "__main__":
    unittest.main()
