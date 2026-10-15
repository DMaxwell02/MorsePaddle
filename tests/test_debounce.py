from morse_paddle.debounce import PaddleDebouncer
from morse_paddle.models import Contact, RawSample


def sample(milliseconds: float, dit: bool = False, dah: bool = False) -> RawSample:
    return RawSample(int(milliseconds * 1_000_000), dit, dah, b"")


def test_rejects_contact_bounce_and_accepts_stable_press() -> None:
    debouncer = PaddleDebouncer(debounce_ms=5)

    events = []
    for raw_sample in [
        sample(0),
        sample(1, dit=True),
        sample(2),
        sample(3, dit=True),
        sample(8, dit=True),
    ]:
        events.extend(debouncer.process(raw_sample))

    accepted = [event for event in events if not event.bounced]
    assert [(event.contact, event.pressed) for event in accepted] == [(Contact.DIT, True)]
    assert debouncer.bounce_count == 1


def test_tracks_dit_and_dah_independently() -> None:
    debouncer = PaddleDebouncer(debounce_ms=2)
    debouncer.process(sample(0, dit=True, dah=True))
    events = debouncer.process(sample(2, dit=True, dah=True))

    assert {(event.contact, event.pressed) for event in events} == {
        (Contact.DIT, True),
        (Contact.DAH, True),
    }

