"""Pack cell / temperature-sensor / module counts (lib 2.0.8)."""

import struct
import unittest

from bluetti_bt_connect_lib.devices import DEVICES


class TestPackCounts(unittest.TestCase):
    def test_counts_from_a_real_hv800_stack(self):
        # 6152-6154 as read on 2026-10-05: seven B700 behind an HV800.
        device = DEVICES["EP2000"]()
        data = device.parse(6152, struct.pack("!3H", 224, 112, 7))
        self.assertEqual(data["active_cell_count"], 224)
        self.assertEqual(data["temperature_sensor_count"], 112)
        self.assertEqual(data["battery_stack_count"], 7)

    def test_counts_are_read_in_one_request(self):
        device = DEVICES["EP2000"]()
        groups = [(r.slave, r.starting_address, r.quantity) for r in device.get_polling_registers()]
        self.assertIn((1, 6152, 3), groups)


if __name__ == "__main__":
    unittest.main()
