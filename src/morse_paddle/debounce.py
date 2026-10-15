from dataclasses import dataclass

from morse_paddle.models import Contact, ContactEvent, RawSample


@dataclass(slots=True)
class _ContactState:
    accepted: bool = False
    candidate: bool | None = None
    candidate_since_ns: int = 0


class PaddleDebouncer:
    def __init__(self, debounce_ms: float = 5.0) -> None:
        if debounce_ms < 0:
            raise ValueError("debounce_ms must be non-negative")
        self.window_ns = int(debounce_ms * 1_000_000)
        self._states = {
            Contact.DIT: _ContactState(),
            Contact.DAH: _ContactState(),
        }
        self.bounce_count = 0

    def process(self, sample: RawSample) -> list[ContactEvent]:
        events: list[ContactEvent] = []
        for contact, raw_state in (
            (Contact.DIT, sample.dit_pressed),
            (Contact.DAH, sample.dah_pressed),
        ):
            state = self._states[contact]
            if raw_state == state.accepted:
                if state.candidate is not None:
                    self.bounce_count += 1
                    events.append(
                        ContactEvent(sample.timestamp_ns, contact, raw_state, bounced=True)
                    )
                    state.candidate = None
                continue

            if state.candidate != raw_state:
                state.candidate = raw_state
                state.candidate_since_ns = sample.timestamp_ns

            if sample.timestamp_ns - state.candidate_since_ns >= self.window_ns:
                state.accepted = raw_state
                state.candidate = None
                events.append(ContactEvent(sample.timestamp_ns, contact, raw_state))

        return events

