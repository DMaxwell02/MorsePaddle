from io import StringIO
from pathlib import Path

import pytest

from morse_paddle import cli
from morse_paddle.hid_source import HIDCollection, HIDError


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
