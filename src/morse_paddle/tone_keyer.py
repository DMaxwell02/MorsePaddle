import math
import time
from collections.abc import Callable
from typing import Protocol

from morse_paddle.models import Contact
from morse_paddle.raw_keyboard import KeyMapping, RawKeyboardSession, RawKeyEvent


class ToneError(RuntimeError):
    """A tone could not be generated."""


class ToneOutput(Protocol):
    def play(self, frequency_hz: int, duration_ms: int) -> None: ...


class WindowsToneOutput:
    def __init__(self) -> None:
        try:
            import winsound
        except ImportError as exc:
            raise ToneError("Tone output is only available on Windows.") from exc
        self._winsound = winsound

    def play(self, frequency_hz: int, duration_ms: int) -> None:
        try:
            self._winsound.Beep(frequency_hz, duration_ms)
        except (OSError, RuntimeError) as exc:
            raise ToneError(f"Could not play {frequency_hz} Hz tone: {exc}") from exc


class PaddleKeyerState:
    def __init__(self) -> None:
        self.pressed = {Contact.DIT: False, Contact.DAH: False}
        self.memory: set[Contact] = set()
        self.last_element: Contact | None = None

    def update(self, contact: Contact, pressed: bool) -> None:
        if self.pressed[contact] == pressed:
            return
        self.pressed[contact] = pressed
        if pressed:
            self.memory.add(contact)

    def next_element(self) -> Contact | None:
        requested = self.memory | {contact for contact, pressed in self.pressed.items() if pressed}
        if not requested:
            return None
        if len(requested) == 2:
            element = Contact.DAH if self.last_element is Contact.DIT else Contact.DIT
        else:
            element = next(iter(requested))
        self.memory.discard(element)
        self.last_element = element
        return element


class PaddleToneKeyer:
    def __init__(
        self,
        mapping: KeyMapping,
        tone: ToneOutput,
        frequency_hz: int = 700,
        wpm: float = 15,
        event_sink: Callable[[RawKeyEvent], None] | None = None,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        if not 37 <= frequency_hz <= 32767:
            raise ToneError("frequency must be between 37 and 32767 Hz")
        if not math.isfinite(wpm) or wpm <= 0:
            raise ToneError("WPM must be finite and positive")
        self.mapping = mapping
        self.tone = tone
        self.frequency_hz = frequency_hz
        self.unit_ms = 1200 / wpm
        self.event_sink = event_sink
        self.clock = clock
        self.state = PaddleKeyerState()

    def run(self, source: RawKeyboardSession) -> None:
        while True:
            element = self.state.next_element()
            if element is None:
                event = source.get(0.1)
                if event is not None:
                    self._process_event(event)
                continue

            duration_ms = round(self.unit_ms * (1 if element is Contact.DIT else 3))
            self.tone.play(self.frequency_hz, duration_ms)
            self._inter_element_gap(source)

    def _inter_element_gap(self, source: RawKeyboardSession) -> None:
        deadline = self.clock() + round(self.unit_ms * 1_000_000)
        while True:
            remaining_ns = deadline - self.clock()
            if remaining_ns <= 0:
                return
            event = source.get(remaining_ns / 1_000_000_000)
            if event is None:
                return
            self._process_event(event)

    def _process_event(self, event: RawKeyEvent) -> None:
        if self.event_sink is not None:
            self.event_sink(event)
        contact = self.mapping.contact_for(event)
        if contact is not None:
            self.state.update(contact, event.is_make)
