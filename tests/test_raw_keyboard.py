import ctypes
from collections.abc import Iterator
from typing import Self

import pytest

from morse_paddle import _win_raw_input
from morse_paddle.debounce import PaddleDebouncer
from morse_paddle.models import Contact
from morse_paddle.raw_keyboard import (
    KeyboardSampleStream,
    KeyMapping,
    RawInputError,
    RawKeyboardDevice,
    RawKeyEvent,
    list_raw_keyboards,
    normalize_raw_path,
    select_raw_keyboard,
)

PADDLE_PATH = r"\\?\HID#VID_04D8&PID_01A6#paddle#{raw-input}"


class FakeBackend:
    def __init__(self, devices: list[RawKeyboardDevice]) -> None:
        self.devices = devices

    def enumerate(self) -> list[RawKeyboardDevice]:
        return self.devices

    def open(self, device: RawKeyboardDevice) -> "FakeSession":
        return FakeSession(device, iter([]))


class FakeSession:
    def __init__(
        self,
        device: RawKeyboardDevice,
        responses: Iterator[RawKeyEvent | None],
    ) -> None:
        self.device = device
        self.responses = responses

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def get(self, timeout: float) -> RawKeyEvent | None:
        return next(self.responses)


def event(
    timestamp_ns: int,
    is_make: bool,
    scan_code: int,
    *,
    e0: bool = False,
    virtual_key: int = 0,
) -> RawKeyEvent:
    return RawKeyEvent(
        timestamp_ns,
        10,
        PADDLE_PATH,
        is_make,
        scan_code,
        e0,
        False,
        virtual_key,
    )


def test_filters_and_reindexes_raw_keyboards_by_vid_pid() -> None:
    backend = FakeBackend(
        [
            RawKeyboardDevice(0, 1, r"\\?\HID#VID_1111&PID_2222#keyboard"),
            RawKeyboardDevice(1, 10, PADDLE_PATH),
        ]
    )

    devices = list_raw_keyboards(backend, 0x04D8, 0x01A6)

    assert devices == [RawKeyboardDevice(0, 10, PADDLE_PATH)]


def test_selects_exact_raw_path_case_insensitively() -> None:
    device = RawKeyboardDevice(0, 10, PADDLE_PATH)

    selected = select_raw_keyboard([device], PADDLE_PATH.lower())

    assert selected is device
    assert normalize_raw_path(r"\??\HID#DEVICE") == normalize_raw_path(r"\\?\HID#DEVICE")


def test_requires_path_when_vid_pid_match_is_ambiguous() -> None:
    devices = [
        RawKeyboardDevice(0, 10, PADDLE_PATH),
        RawKeyboardDevice(1, 11, PADDLE_PATH + "#second"),
    ]

    with pytest.raises(RawInputError, match="Multiple Raw Input keyboards"):
        select_raw_keyboard(devices)


def test_extended_scan_mapping_and_debounce_confirmation() -> None:
    device = RawKeyboardDevice(0, 10, PADDLE_PATH)
    make = event(1_000_000_000, True, 0x1D, e0=True)
    release = event(1_010_000_000, False, 0x1D, e0=True)
    session = FakeSession(device, iter([make, None, release, None]))
    seen: list[RawKeyEvent] = []
    samples = KeyboardSampleStream(
        session,
        KeyMapping(dit_scan=0xE01D),
        debounce_ms=5,
        event_sink=seen.append,
        clock=lambda: 1_000_000_000,
    )
    debouncer = PaddleDebouncer(5)

    events = []
    for _ in range(4):
        events.extend(debouncer.process(next(samples)))

    assert [(item.contact, item.pressed) for item in events] == [
        (Contact.DIT, True),
        (Contact.DIT, False),
    ]
    assert seen == [make, release]


def test_virtual_key_mapping_ignores_repeat_make() -> None:
    device = RawKeyboardDevice(0, 10, PADDLE_PATH)
    make = event(1, True, 0, virtual_key=0x25)
    repeat = event(2, True, 0, virtual_key=0x25)
    release = event(3, False, 0, virtual_key=0x25)
    session = FakeSession(device, iter([make, repeat, release]))
    samples = KeyboardSampleStream(session, KeyMapping(dah_vkey=0x25), debounce_ms=0)

    first = next(samples)
    second = next(samples)

    assert first.dah_pressed
    assert not second.dah_pressed


def test_raw_input_structures_have_pointer_safe_layouts() -> None:
    pointer_size = ctypes.sizeof(ctypes.c_void_p)

    assert ctypes.sizeof(_win_raw_input.RAWINPUTDEVICELIST) == (16 if pointer_size == 8 else 8)
    assert ctypes.sizeof(_win_raw_input.RAWINPUTHEADER) == (24 if pointer_size == 8 else 16)
    assert ctypes.sizeof(_win_raw_input.RAWKEYBOARD) == 16
    assert ctypes.sizeof(_win_raw_input.RAWINPUTDEVICE) == (16 if pointer_size == 8 else 12)
