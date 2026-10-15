from morse_paddle.decoder import MorseDecoder
from morse_paddle.models import Contact, ContactEvent


def press(milliseconds: int, contact: Contact) -> ContactEvent:
    return ContactEvent(milliseconds * 1_000_000, contact, True)


def test_decodes_sos_from_timed_presses() -> None:
    decoder = MorseDecoder(unit_ms=10)
    sequence = [
        press(0, Contact.DIT),
        press(10, Contact.DIT),
        press(20, Contact.DIT),
        press(50, Contact.DAH),
        press(60, Contact.DAH),
        press(70, Contact.DAH),
        press(100, Contact.DIT),
        press(110, Contact.DIT),
        press(120, Contact.DIT),
    ]

    for event in sequence:
        decoder.process(event)
    decoder.flush()

    assert decoder.text == "SOS"


def test_marks_unknown_morse_sequence() -> None:
    decoder = MorseDecoder(unit_ms=10)
    for milliseconds in range(0, 60, 10):
        decoder.process(press(milliseconds, Contact.DIT))
    decoder.flush()

    assert decoder.text == "[......?]"

