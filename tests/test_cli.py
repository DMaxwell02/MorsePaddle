from io import StringIO
from pathlib import Path
from typing import Self

import pytest

from morse_paddle import cli
from morse_paddle.hid_source import HIDCollection, HIDError
from morse_paddle.raw_keyboard import RawKeyboardDevice, RawKeyEvent


def paddle_collection() -> HIDCollection:
    return HIDCollection(
        index=1,
        path=rb"\\?\hid#vid_04d8&pid_01a6&mi_01&col02#paddle",
        vendor_id=0x04D8,
        product_id=0x01A6,
        usage_page=0xFF00,
        usage=0x01,
        interface_number=1,
        manufacturer="hamradio.solutions",
        product="PaddleAdapter",
    )


def test_devices_prints_collection_metadata(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "list_devices", lambda vid, pid: [paddle_collection()])

    assert cli.main(["devices", "--vid", "0x04D8", "--pid", "0x01A6"]) == 0

    output = capsys.readouterr().out
    assert "[1] VID=0x04D8 PID=0x01A6" in output
    assert "usage_page=0xFF00 usage=0x0001 interface=1" in output
    assert "hamradio.solutions - PaddleAdapter" in output
    assert r"path=\\?\hid#vid_04d8&pid_01a6" in output


def test_hid_error_is_concise_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise HIDError("read error; choose a non-keyboard collection")

    monkeypatch.setattr(cli, "read_device", fail)

    result = cli.main(["listen", "--vid", "0x04D8", "--pid", "0x01A6"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.err == "error: read error; choose a non-keyboard collection\n"
    assert "Traceback" not in captured.err


def test_capture_creates_missing_parent_directories(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture_path = tmp_path / "nested" / "captures" / "paddle.jsonl"

    cli._analyze([], debounce_ms=5, unit_ms=80, capture_path=capture_path)

    assert capture_path.is_file()
    assert capture_path.read_text(encoding="utf-8") == ""
    capsys.readouterr()


def test_capture_write_error_becomes_actionable_error() -> None:
    class BrokenCapture(StringIO):
        def write(self, text: str) -> int:
            raise OSError("disk full")

    with pytest.raises(cli.CaptureError, match="disk full"):
        cli._write_capture(
            BrokenCapture(),
            cli.RawSample(1, False, False, b"\x00"),
            0,
        )


def test_raw_devices_prints_filterable_physical_keyboard_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    device = RawKeyboardDevice(
        0,
        10,
        r"\\?\HID#VID_04D8&PID_01A6#paddle",
        keyboard_type=4,
        keyboard_subtype=0,
        key_count=101,
    )
    backend = object()
    monkeypatch.setattr(cli, "windows_backend", lambda: backend)
    monkeypatch.setattr(cli, "list_raw_keyboards", lambda api, vid, pid: [device])

    result = cli.main(["raw-devices", "--vid", "0x04D8", "--pid", "0x01A6"])

    output = capsys.readouterr().out
    assert result == 0
    assert "[0] VID=0x04D8 PID=0x01A6 type=4 subtype=0 keys=101" in output
    assert r"path=\\?\HID#VID_04D8&PID_01A6#paddle" in output


def test_raw_listen_parser_accepts_extended_scan_mappings() -> None:
    args = cli.build_parser().parse_args(
        [
            "raw-listen",
            "--vid",
            "0x04D8",
            "--pid",
            "0x01A6",
            "--dit-scan",
            "0xE01D",
            "--dah-vkey",
            "0x27",
        ]
    )

    assert args.dit_scan == 0xE01D
    assert args.dah_vkey == 0x27


def test_raw_keyer_defaults_to_700_hz_at_15_wpm() -> None:
    args = cli.build_parser().parse_args(
        [
            "raw-keyer",
            "--vid",
            "0x04D8",
            "--pid",
            "0x01A6",
            "--dit-scan",
            "0xE01D",
            "--dah-scan",
            "0x001D",
        ]
    )

    assert args.frequency == 700
    assert args.wpm == 15


def test_raw_inspection_stops_cleanly_on_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    device = RawKeyboardDevice(0, 10, r"\\?\HID#VID_04D8&PID_01A6#paddle")

    class InterruptingSession:
        def __init__(self) -> None:
            self.device = device
            self.closed = False
            self.reads = 0

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            self.closed = True

        def get(self, timeout: float) -> RawKeyEvent | None:
            self.reads += 1
            if self.reads > 1:
                raise KeyboardInterrupt
            return RawKeyEvent(1, 10, device.path, True, 0x1D, True, False, 0xA3)

    class Backend:
        def __init__(self) -> None:
            self.session = InterruptingSession()

        def enumerate(self) -> list[RawKeyboardDevice]:
            return [device]

        def open(self, selected: RawKeyboardDevice) -> InterruptingSession:
            assert selected == device
            return self.session

    backend = Backend()
    monkeypatch.setattr(cli, "windows_backend", lambda: backend)

    result = cli.main(["raw-listen", "--vid", "0x04D8", "--pid", "0x01A6", "--inspect"])

    output = capsys.readouterr().out
    assert result == 0
    assert "RAWKEY MAKE" in output
    assert "Capture stopped." in output
    assert backend.session.closed
