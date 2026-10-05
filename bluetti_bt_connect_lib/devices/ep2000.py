from ..base_devices import BaseDeviceV2
from ..enums import WorkingMode, EmsControlMode, InverterStatus, BatteryStatus
from ..fields import (
    FieldName,
    UIntField,
    SIntField,
    SInt32Field,
    DecimalField,
    SwapStringField,
    SerialNumberField,
    VersionField,
    SwitchField,
    ValueSwitchField,
    SelectField,
    BoolField,
    WriteableUIntField,
    NodeCountField,
    OffsetIntField,
    MaskedEnumField,
    BitMaskField,
    LowByteOffsetField,
    FirmwareVersionField,
    U32VersionField,
    ScheduleSlotField,
    AlarmListField,
    AlarmCountField,
    AcPvSlotField,
    AcPvTotalField,
)


class EP2000(BaseDeviceV2):
    def __init__(self):
        super().__init__(
            [
                # These are plain 16-bit fields, not 32-bit - treating them
                # as 32-bit previously produced nonsensical values in the
                # tens of millions.
                SIntField(FieldName.CONSUMPTION_POWER_ALL, 142),
                UIntField(FieldName.PV_INPUT_POWER_ALL, 144),
                SIntField(FieldName.GRID_POWER_ALL, 146),
                # Energy totals at 152 (AC consumption), 158 (grid feed-in)
                # and 1202 (power generation) removed in 2.0.5: each read a
                # flat 0 for over a week of normal running, through days of
                # solar generation. Home Assistant's Integral helper on the
                # power sensors gives working kWh totals instead.
                SInt32Field(FieldName.TOTAL_PV_POWER, 1200),
                UIntField(FieldName.PV_S1_POWER, 1212),
                DecimalField(FieldName.PV_S1_VOLTAGE, 1213, 1),
                DecimalField(FieldName.PV_S1_CURRENT, 1214, 1),
                UIntField(FieldName.PV_S2_POWER, 1220),
                DecimalField(FieldName.PV_S2_VOLTAGE, 1221, 1),
                DecimalField(FieldName.PV_S2_CURRENT, 1222, 1),
                # PV Strings 3, 4, and 5 (registers 1228-1230, 1236-1238,
                # 1244-1246) removed entirely - this installation only has
                # 2 physically connected strings. String 3 and 5 read flat,
                # internally-consistent zero in every capture (genuinely
                # unpopulated, nothing wrong, just nothing there). String
                # 4 is worse than unpopulated: its "power" (1236) and the
                # already-removed "current" (1238) are proven to be the
                # high/low halves of one internal uptime counter - power
                # increments by exactly 1 every time current's raw value
                # wraps at 30000 (8h20m), matching to the millisecond
                # across 5 separate wrap events. Its "voltage" (1237) reads
                # a fixed 0.0V in every capture taken. None of this is PV
                # measurement.
                DecimalField(FieldName.GRID_FREQUENCY, 1300, 1),
                SIntField(FieldName.TOTAL_AC_POWER, 1301),
                SIntField(FieldName.GRID_P1_POWER, 1313),
                DecimalField(FieldName.GRID_P1_VOLTAGE, 1314, 1),
                DecimalField(FieldName.GRID_P1_CURRENT, 1315, 1),
                SIntField(FieldName.GRID_P2_POWER, 1319),
                DecimalField(FieldName.GRID_P2_VOLTAGE, 1320, 1),
                DecimalField(FieldName.GRID_P2_CURRENT, 1321, 1),
                SIntField(FieldName.GRID_P3_POWER, 1325),
                DecimalField(FieldName.GRID_P3_VOLTAGE, 1326, 1),
                DecimalField(FieldName.GRID_P3_CURRENT, 1327, 1),
                UIntField(FieldName.TOTAL_SELF_CONSUMPTION, 1290),
                DecimalField(FieldName.AC_OUTPUT_FREQUENCY, 1500, 1),
                SIntField(FieldName.AC_P1_POWER, 1510),
                DecimalField(FieldName.AC_P1_VOLTAGE, 1511, 1),
                DecimalField(FieldName.AC_P1_CURRENT, 1512, 1),
                SIntField(FieldName.AC_P2_POWER, 1517),
                DecimalField(FieldName.AC_P2_VOLTAGE, 1518, 1),
                DecimalField(FieldName.AC_P2_CURRENT, 1519, 1),
                SIntField(FieldName.AC_P3_POWER, 1524),
                DecimalField(FieldName.AC_P3_VOLTAGE, 1525, 1),
                DecimalField(FieldName.AC_P3_CURRENT, 1526, 1),
                UIntField(FieldName.LOAD_P1_POWER, 1430),
                UIntField(FieldName.LOAD_P2_POWER, 1436),
                UIntField(FieldName.LOAD_P3_POWER, 1442),
                # CAUTION: this remains writable. See README for what we
                # found about grid/mode writes on this device before
                # relying on any control below.
                SwitchField(FieldName.CTRL_AC, 2011),
                # Working Mode. 2005, not 2013 - 2013 is SetCtrlPowerOn,
                # the device power control, and a mode number written there
                # would have been a power command. Confirmed two ways that
                # agree exactly: this register reads 1, and Bluetti's cloud
                # reports SetCtrlWorkMode = workmode_3 for this device,
                # which their own mapping ties to register value 1. The
                # enum below was always right; only the address was wrong.
                SelectField(FieldName.WORKING_MODE, 2005, WorkingMode),
                # AI/EMS control mode (register 2241). 8 = Bluetti AI/EMS
                # actively managing the system, which OVERWRITES manual
                # writes (grid limits, working mode) - the accept-then-
                # revert we chased for weeks. 0 = manual control, and
                # manual writes then persist. Confirmed on hardware:
                # plain write reverts with 2241=8, persists with 2241=0.
                # Turn this OFF to make manual settings stick.
                ValueSwitchField(FieldName.EMS_CONTROL, 2241, on_value=8, off_value=0),
                # The full EMS control mode behind that switch: 0/4 local, 8 AI,
                # and 3/5/7 when the cloud (VPP, dynamic pricing) is in
                # charge. Low nibble, as BLUETTI's app reads it.
                MaskedEnumField(FieldName.EMS_CONTROL_MODE, 2241, EmsControlMode, 0x0F),
                UIntField(FieldName.BATTERY_SOC_RANGE_START, 2022),
                UIntField(FieldName.BATTERY_SOC_RANGE_END, 2023),
                # CAUTION: the following two switches and four sliders
                # remain writable, but see the README before relying on
                # any of them - the grid-limit fields in particular were
                # found to accept writes without the change persisting on
                # the device. Full explanation in the README.
                SwitchField(FieldName.CHARGE_FROM_GRID_ENABLED, 2207),
                SwitchField(FieldName.GRID_EXPORT_ENABLED, 2208),
                WriteableUIntField(FieldName.MAX_GRID_EXPORT_POWER, 2215, min=0, max=6666),
                # Restored: live-tested and confirmed working in an earlier
                # build (37A raw read correctly, no scaling needed) before
                # being lost from the codebase during restructuring. Bound
                # is the last value you confirmed - 35A for wiring
                # headroom, since the 6666W power limit above is the true
                # constraint anyway.
                WriteableUIntField(FieldName.MAX_GRID_EXPORT_CURRENT, 2216, min=0, max=35),
                # Cross-referenced from two independent sources (a related
                # device's register map and the original bluetti_mqtt/EP600
                # reference, which both agree on this register/purpose).
                # Fixed: min was 1, but if the device legitimately reports
                # 0 (e.g. no active import limit set), the old min=1 bound
                # made in_range() silently discard every reading with no
                # error - which is exactly what was happening. Changed to
                # min=0 so real 0 readings actually surface instead of
                # vanishing. Max raised 30 -> 40: the Bluetti app's own
                # Energy Buying/Selling screen shows 40A as a real,
                # currently-configured value on this exact unit, so our
                # old 30A ceiling was simply wrong, not just conservative.
                # Confirmed directly from a raw register dump: 2213 reads
                # 6600, exactly matching "Single-phase Grid Max. Input
                # Power: 6600 W" in the Bluetti app. Bound set to that
                # confirmed real value.
                WriteableUIntField(FieldName.MAX_GRID_IMPORT_POWER, 2213, min=0, max=9600),
                WriteableUIntField(FieldName.CTRL_GRID_MAX_CURRENT, 2214, min=0, max=50),
                # CTRL_GRID_INPUT_CURRENT (was register 2272) removed -
                # history showed it only ever reports unavailable or 0
                # across its entire recorded lifetime, and
                # ctrl_grid_max_current (2214, above) is already confirmed
                # correct and serves this exact purpose (40A, matching the
                # Bluetti app exactly). This was a redundant, non-working
                # duplicate.
                BoolField(FieldName.CTRL_GENERATOR, 2246),
                DecimalField(FieldName.GRID_VOLT_MIN_VAL, 2435, 1),
                DecimalField(FieldName.GRID_VOLT_MAX_VAL, 2436, 1),
                DecimalField(FieldName.GRID_FREQ_MIN_VALUE, 2437, 2),
                DecimalField(FieldName.GRID_FREQ_MAX_VALUE, 2438, 2),
                SwapStringField(FieldName.WIFI_NAME, 12002, 16),
                # Read directly here rather than via the pack_fields/
                # max_packs mechanism below, which is dormant (max_packs=0)
                # and untested for multi-pack selection.
                SwapStringField(FieldName.BMS_CONTROLLER_MODEL, 6101, 6),
                DecimalField(FieldName.PACK_VOLTAGE, 6111, 1),
                UIntField(FieldName.PACK_BATTERY_SOC, 6113, min=0, max=100),
                UIntField(FieldName.PACK_SOH, 6114, min=0, max=100),
                UIntField(FieldName.ACTIVE_CELL_COUNT, 6153),
                UIntField(FieldName.BATTERY_STACK_COUNT, 6154),
                # Exploratory, unverified: "Total Node Count", documented
                # alongside a separate write-only discovery-trigger register.
                # Pack average temperature: the register holds degrees C
                # plus 40, and BLUETTI's own app decodes it as raw - 40
                # (ProtocolParserV2.parsePackItemInfo, the same for 6007,
                # the cell NTCs and the inverter's temperatures). 2.0.4
                # read it as degrees F from a fit against air temperature;
                # the vendor decoding replaces that.
                OffsetIntField(FieldName.PACK_TEMPERATURE, 6115, offset=-40),
                # The node list at 21002: one 8-word entry per device
                # (EBOX, inverter, packs), with slave address, serial and
                # model code. 21001, read here before as a "total node
                # count", is always 0 and was not a count at all.
                NodeCountField(FieldName.CONNECTED_DEVICES, 21002, entries=4),
                # The home data block as the EBOX (slave 0) serves it. The
                # inverter (slave 1) leaves most of this block at 0; the
                # EBOX aggregates inverter, battery and meters and fills it
                # in. Layout from BLUETTI's app (parseHomeData): 32-bit
                # values, low word first, energies in 0.1 kWh. Checked
                # against the app's lifetime statistics on a real system.
                SInt32Field(FieldName.HOME_LOAD_POWER, 142).at_slave(0),
                SInt32Field(FieldName.HOME_CONSUMPTION_ENERGY, 152, 0.1, min=0).at_slave(0),
                SInt32Field(FieldName.SOLAR_ENERGY, 154, 0.1, min=0).at_slave(0),
                SInt32Field(FieldName.GRID_IMPORT_ENERGY, 156, 0.1, min=0).at_slave(0),
                SInt32Field(FieldName.GRID_EXPORT_ENERGY, 158, 0.1, min=0).at_slave(0),
                UIntField(FieldName.SELF_SUFFICIENCY, 164, max=100).at_slave(0),
                # More of the EBOX's view (slave 0), decoded as BLUETTI's app
                # does and checked on a real system (2026-10-05).
                MaskedEnumField(FieldName.BATTERY_STATUS, 103, BatteryStatus, 0xFF).at_slave(0),
                # Time to full and time to empty: the EBOX reports one value
                # in both registers, the time left in the current direction.
                UIntField(FieldName.TIME_REMAINING_MINUTES, 104).at_slave(0),
                # 122 power type picks the code table; 126-129 warnings and
                # 133-138 faults, one code per bit.
                AlarmListField(FieldName.ACTIVE_ALARMS, 122).at_slave(0),
                AlarmCountField(FieldName.ALARM_COUNT, 122).at_slave(0),
                MaskedEnumField(FieldName.INVERTER_STATUS, 161, InverterStatus, 0xFF).at_slave(0),
                # 174: IoT, BMS, other and meter error flags (bits 5, 6, 7, 10).
                BitMaskField(FieldName.SYSTEM_ERROR, 174, 0x04E0).at_slave(0),
                # AC-coupled PV phases (a metered inverter such as Enphase),
                # listed by the EBOX as PV slots of type 101 after the two
                # DC strings: slots 3-5 at 1226, 1234 and 1242. Each value
                # is only reported for a slot of that type; 0 W without an
                # AC PV meter.
                AcPvTotalField(FieldName.AC_PV_POWER, 1226, slots=3).at_slave(0),
                AcPvSlotField(FieldName.AC_PV_L1_POWER, 1226).at_slave(0),
                AcPvSlotField(FieldName.AC_PV_L2_POWER, 1234).at_slave(0),
                AcPvSlotField(FieldName.AC_PV_L3_POWER, 1242).at_slave(0),
                AcPvSlotField(FieldName.AC_PV_L1_VOLTAGE, 1226, "voltage").at_slave(0),
                AcPvSlotField(FieldName.AC_PV_L2_VOLTAGE, 1234, "voltage").at_slave(0),
                AcPvSlotField(FieldName.AC_PV_L3_VOLTAGE, 1242, "voltage").at_slave(0),
                # Time control (the schedule used by Custom mode): enable,
                # then six slots of action / start / end. Read-only here.
                BoolField(FieldName.TIME_CONTROL_ENABLED, 2029).at_slave(0),
                ScheduleSlotField(FieldName.SCHEDULE_SLOT_1, 2030).at_slave(0),
                ScheduleSlotField(FieldName.SCHEDULE_SLOT_2, 2033).at_slave(0),
                ScheduleSlotField(FieldName.SCHEDULE_SLOT_3, 2036).at_slave(0),
                ScheduleSlotField(FieldName.SCHEDULE_SLOT_4, 2039).at_slave(0),
                ScheduleSlotField(FieldName.SCHEDULE_SLOT_5, 2042).at_slave(0),
                ScheduleSlotField(FieldName.SCHEDULE_SLOT_6, 2045).at_slave(0),
                # Battery limits from the BMS (EBOX battery totals block).
                DecimalField(FieldName.MAX_CHARGE_CURRENT, 6011, 1).at_slave(0),
                DecimalField(FieldName.MAX_DISCHARGE_CURRENT, 6012, 1).at_slave(0),
                # EBOX: firmware, cloud (MQTT) connection, WiFi signal.
                U32VersionField(FieldName.FIRMWARE_IOT, 11014).at_slave(0),
                BitMaskField(FieldName.CLOUD_CONNECTED, 11018, 1 << 6).at_slave(0),
                LowByteOffsetField(FieldName.WIFI_SIGNAL, 11026, -256).at_slave(0),
                # Inverter firmware from its software list (slave 1).
                FirmwareVersionField(FieldName.FIRMWARE_ARM, 1112, mcu_type=1),
                FirmwareVersionField(FieldName.FIRMWARE_DSP, 1112, mcu_type=2),
            ],
            [
                SwapStringField(FieldName.PACK_TYPE, 6101, 6),
                SerialNumberField(FieldName.PACK_SN, 6107),
                VersionField(FieldName.PACK_VER_BCU, 6175),
                VersionField(FieldName.PACK_VER_BMU, 6178),
                VersionField(FieldName.PACK_VER_SAFETY_MOD, 6181),
                VersionField(FieldName.PACK_VER_HV_MOD, 6184),
            ],
            # max_packs=2,
            # Writes go to slave 0: this is a 2nd-gen IoT device whose
            # settings controller is on slave 0. A write to slave 1 is
            # echoed by the inverter and then overwritten by the slave-0
            # setpoint within a few seconds (confirmed on hardware).
            write_slave_addr=0,
        )
