"""Battery maintenance status (home 106, slave 0) and cell voltages (6116/6117)."""

import asyncio
import struct
import unittest
from decimal import Decimal

from bluetti_bt_connect_lib import DeviceReader, FieldName
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.enums import (
    BatteryMaintenanceStatus,
    BatteryMaintenanceStopReason,
)
from bluetti_bt_connect_lib.fields import (
    CellVoltageSpreadField,
    MaintenanceProgressField,
    MaintenanceStopReasonField,
    MaskedEnumField,
    get_unit,
)

from slave_fields_test import TwoSlaveMock


def _w(*words):
    return b"".join(struct.pack("!H", w) for w in words)


STATUS = MaskedEnumField(
    FieldName.BATTERY_MAINTENANCE_STATUS, 106, BatteryMaintenanceStatus, 0x000F
)
PROGRESS = MaintenanceProgressField(FieldName.BATTERY_MAINTENANCE_PROGRESS, 106)
REASON = MaintenanceStopReasonField(FieldName.BATTERY_MAINTENANCE_STOP_REASON, 106)


class TestMaintenanceRegister(unittest.TestCase):
    def test_real_run_in_progress(self):
        # Read on a real EBOX during a maintenance run, 2026-10-25.
        data = _w(0x0022)
        self.assertEqual(STATUS.parse(data), BatteryMaintenanceStatus.IN_PROGRESS)
        self.assertEqual(PROGRESS.parse(data), 20)
        self.assertEqual(REASON.parse(data), BatteryMaintenanceStopReason.NONE)

    def test_idle(self):
        data = _w(0)
        self.assertEqual(STATUS.parse(data), BatteryMaintenanceStatus.NOT_NEEDED)
        self.assertEqual(PROGRESS.parse(data), 0)

    def test_finished_and_due(self):
        self.assertEqual(STATUS.parse(_w(0x00A3)), BatteryMaintenanceStatus.FINISHED)
        self.assertEqual(PROGRESS.parse(_w(0x00A3)), 100)
        self.assertEqual(STATUS.parse(_w(1)), BatteryMaintenanceStatus.DUE)
        self.assertEqual(
            STATUS.parse(_w(5)), BatteryMaintenanceStatus.DUE_CONDITIONS_NOT_MET
        )

    def test_stop_reasons(self):
        self.assertEqual(STATUS.parse(_w(0x0514)), BatteryMaintenanceStatus.STOPPED)
        self.assertEqual(REASON.parse(_w(0x0514)), BatteryMaintenanceStopReason.CHARGE_FAILED)
        self.assertEqual(REASON.parse(_w(0x0104)), BatteryMaintenanceStopReason.GRID_OFFLINE)
        for nibble in (7, 9, 15):
            self.assertEqual(
                REASON.parse(_w(nibble << 8 | 4)),
                BatteryMaintenanceStopReason.NOT_TRIGGERED,
            )

    def test_unknown_values(self):
        self.assertIsNone(STATUS.parse(_w(9)))
        self.assertIsNone(PROGRESS.parse(_w(0x00B2)))  # 110 %


class TestCellSpread(unittest.TestCase):
    def test_spread(self):
        field = CellVoltageSpreadField(FieldName.CELL_VOLTAGE_SPREAD, 6116)
        self.assertEqual(field.parse(_w(3224, 3232)), 8)
        self.assertIsNone(field.parse(_w(0, 0)))
        self.assertIsNone(field.parse(_w(3300, 3200)))

    def test_units(self):
        self.assertEqual(get_unit(FieldName.CELL_VOLTAGE_MIN), "V")
        self.assertEqual(get_unit(FieldName.CELL_VOLTAGE_SPREAD), "mV")
        self.assertEqual(get_unit(FieldName.BATTERY_MAINTENANCE_PROGRESS), "%")


class TestEP2000Poll(unittest.IsolatedAsyncioTestCase):
    async def test_values_and_no_extra_requests(self):
        device = DEVICES["EP2000"]()
        groups = [(r.slave, r.starting_address, r.quantity) for r in device.get_polling_registers()]
        # Both fit in reads that were already made.
        self.assertIn((1, 6101, 17), groups)
        self.assertTrue(any(s == 0 and a <= 106 < a + q for s, a, q in groups))

        mock = TwoSlaveMock()
        mock.set(1, 6116, _w(3224, 3232))
        mock.set(0, 106, _w(0x0022))
        reader = DeviceReader(
            "00:11:00:11:00:11", device, asyncio.Future, ble_client=mock
        )
        data = await reader.read()

        self.assertEqual(data["cell_voltage_min"], Decimal("3.224"))
        self.assertEqual(data["cell_voltage_max"], Decimal("3.232"))
        self.assertEqual(data["cell_voltage_spread"], 8)
        self.assertEqual(
            data["battery_maintenance_status"], BatteryMaintenanceStatus.IN_PROGRESS
        )
        self.assertEqual(data["battery_maintenance_progress"], 20)
        self.assertEqual(
            data["battery_maintenance_stop_reason"], BatteryMaintenanceStopReason.NONE
        )

    async def test_no_cells_reported(self):
        mock = TwoSlaveMock()
        reader = DeviceReader(
            "00:11:00:11:00:11", DEVICES["EP2000"](), asyncio.Future, ble_client=mock
        )
        data = await reader.read()
        # 0 mV is no reading: dropped, or unknown for the spread.
        self.assertNotIn("cell_voltage_min", data)
        self.assertIsNone(data.get("cell_voltage_spread"))


if __name__ == "__main__":
    unittest.main()
