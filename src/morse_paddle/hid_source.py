import time
from collections.abc import Iterator

import hid

from morse_paddle.models import RawSample


def list_devices() -> list[dict[str, object]]:
    return hid.enumerate()


def read_device(
    vendor_id: int,
    product_id: int,
    byte_index: int,
    dit_mask: int,
    dah_mask: int,
    invert: bool = False,
    timeout_ms: int = 50,
) -> Iterator[RawSample]:
    device = hid.device()
    device.open(vendor_id, product_id)
    device.set_nonblocking(False)
    try:
        while True:
            report_values = device.read(64, timeout_ms)
            if not report_values:
                continue
            report = bytes(report_values)
            if byte_index >= len(report):
                raise ValueError(
                    f"Report has {len(report)} bytes; byte index {byte_index} is out of range"
                )
            value = report[byte_index]
            dit_pressed = bool(value & dit_mask)
            dah_pressed = bool(value & dah_mask)
            if invert:
                dit_pressed = not dit_pressed
                dah_pressed = not dah_pressed
            yield RawSample(
                timestamp_ns=time.perf_counter_ns(),
                dit_pressed=dit_pressed,
                dah_pressed=dah_pressed,
                report=report,
            )
    finally:
        device.close()

