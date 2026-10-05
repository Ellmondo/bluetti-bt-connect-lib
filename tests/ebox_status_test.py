"""EBOX status, alarms, schedule, AC-coupled PV and diagnostics (lib 2.0.7).

Register values are a real EP2000 + EBOX + HV800 read on 2026-10-05, evening,
battery discharging. Serial numbers and MAC addresses are zeroed.
"""

import asyncio
import struct
import unittest

from bluetti_bt_connect_lib import DeviceReader, FieldName
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.enums import (
    BatteryStatus,
    EmsControlMode,
    InverterStatus,
    WorkingMode,
)
from bluetti_bt_connect_lib.fields import (
    AcPvSlotField,
    AcPvTotalField,
    AlarmListField,
    MaskedEnumField,
    ScheduleSlotField,
    SelectField,
)

from slave_fields_test import TwoSlaveMock


def _w(words):
    return b"".join(struct.pack("!H", w & 0xFFFF) for w in words)


# Slave 0 (EBOX)
HOME_100 = [7445, 11, 97, 2, 1212, 1212, 0, 0, 0, 0, 20549, 12338, 12336, 0, 0, 0,
            0, 0, 0, 0, 1, 1, 3, 13568, 346, 0, 128, 0, 0, 0, 0, 0]
HOME_132 = [0] * 8
HOME_140 = [0, 0, 1162, 0, 591, 0, 0, 0, 1155, 0, 0, 0, 37396, 0, 23284, 0,
            51642, 0, 5111, 0, 0, 3]
HOME_162 = [0, 0, 64] + [0] * 19
PV_1200 = [0] * 9 + [50, 1, 100, 129, 3213, 4, 0, 0, 0, 0, 100, 0, 1334, 0, 0,
                     0, 0, 0, 101, 0, 2382, 0, 0,
                     0, 0, 0, 101, 0, 2445, 0, 0, 0, 0, 0, 101, 0, 2381, 0, 0]
TIME_2029 = [1, 1, 0x0B01, 0x0D3B, 2, 0x1200, 0x1500] + [0] * 12
PACK_6000 = [2, 1, 1, 7444, 12, 97, 98, 71, 34, 2, 0, 183, 493, 3, 0, 0, 1,
             1211, 1211, 0, 0, 0, 0, 0]
IOT_11000 = [16965, 22607, 0, 0, 0, 0, 0, 0, 0, 0, 9272, 9693, 0, 0, 53258, 13,
             324, 0, 69, 0, 43200, 33586, 43200, 306, 65535, 255, 209, 0, 0, 0,
             0, 0]

# Slave 1 (inverter)
INV_1100 = [0, 20549, 12338, 12336, 0, 0, 0, 0, 0, 0, 0, 3, 2, 1, 44470, 7, 2,
            44269, 7] + [0] * 13


