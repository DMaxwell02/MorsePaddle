import argparse
import json
import sys
from collections.abc import Iterable, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import TextIO

from morse_paddle.debounce import PaddleDebouncer
from morse_paddle.decoder import MorseDecoder
from morse_paddle.hid_source import HIDError, list_devices, read_device
from morse_paddle.models import RawSample
from morse_paddle.simulator import samples_for_text


def _number(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Morse Paddle USB interface diagnostics")
    subparsers = parser.add_subparsers(dest="command", required=True)

    devices = subparsers.add_parser("devices", help="list connected HID collections")
    devices.add_argument("--vid", type=_number, default=0, help="filter by vendor ID")
    devices.add_argument("--pid", type=_number, default=0, help="filter by product ID")

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
    selector = listen.add_mutually_exclusive_group()
    selector.add_argument(
        "--path",
        help="exact HID path printed by `devices` (quote this value in PowerShell)",
    )
    selector.add_argument(
        "--collection",
        type=int,
        help="collection index printed by `devices --vid ... --pid ...`",
    )
    listen.add_argument("--capture", type=Path, help="write raw samples to a JSONL file")
    _add_timing_arguments(listen)
    return parser


def _add_timing_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--debounce-ms", type=float, default=5.0)
    parser.add_argument("--unit-ms", type=float, default=80.0, help="Morse timing unit")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "devices":
            _print_devices(args.vid, args.pid)
            return 0

        if args.command == "simulate":
            samples = samples_for_text(args.text, args.unit_ms, args.bounce)
            _analyze(samples, args.debounce_ms, args.unit_ms)
            return 0

        with read_device(
            args.vid,
            args.pid,
            args.byte_index,
            args.dit_mask,
            args.dah_mask,
            args.invert,
            path=args.path,
            collection_index=args.collection,
        ) as samples:
            selected = samples.collection
            print(
                f"Listening on collection [{selected.index}] "
                f"usage_page=0x{selected.usage_page:04X} usage=0x{selected.usage:04X} "
                f"interface={selected.interface_number} path={selected.path_text}"
            )
            _analyze(samples, args.debounce_ms, args.unit_ms, args.capture)
    except KeyboardInterrupt:
        print("\nCapture stopped.")
    except (HIDError, CaptureError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


def _print_devices(vendor_id: int = 0, product_id: int = 0) -> None:
    devices = list_devices(vendor_id, product_id)
    if not devices:
        print("No HID devices found.")
        return
    for device in devices:
        print(
            f"[{device.index}] VID=0x{device.vendor_id:04X} PID=0x{device.product_id:04X} "
            f"usage_page=0x{device.usage_page:04X} usage=0x{device.usage:04X} "
            f"interface={device.interface_number}"
        )
        print(f"    {device.manufacturer} - {device.product}")
        print(f"    path={device.path_text}")


def _analyze(
    samples: Iterable[RawSample],
    debounce_ms: float,
    unit_ms: float,
    capture_path: Path | None = None,
) -> None:
    debouncer = PaddleDebouncer(debounce_ms)
    decoder = MorseDecoder(unit_ms)
    first_timestamp: int | None = None

    capture_context = _capture_file(capture_path) if capture_path else nullcontext(None)
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
    try:
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
    except OSError as exc:
        raise CaptureError(f"Could not write capture data: {exc}") from exc


class CaptureError(RuntimeError):
    """A capture file could not be created."""


@contextmanager
def _capture_file(capture_path: Path) -> Iterator[TextIO]:
    try:
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture = capture_path.open("w", encoding="utf-8")
    except OSError as exc:
        raise CaptureError(f"Could not create capture file {capture_path}: {exc}") from exc
    try:
        yield capture
    finally:
        try:
            capture.close()
        except OSError as exc:
            raise CaptureError(f"Could not close capture file {capture_path}: {exc}") from exc
