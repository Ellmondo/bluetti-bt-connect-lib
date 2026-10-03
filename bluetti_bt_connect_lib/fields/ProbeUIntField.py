from . import FieldName, UIntField


class ProbeUIntField(UIntField):
    """A raw, unscaled register whose existence on the device is unconfirmed.

    Used to look at an address before committing to what it means - the
    value is reported exactly as the device sends it, with no multiplier,
    offset or bounds.

    An unconfirmed address may not be served at all, and a device can answer
    an unserved address with silence rather than a Modbus exception. A silent
    register inside an ordinary read would time out and fail the whole poll,
    so probe fields are never merged into grouped reads: they are read on
    their own, after everything else, and the reader stops asking for any
    probe register the device refuses or ignores (see
    `DeviceReader._read_probe_register`).
    """

    optional = True

    def __init__(self, name: FieldName, address: int):
        super().__init__(name, address)