class TestRealEboxRead(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        mock = TwoSlaveMock()
        for register, words in (
            (100, HOME_100), (132, HOME_132), (140, HOME_140), (162, HOME_162),
            (1200, PV_1200), (2029, TIME_2029), (6000, PACK_6000),
            (11000, IOT_11000),
        ):
            mock.set(0, register, _w(words))
        mock.set(1, 1100, _w(INV_1100))
        mock.set(1, 2241, _w([0]))
        reader = DeviceReader(
            "00:11:00:11:00:11", DEVICES["EP2000"](), asyncio.Future, ble_client=mock
        )
        self.data = await reader.read()

    def test_status(self):
        d = self.data
        self.assertEqual(d["battery_status"], BatteryStatus.DISCHARGING)
        self.assertEqual(d["time_remaining_minutes"], 1212)
        self.assertEqual(d["inverter_status"], InverterStatus.GRID_CONNECTED)
        self.assertEqual(d["ems_control_mode"], EmsControlMode.LOCAL)
        self.assertEqual(d["self_sufficiency"], 64)

    def test_alarms(self):
        # 126 bit 7 on a high-power inverter (122 = 3): the short PV2 string.
        self.assertEqual(self.data["active_alarms"], "B104 PV2 Voltage Low")
        self.assertEqual(self.data["alarm_count"], 1)
        self.assertIs(self.data["system_error"], False)

    def test_ac_coupled_pv(self):
        d = self.data
        self.assertEqual(d["ac_pv_power"], 0)
        self.assertEqual(
            [d["ac_pv_l1_power"], d["ac_pv_l2_power"], d["ac_pv_l3_power"]], [0, 0, 0]
        )
        self.assertEqual(
            [d["ac_pv_l1_voltage"], d["ac_pv_l2_voltage"], d["ac_pv_l3_voltage"]],
            [238.2, 244.5, 238.1],
        )

    def test_schedule(self):
        d = self.data
        self.assertIs(d["time_control_enabled"], True)
        self.assertEqual(d["schedule_slot_1"], "Charge 11:01-13:59")
        self.assertEqual(d["schedule_slot_2"], "Discharge 18:00-21:00")
        for n in range(3, 7):
            self.assertEqual(d[f"schedule_slot_{n}"], "Off")

    def test_battery_limits(self):
        self.assertEqual(float(self.data["max_charge_current"]), 18.3)
        self.assertEqual(float(self.data["max_discharge_current"]), 49.3)

    def test_diagnostics(self):
        d = self.data
        self.assertEqual(d["firmware_iot"], "9052.26")
        self.assertEqual(d["firmware_arm"], "5032.22")
        self.assertEqual(d["firmware_dsp"], "5030.21")
        self.assertIs(d["cloud_connected"], True)
        self.assertEqual(d["wifi_signal"], -47)

    def test_existing_values_unchanged(self):
        self.assertEqual(self.data["home_load_power"], 1162)
        self.assertEqual(self.data["grid_import_energy"], 5164.2)


class TestFields(unittest.TestCase):
    def test_ac_pv_ignores_dc_slots(self):
        # A DC string (type 100) in an AC slot position is never reported.
        dc = _w([1, 100, 2427, 3585])
        self.assertIsNone(AcPvSlotField(FieldName.AC_PV_L1_POWER, 1226).parse(dc))
        three_dc = _w([1, 100, 500, 0, 0, 0, 0, 0] * 2 + [1, 100, 500])
        self.assertIsNone(AcPvTotalField(FieldName.AC_PV_POWER, 1226, 3).parse(three_dc))

    def test_ac_pv_producing_and_signed(self):
        slots = _w([1, 101, 1200, 2400, 50, 0, 0, 0,
                    1, 101, 1100, 2410, 46, 0, 0, 0,
                    1, 101, 0xFFF6])
        self.assertEqual(AcPvTotalField(FieldName.AC_PV_POWER, 1226, 3).parse(slots), 2290)
        self.assertEqual(
            AcPvSlotField(FieldName.AC_PV_L3_POWER, 1242).parse(_w([1, 101, 0xFFF6, 2400])),
            -10,
        )

    def test_low_power_table_and_unknown_bits(self):
        words = [0] * 17
        words[0] = 1  # not high power: table E
        words[4] = 1  # 126 bit 0
        self.assertEqual(
            AlarmListField(FieldName.ACTIVE_ALARMS).parse(_w(words)), "E113 Grid voltage high"
        )
        words[0] = 3
        words[5] = 1  # 127 has no table B entries
        text = AlarmListField(FieldName.ACTIVE_ALARMS).parse(_w(words))
        self.assertIn("B097 Grid Voltage High", text)
        self.assertIn("R127.0 Unknown", text)

    def test_ems_mode_uses_low_nibble(self):
        field = MaskedEnumField(FieldName.EMS_CONTROL_MODE, 2241, EmsControlMode, 0x0F)
        self.assertEqual(field.parse(_w([0x0013])), EmsControlMode.CLOUD)
        self.assertEqual(field.parse(_w([8])), EmsControlMode.AI)
        self.assertIsNone(field.parse(_w([9])))

    def test_working_mode_11(self):
        field = SelectField(FieldName.WORKING_MODE, 2005, WorkingMode)
        self.assertEqual(field.parse(_w([11])), WorkingMode.SELF_CONSUMPTION_EXPORT)

    def test_schedule_slot_rejects_unknown_action(self):
        self.assertIsNone(ScheduleSlotField(FieldName.SCHEDULE_SLOT_1, 2030).parse(_w([9, 0, 0])))
        self.assertEqual(
            ScheduleSlotField(FieldName.SCHEDULE_SLOT_1, 2030).parse(_w([3, 0x0000, 0x0630])),
            "Standby 00:00-06:48",
        )


if __name__ == "__main__":
    unittest.main()
