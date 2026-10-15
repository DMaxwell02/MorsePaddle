from collections.abc import Iterator

from morse_paddle.decoder import TEXT_TO_MORSE
from morse_paddle.models import RawSample


def samples_for_text(
    text: str,
    unit_ms: float = 80.0,
    include_bounce: bool = False,
) -> Iterator[RawSample]:
    unit_ns = int(unit_ms * 1_000_000)
    timestamp_ns = 0
    first_symbol = True

    for character in text.upper():
        if character == " ":
            timestamp_ns += 6 * unit_ns
            first_symbol = True
            continue
        code = TEXT_TO_MORSE.get(character)
        if code is None:
            raise ValueError(f"Cannot simulate unsupported character: {character!r}")

        if not first_symbol:
            timestamp_ns += 2 * unit_ns
        first_symbol = False

        for symbol in code:
            yield from _press_samples(timestamp_ns, symbol, unit_ns, include_bounce)
            timestamp_ns += 2 * unit_ns

    timestamp_ns += 3 * unit_ns
    yield RawSample(timestamp_ns, False, False, b"\x00")


def _press_samples(
    start_ns: int,
    symbol: str,
    unit_ns: int,
    include_bounce: bool,
) -> Iterator[RawSample]:
    dit = symbol == "."
    dah = symbol == "-"
    pressed_report = b"\x01" if dit else b"\x02"

    yield RawSample(start_ns, dit, dah, pressed_report)
    if include_bounce:
        yield RawSample(start_ns + 1_000_000, False, False, b"\x00")
        yield RawSample(start_ns + 2_000_000, dit, dah, pressed_report)
    yield RawSample(start_ns + 8_000_000, dit, dah, pressed_report)

    release_ns = start_ns + unit_ns
    yield RawSample(release_ns, False, False, b"\x00")
    if include_bounce:
        yield RawSample(release_ns + 1_000_000, dit, dah, pressed_report)
        yield RawSample(release_ns + 2_000_000, False, False, b"\x00")
    yield RawSample(release_ns + 8_000_000, False, False, b"\x00")
