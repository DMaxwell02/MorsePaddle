import argparse
import json
from collections.abc import Iterable
from contextlib import nullcontext
from pathlib import Path
from typing import TextIO

from morse_paddle.debounce import PaddleDebouncer
from morse_paddle.decoder import MorseDecoder
from morse_paddle.hid_source import list_devices, read_device
from morse_paddle.models import RawSample
from morse_paddle.simulator import samples_for_text


def _number(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Morse Paddle USB interface diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("devices", help="list connected HID devices")

    simulate = subparsers.add_parser("simulate", help="analyze generated paddle input")
    simulate.add_argument("--text", default="SOS TEST", help="text to generate")
    simulate.add_argument("--bounce", action="store_true", help="inject contact bounce")
    _add_timing_arguments(simulate)

    listen = subparsers.add_parser("listen", help="capture a USB HID paddle")
    listen.add_argument("--vid", type=_number, required=True, help="vendor ID, e.g. 0x1234")
    listen.add_argument("--pid", type=_number, required=True, help="product ID, e.g. 0x5678")
    listen.add_argument("--byte-index", type=int, default=0)
    listen.add_argument("--dit-mask", type=_number, default=0x01)
    listen.add_argument("--dah-mask", type=_number, default=0x02)
    listen.add_argument("--invert", action="store_true", help="use active-low contact bits")
    listen.add_argument("--capture", type=Path, help="write raw samples to a JSONL file")
    _add_timing_arguments(listen)
    return parser


def _add_timing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--debounce-ms", type=float, default=5.0)
    parser.add_argument("--unit-ms", type=float, default=80.0, help="Morse timing unit")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "devices":
        _print_devices()
        return

    if args.command == "simulate":
        samples = samples_for_text(args.text, args.unit_ms, args.bounce)
        _analyze(samples, args.debounce_ms, args.unit_ms)
        return

    samples = read_device(
        args.vid,
        args.pid,
        args.byte_index,
        args.dit_mask,
        args.dah_mask,
        args.invert,
    )
    try:
        _analyze(samples, args.debounce_ms, args.unit_ms, args.capture)
    except KeyboardInterrupt:
        print("\nCapture stopped.")


def _print_devices() -> None:
    devices = list_devices()
    if not devices:
        print("No HID devices found.")
        return
    for device in devices:
        vid = int(device.get("vendor_id", 0))
        pid = int(device.get("product_id", 0))
        manufacturer = device.get("manufacturer_string") or "Unknown manufacturer"
        product = device.get("product_string") or "Unknown product"
        print(f"VID=0x{vid:04X} PID=0x{pid:04X}  {manufacturer} - {product}")


def _analyze(
    samples: Iterable[RawSample],
    debounce_ms: float,
    unit_ms: float,
    capture_path: Path | None = None,
) -> None:
    debouncer = PaddleDebouncer(debounce_ms)
    decoder = MorseDecoder(unit_ms)
    first_timestamp: int | None = None

    capture_context = (
        capture_path.open("w", encoding="utf-8") if capture_path else nullcontext(None)
    )
    with capture_context as capture:
        for sample in samples:
            if first_timestamp is None:
                first_timestamp = sample.timestamp_ns
            elapsed_ms = (sample.timestamp_ns - first_timestamp) / 1_000_000
            _write_capture(capture, sample, elapsed_ms)
            print(
                f"{elapsed_ms:9.3f} ms RAW "
                f"dit={int(sample.dit_pressed)} dah={int(sample.dah_pressed)} "
                f"report={sample.report.hex(' ')}"
            )
            for event in debouncer.process(sample):
                if event.bounced:
                    print(f"{elapsed_ms:9.3f} ms BOUNCE {event.contact.value}")
                    continue
                edge = "DOWN" if event.pressed else "UP"
                print(f"{elapsed_ms:9.3f} ms ACCEPT {event.contact.value.upper()} {edge}")
                if event.pressed:
                    symbol = "." if event.contact.value == "dit" else "-"
                    emitted = decoder.process(event)
                    print(f"{elapsed_ms:9.3f} ms SYMBOL {symbol}")
                    for character in emitted:
                        print(f"{elapsed_ms:9.3f} ms DECODE {character!r}")

    for character in decoder.flush():
        print(f"FINAL DECODE {character!r}")
    print(f"Decoded: {decoder.text or '(none)'}")
    print(f"Rejected bounce transitions: {debouncer.bounce_count}")


def _write_capture(capture: TextIO | None, sample: RawSample, elapsed_ms: float) -> None:
    if capture is None:
        return
    json.dump(
        {
            "elapsed_ms": round(elapsed_ms, 6),
            "timestamp_ns": sample.timestamp_ns,
            "dit_pressed": sample.dit_pressed,
            "dah_pressed": sample.dah_pressed,
            "report_hex": sample.report.hex(),
        },
        capture,
    )
    capture.write("\n")

