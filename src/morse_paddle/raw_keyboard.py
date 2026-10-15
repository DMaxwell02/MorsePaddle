import re
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol, Self

from morse_paddle.models import Contact, RawSample


class RawInputError(RuntimeError):
    """An actionable Windows Raw Input error."""


@dataclass(frozen=True, slots=True)
class RawKeyboardDevice:
    index: int
    handle: int
    path: str
    keyboard_type: int = 0
    keyboard_subtype: int = 0
    key_count: int = 0


@dataclass(frozen=True, slots=True)
class RawKeyEvent:
    timestamp_ns: int
    device_handle: int
    device_path: str
    is_make: bool
    scan_code: int
    e0: bool
    e1: bool
    virtual_key: int
    message: int = 0
    extra_information: int = 0

    @property
    def scan_id(self) -> int:
        if self.e1:
            return 0xE100 | self.scan_code
        if self.e0:
            return 0xE000 | self.scan_code
        return self.scan_code


class RawKeyboardSession(Protocol):
    device: RawKeyboardDevice

    def __enter__(self) -> Self: ...

    def __exit__(self, *args: object) -> None: ...

    def get(self, timeout: float) -> RawKeyEvent | None: ...


class RawKeyboardBackend(Protocol):
    def enumerate(self) -> list[RawKeyboardDevice]: ...

    def open(self, device: RawKeyboardDevice) -> RawKeyboardSession: ...


@dataclass(frozen=True, slots=True)
class KeyMapping:
    dit_scan: int | None = None
    dah_scan: int | None = None
    dit_vkey: int | None = None
    dah_vkey: int | None = None

    def contact_for(self, event: RawKeyEvent) -> Contact | None:
        if self.dit_scan == event.scan_id or self.dit_vkey == event.virtual_key:
            return Contact.DIT
        if self.dah_scan == event.scan_id or self.dah_vkey == event.virtual_key:
            return Contact.DAH
        return None


class KeyboardSampleStream(Iterator[RawSample]):
    def __init__(
        self,
        source: RawKeyboardSession,
        mapping: KeyMapping,
        debounce_ms: float,
        event_sink: Callable[[RawKeyEvent], None] | None = None,
        clock: Callable[[], int] = time.perf_counter_ns,
    ) -> None:
        self.source = source
        self.mapping = mapping
        self.debounce_ns = int(debounce_ms * 1_000_000)
        self.event_sink = event_sink
        self.clock = clock
        self.states = {Contact.DIT: False, Contact.DAH: False}
        self.deadlines: dict[Contact, int] = {}
        self.pending_event: RawKeyEvent | None = None

    def __next__(self) -> RawSample:
        while True:
            contact, deadline = self._next_deadline()
            event = self._next_event(deadline)
            if event is None:
                if contact is not None:
                    self.deadlines.pop(contact, None)
                    return self._sample(deadline, b"")
                continue

            if deadline and event.timestamp_ns >= deadline:
                self.pending_event = event
                self.deadlines.pop(contact, None)
                return self._sample(deadline, b"")

            if self.event_sink is not None:
                self.event_sink(event)
            mapped_contact = self.mapping.contact_for(event)
            if mapped_contact is None or self.states[mapped_contact] == event.is_make:
                continue

            self.states[mapped_contact] = event.is_make
            if self.debounce_ns:
                self.deadlines[mapped_contact] = event.timestamp_ns + self.debounce_ns
            report = (
                event.scan_id.to_bytes(2, "little")
                + event.virtual_key.to_bytes(2, "little")
                + bytes([event.is_make])
            )
            return self._sample(event.timestamp_ns, report)

    def _next_event(self, deadline: int) -> RawKeyEvent | None:
        if self.pending_event is not None:
            event = self.pending_event
            self.pending_event = None
            return event
        timeout = 0.1
        if deadline:
            timeout = max(0.0, (deadline - self.clock()) / 1_000_000_000)
        return self.source.get(timeout)

    def _next_deadline(self) -> tuple[Contact | None, int]:
        if not self.deadlines:
            return None, 0
        return min(self.deadlines.items(), key=lambda item: item[1])

    def _sample(self, timestamp_ns: int, report: bytes) -> RawSample:
        return RawSample(
            timestamp_ns,
            self.states[Contact.DIT],
            self.states[Contact.DAH],
            report,
        )


def windows_backend() -> RawKeyboardBackend:
    if sys.platform != "win32":
        raise RawInputError("Windows Raw Input is only available on Windows.")
    from morse_paddle._win_raw_input import WinRawInputBackend

    return WinRawInputBackend()


def list_raw_keyboards(
    backend: RawKeyboardBackend,
    vendor_id: int = 0,
    product_id: int = 0,
) -> list[RawKeyboardDevice]:
    devices = backend.enumerate()
    if vendor_id:
        marker = f"vid_{vendor_id:04x}"
        devices = [device for device in devices if marker in device.path.casefold()]
    if product_id:
        marker = f"pid_{product_id:04x}"
        devices = [device for device in devices if marker in device.path.casefold()]
    return [
        RawKeyboardDevice(
            index=index,
            handle=device.handle,
            path=device.path,
            keyboard_type=device.keyboard_type,
            keyboard_subtype=device.keyboard_subtype,
            key_count=device.key_count,
        )
        for index, device in enumerate(devices)
    ]


def select_raw_keyboard(
    devices: list[RawKeyboardDevice],
    path: str | None = None,
    device_index: int | None = None,
) -> RawKeyboardDevice:
    if not devices:
        raise RawInputError("No matching Raw Input keyboard devices were found.")
    if path is not None:
        requested = normalize_raw_path(path)
        matches = [device for device in devices if normalize_raw_path(device.path) == requested]
        if not matches:
            raise RawInputError(
                "The Raw Input path was not found. Copy the complete path from `raw-devices` "
                "and quote it in PowerShell."
            )
        return matches[0]
    if device_index is not None:
        matches = [device for device in devices if device.index == device_index]
        if not matches:
            available = ", ".join(str(device.index) for device in devices)
            raise RawInputError(
                f"Raw Input device {device_index} was not found; available indices: {available}."
            )
        return matches[0]
    if len(devices) > 1:
        raise RawInputError(
            "Multiple Raw Input keyboards match this VID/PID. Select one with --path or "
            "--device-index after running `raw-devices`."
        )
    return devices[0]


def normalize_raw_path(path: str) -> str:
    normalized = path.rstrip("\0").replace("/", "\\")
    if normalized.startswith("\\??\\"):
        normalized = "\\\\?\\" + normalized[4:]
    return normalized.casefold()


def vid_pid_from_path(path: str) -> tuple[int | None, int | None]:
    match = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", path, re.IGNORECASE)
    if not match:
        return None, None
    return int(match.group(1), 16), int(match.group(2), 16)
