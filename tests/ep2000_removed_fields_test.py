"""EP2000 energy totals that never reported anything stay removed."""

import unittest

from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.fields import FieldName


class TestEP2000RemovedFields(unittest.TestCase):
    def setUp(self):
        self.device = DEVICES["EP2000"]()

    def test_dead_registers_are_not_read_from_the_inverter(self):
        # 152, 158 and 1202 read a flat 0 for over a week at slave 1. 152 and
        # 158 are live at slave 0 (the EBOX) and are read from there now.
        addresses = {f.address for f in self.device.fields if f.slave == 1}
        for address in (152, 158, 1202):
            self.assertNotIn(address, addresses)

    def test_dead_field_names_are_gone(self):
        names = {f.name for f in self.device.fields}
        self.assertNotIn(FieldName.POWER_GENERATION.value, names)
        self.assertFalse(hasattr(FieldName, "TOTAL_AC_CONSUMPTION"))
        self.assertFalse(hasattr(FieldName, "TOTAL_GRID_FEED"))

    def test_neighbouring_fields_survive(self):
        names = {f.name for f in self.device.fields}
        for name in (
            FieldName.CONSUMPTION_POWER_ALL,
            FieldName.PV_INPUT_POWER_ALL,
            FieldName.GRID_POWER_ALL,
            FieldName.TOTAL_PV_POWER,
            FieldName.PV_S1_POWER,
        ):
            self.assertIn(name.value, names)

    def test_power_generation_kept_for_other_devices(self):
        # The name is shared: other models read it from their own registers.
        for model in ("AC2A", "AC2P", "EP600", "AC300"):
            names = {f.name for f in DEVICES[model]().fields}
            self.assertIn(FieldName.POWER_GENERATION.value, names, model)


if __name__ == "__main__":
    unittest.main()
