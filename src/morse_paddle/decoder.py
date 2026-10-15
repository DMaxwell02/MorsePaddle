from morse_paddle.models import Contact, ContactEvent

MORSE_TO_TEXT = {
    ".-": "A", "-...": "B", "-.-.": "C", "-..": "D", ".": "E",
    "..-.": "F", "--.": "G", "....": "H", "..": "I", ".---": "J",
    "-.-": "K", ".-..": "L", "--": "M", "-.": "N", "---": "O",
    ".--.": "P", "--.-": "Q", ".-.": "R", "...": "S", "-": "T",
    "..-": "U", "...-": "V", ".--": "W", "-..-": "X", "-.--": "Y",
    "--..": "Z", "-----": "0", ".----": "1", "..---": "2",
    "...--": "3", "....-": "4", ".....": "5", "-....": "6",
    "--...": "7", "---..": "8", "----.": "9",
}
TEXT_TO_MORSE = {text: morse for morse, text in MORSE_TO_TEXT.items()}


class MorseDecoder:
    def __init__(self, unit_ms: float = 80.0) -> None:
        if unit_ms <= 0:
            raise ValueError("unit_ms must be positive")
        self.unit_ns = int(unit_ms * 1_000_000)
        self._symbols: list[str] = []
        self._output: list[str] = []
        self._last_press_ns: int | None = None

    @property
    def text(self) -> str:
        return "".join(self._output)

    @property
    def pending_symbols(self) -> str:
        return "".join(self._symbols)

    def process(self, event: ContactEvent) -> list[str]:
        if event.bounced or not event.pressed:
            return []

        emitted: list[str] = []
        if self._last_press_ns is not None:
            gap = event.timestamp_ns - self._last_press_ns
            if gap >= 7 * self.unit_ns:
                emitted.extend(self._flush_letter())
                if self._output and self._output[-1] != " ":
                    self._output.append(" ")
                    emitted.append(" ")
            elif gap >= 3 * self.unit_ns:
                emitted.extend(self._flush_letter())

        self._symbols.append("." if event.contact is Contact.DIT else "-")
        self._last_press_ns = event.timestamp_ns
        return emitted

    def flush(self) -> list[str]:
        return self._flush_letter()

    def _flush_letter(self) -> list[str]:
        if not self._symbols:
            return []
        code = "".join(self._symbols)
        letter = MORSE_TO_TEXT.get(code, f"[{code}?]")
        self._symbols.clear()
        self._output.append(letter)
        return [letter]

