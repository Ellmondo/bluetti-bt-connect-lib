import struct
import unittest

from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.fields import FieldName, ValueSwitchField


class TestValueSwitchField(unittest.TestCase):
    def field(self):
        return ValueSwitchField(FieldName.EMS_CONTROL, 2241, on_value=8, off_value=0)

    def test_parse_maps_on_off_values_to_bool(self):
        f = self.field()
        self.assertIs(f.parse(struct.pack("!H", 8)), True)
        self.assertIs(f.parse(struct.pack("!H", 0)), False)
        self.assertIsNone(f.parse(struct.pack("!H", 4)))

    def test_write_uses_on_off_values_not_one_zero(self):
        device = BluettiDevice(fields=[self.field()])
        on = device.build_write_command(FieldName.EMS_CONTROL.value, True)
        off = device.build_write_command(FieldName.EMS_CONTROL.value, False)
        self.assertEqual(on.address, 2241)
        self.assertEqual(on.value, 8)
        self.assertEqual(off.value, 0)

    def test_is_a_switch_field(self):
        device = BluettiDevice(fields=[self.field()])
        names = [getattr(f.name, "value", f.name) for f in device.get_switch_fields()]
        self.assertIn("ems_control", names)


if __name__ == "__main__":
    unittest.main()
