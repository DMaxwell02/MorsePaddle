from collections.abc import Iterator

import pytest

from morse_paddle.models import Contact
from morse_paddle.raw_keyboard import KeyMapping, RawKeyboardDevice, RawKeyEvent
from morse_paddle.tone_keyer import PaddleKeyerState, PaddleToneKeyer, ToneError

PATH = r"\\?\HID#VID_04D8&PID_01A6#paddle"


def event(timestamp_ns: int, is_make: bool, scan_id: int) -> RawKeyEvent:
    e0 = scan_id & 0xFF00 == 0xE000
    return RawKeyEvent(
        timestamp_ns,
        10,
        PATH,
        is_make,
        scan_id & 0xFF,
        e0,
        False,
        0x11,
    )


class FakeSession:
    def __init__(self, responses: Iterator[RawKeyEvent | None]) -> None:
        self.device = RawKeyboardDevice(0, 10, PATH)
        self.responses = responses

    def get(self, timeout: float) -> RawKeyEvent | None:
        return next(self.responses)


class FakeTone:
    def __init__(self, stop_after: int) -> None:
        self.stop_after = stop_after
        self.calls: list[tuple[int, int]] = []

    def play(self, frequency_hz: int, duration_ms: int) -> None:
        self.calls.append((frequency_hz, duration_ms))
        if len(self.calls) == self.stop_after:
            raise KeyboardInterrupt


def test_15_wpm_generates_80_ms_dit_and_240_ms_dah() -> None:
    source = FakeSession(
        iter(
            [
                event(1, True, 0xE01D),
                event(2, False, 0xE01D),
                None,
                event(3, True, 0x001D),
            ]
        )
    )
    tone = FakeTone(stop_after=2)
    keyer = PaddleToneKeyer(
        KeyMapping(dit_scan=0xE01D, dah_scan=0x001D),
        tone,
        frequency_hz=700,
        wpm=15,
        clock=lambda: 0,
    )

    with pytest.raises(KeyboardInterrupt):
        keyer.run(source)

    assert tone.calls == [(700, 80), (700, 240)]


def test_squeezed_paddles_alternate_elements() -> None:
    state = PaddleKeyerState()
    state.update(Contact.DIT, True)
    state.update(Contact.DAH, True)

    assert [state.next_element() for _ in range(4)] == [
        Contact.DIT,
        Contact.DAH,
        Contact.DIT,
        Contact.DAH,
    ]


def test_tapped_opposite_paddle_is_remembered() -> None:
    state = PaddleKeyerState()
    state.update(Contact.DIT, True)
    assert state.next_element() is Contact.DIT

    state.update(Contact.DAH, True)
    state.update(Contact.DAH, False)

    assert state.next_element() is Contact.DAH
    assert state.next_element() is Contact.DIT


@pytest.mark.parametrize(
    "frequency,wpm",
    [(36, 15), (700, 0), (700, float("nan")), (700, float("inf"))],
)
def test_rejects_invalid_tone_settings(frequency: int, wpm: float) -> None:
    with pytest.raises(ToneError):
        PaddleToneKeyer(KeyMapping(), FakeTone(1), frequency_hz=frequency, wpm=wpm)
