from collections.abc import Iterator

import pytest

from morse_paddle import hid_source

PADDLE_PATH = rb"\\?\hid#vid_04d8&pid_01a6&mi_01&col02#paddle"
KEYBOARD_PATH = rb"\\?\hid#vid_04d8&pid_01a6&mi_01&col01#keyboard"


def collection(path: bytes, usage_page: int, usage: int, interface: int = 1) -> dict[str, object]:
    return {
        "path": path,
        "vendor_id": 0x04D8,
        "product_id": 0x01A6,
        "usage_page": usage_page,
        "usage": usage,
        "interface_number": interface,
        "manufacturer_string": "hamradio.solutions",
        "product_string": "PaddleAdapter",
    }


class FakeDevice:
    def __init__(self, responses: Iterator[list[int] | OSError]) -> None:
        self.responses = responses
        self.opened_path: bytes | str | None = None
        self.closed = False

    def open_path(self, path: bytes | str) -> None:
        self.opened_path = path

    def set_nonblocking(self, nonblocking: bool) -> None:
        assert nonblocking is False

    def read(self, size: int, timeout_ms: int) -> list[int]:
        response = next(self.responses)
        if isinstance(response, OSError):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def install_hid(
    monkeypatch: pytest.MonkeyPatch,
    collections: list[dict[str, object]],
    devices: list[FakeDevice],
) -> None:
    monkeypatch.setattr(hid_source.hid, "enumerate", lambda vid, pid: collections)
    device_iterator = iter(devices)
    monkeypatch.setattr(hid_source.hid, "device", lambda: next(device_iterator))


def test_exact_windows_path_uses_original_enumerated_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice(iter([[]]))
    install_hid(monkeypatch, [collection(PADDLE_PATH, 0xFF00, 0x01)], [device])

    reader = hid_source.read_device(
        0x04D8,
        0x01A6,
        byte_index=0,
        dit_mask=0x01,
        dah_mask=0x02,
        path=PADDLE_PATH.decode(),
    )

    assert reader.collection.path_text == PADDLE_PATH.decode()
    assert device.opened_path is PADDLE_PATH
    reader.close()


def test_multiple_collections_auto_selects_non_keyboard_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice(iter([[]]))
    install_hid(
        monkeypatch,
        [
            collection(KEYBOARD_PATH, 0x01, 0x06),
            collection(PADDLE_PATH, 0xFF00, 0x01),
        ],
        [device],
    )

    reader = hid_source.read_device(0x04D8, 0x01A6, 0, 0x01, 0x02)

    assert reader.collection.index == 1
    assert device.opened_path == PADDLE_PATH
    reader.close()


def test_auto_selection_retries_after_unreadable_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = FakeDevice(iter([OSError("read error")]))
    second_path = rb"\\?\hid#vid_04d8&pid_01a6&mi_02#gamepad"
    second = FakeDevice(iter([[]]))
    install_hid(
        monkeypatch,
        [
            collection(PADDLE_PATH, 0xFF00, 0x01),
            collection(second_path, 0x01, 0x05, interface=2),
        ],
        [first, second],
    )

    reader = hid_source.read_device(0x04D8, 0x01A6, 0, 0x01, 0x02)

    assert first.closed
    assert reader.collection.index == 1
    assert second.opened_path == second_path
    reader.close()


def test_auto_selection_prefers_collection_that_reports_during_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    silent = FakeDevice(iter([[]]))
    reporting_path = rb"\\?\hid#vid_04d8&pid_01a6&mi_02#gamepad"
    reporting = FakeDevice(iter([[0x03]]))
    install_hid(
        monkeypatch,
        [
            collection(PADDLE_PATH, 0xFF00, 0x01),
            collection(reporting_path, 0x01, 0x05, interface=2),
        ],
        [silent, reporting],
    )

    reader = hid_source.read_device(0x04D8, 0x01A6, 0, 0x01, 0x02)

    assert silent.closed
    assert reader.collection.index == 1
    assert next(reader).report == b"\x03"
    reader.close()


def test_probe_preserves_first_report_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    device = FakeDevice(iter([[0x01]]))
    install_hid(monkeypatch, [collection(PADDLE_PATH, 0xFF00, 0x01)], [device])
    monkeypatch.setattr(hid_source.time, "perf_counter_ns", lambda: 123456789)

    reader = hid_source.read_device(0x04D8, 0x01A6, 0, 0x01, 0x02)

    assert next(reader).timestamp_ns == 123456789
    reader.close()


def test_read_error_has_windows_collection_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
    device = FakeDevice(iter([[], OSError("read error")]))
    install_hid(monkeypatch, [collection(PADDLE_PATH, 0xFF00, 0x01)], [device])
    reader = hid_source.read_device(0x04D8, 0x01A6, 0, 0x01, 0x02)

    with pytest.raises(hid_source.HIDError, match="reserved by the OS"):
        next(reader)

    reader.close()


def test_collection_index_is_scoped_to_filtered_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device = FakeDevice(iter([[]]))
    install_hid(
        monkeypatch,
        [
            collection(KEYBOARD_PATH, 0x01, 0x06),
            collection(PADDLE_PATH, 0xFF00, 0x01),
        ],
        [device],
    )

    reader = hid_source.read_device(
        0x04D8,
        0x01A6,
        0,
        0x01,
        0x02,
        collection_index=1,
    )

    assert device.opened_path == PADDLE_PATH
    reader.close()
