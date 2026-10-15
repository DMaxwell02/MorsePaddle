import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, Self

import hid

from morse_paddle.models import RawSample


class HIDError(RuntimeError):
    """An actionable HID error that can be shown without a traceback."""


class HIDDevice(Protocol):
    def open_path(self, path: bytes | str) -> None: ...

    def set_nonblocking(self, nonblocking: bool) -> None: ...

    def read(self, size: int, timeout_ms: int) -> list[int]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class HIDCollection:
    index: int
    path: bytes | str
    vendor_id: int
    product_id: int
    usage_page: int
    usage: int
    interface_number: int
    manufacturer: str
    product: str

    @property
    def path_text(self) -> str:
        return os.fsdecode(self.path)

    @property
    def is_protected_input(self) -> bool:
        # Windows normally reserves top-level keyboard and mouse collections.
        return self.usage_page == 0x01 and self.usage in {0x02, 0x06}


class HIDReader(Iterator[RawSample]):
    def __init__(
        self,
        device: HIDDevice,
        collection: HIDCollection,
        byte_index: int,
        dit_mask: int,
        dah_mask: int,
        invert: bool,
        timeout_ms: int,
        initial_report: tuple[list[int], int] | None = None,
    ) -> None:
        self.device = device
        self.collection = collection
        self.byte_index = byte_index
        self.dit_mask = dit_mask
        self.dah_mask = dah_mask
        self.invert = invert
        self.timeout_ms = timeout_ms
        self.initial_report = initial_report
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __next__(self) -> RawSample:
        while True:
            try:
                if self.initial_report is not None:
                    report_values, timestamp_ns = self.initial_report
                    self.initial_report = None
                else:
                    report_values = self.device.read(64, self.timeout_ms)
                    timestamp_ns = time.perf_counter_ns()
            except OSError as exc:
                raise HIDError(_access_error("read from", self.collection, exc)) from exc

            if not report_values:
                continue
            report = bytes(report_values)
            if self.byte_index >= len(report):
                raise HIDError(
                    f"HID report has {len(report)} bytes; --byte-index {self.byte_index} "
                    "is out of range."
                )
            value = report[self.byte_index]
            dit_pressed = bool(value & self.dit_mask)
            dah_pressed = bool(value & self.dah_mask)
            if self.invert:
                dit_pressed = not dit_pressed
                dah_pressed = not dah_pressed
            return RawSample(
                timestamp_ns=timestamp_ns,
                dit_pressed=dit_pressed,
                dah_pressed=dah_pressed,
                report=report,
            )

    def close(self) -> None:
        if not self.closed:
            self.device.close()
            self.closed = True


def list_devices(vendor_id: int = 0, product_id: int = 0) -> list[HIDCollection]:
    try:
        devices = hid.enumerate(vendor_id, product_id)
    except OSError as exc:
        raise HIDError(f"Could not enumerate HID devices: {exc}") from exc

    return [_collection(index, device) for index, device in enumerate(devices)]


def read_device(
    vendor_id: int,
    product_id: int,
    byte_index: int,
    dit_mask: int,
    dah_mask: int,
    invert: bool = False,
    timeout_ms: int = 50,
    path: str | None = None,
    collection_index: int | None = None,
) -> HIDReader:
    collections = list_devices(vendor_id, product_id)
    if not collections:
        raise HIDError(
            f"No HID collections found for VID=0x{vendor_id:04X} PID=0x{product_id:04X}."
        )

    explicit = path is not None or collection_index is not None
    candidates = _select_candidates(collections, path, collection_index)
    failures: list[str] = []
    fallback: tuple[HIDDevice, HIDCollection] | None = None
    for collection in candidates:
        device: HIDDevice = hid.device()
        try:
            device.open_path(collection.path)
            device.set_nonblocking(False)
            initial_report = device.read(64, min(timeout_ms, 10))
            timestamp_ns = time.perf_counter_ns()
        except OSError as exc:
            device.close()
            failures.append(f"[{collection.index}] {exc}")
            if explicit:
                raise HIDError(_access_error("open/read", collection, exc)) from exc
            continue

        if initial_report or explicit:
            if fallback is not None:
                fallback[0].close()
            return HIDReader(
                device,
                collection,
                byte_index,
                dit_mask,
                dah_mask,
                invert,
                timeout_ms,
                (initial_report, timestamp_ns) if initial_report else None,
            )

        if fallback is None:
            fallback = device, collection
        else:
            device.close()

    if fallback is not None:
        device, collection = fallback
        return HIDReader(
            device,
            collection,
            byte_index,
            dit_mask,
            dah_mask,
            invert,
            timeout_ms,
        )

    detail = "; ".join(failures)
    raise HIDError(
        "No readable HID input collection was found"
        + (f" ({detail})" if detail else "")
        + ". Close other paddle/keyer applications that may have exclusive use and retry. On "
        "Windows, keyboard and mouse collections are commonly reserved by the OS; use "
        "`morse-paddle devices --vid "
        f"0x{vendor_id:04X} --pid 0x{product_id:04X}` and select a different collection with "
        "--path or --collection."
    )


def _select_candidates(
    collections: list[HIDCollection],
    path: str | None,
    collection_index: int | None,
) -> list[HIDCollection]:
    if path is not None:
        matches = [collection for collection in collections if collection.path_text == path]
        if not matches:
            raise HIDError(
                "The requested HID path was not found for this VID/PID. Copy the full path from "
                "`morse-paddle devices --vid ... --pid ...` and quote it in PowerShell."
            )
        return matches

    if collection_index is not None:
        matches = [collection for collection in collections if collection.index == collection_index]
        if not matches:
            available = ", ".join(str(collection.index) for collection in collections)
            raise HIDError(
                f"HID collection {collection_index} was not found; available indices: {available}."
            )
        return matches

    if len(collections) == 1:
        return collections

    readable_candidates = [
        collection for collection in collections if not collection.is_protected_input
    ]
    if not readable_candidates:
        raise HIDError(
            "This VID/PID exposes only keyboard/mouse HID collections. Windows normally reserves "
            "those collections, so hidapi cannot read them. Close software using the paddle or "
            "select an exact collection with --path/--collection to confirm the limitation."
        )

    return sorted(readable_candidates, key=_collection_rank)


def _collection_rank(collection: HIDCollection) -> tuple[int, int]:
    if collection.usage_page >= 0xFF00:
        rank = 0
    elif collection.usage_page == 0x01 and collection.usage in {0x04, 0x05, 0x08}:
        rank = 1
    else:
        rank = 2
    return rank, collection.index


def _collection(index: int, device: dict[str, object]) -> HIDCollection:
    path = device.get("path")
    if not isinstance(path, (bytes, str)):
        path = ""
    return HIDCollection(
        index=index,
        path=path,
        vendor_id=_integer(device.get("vendor_id")),
        product_id=_integer(device.get("product_id")),
        usage_page=_integer(device.get("usage_page")),
        usage=_integer(device.get("usage")),
        interface_number=_integer(device.get("interface_number"), -1),
        manufacturer=str(device.get("manufacturer_string") or "Unknown manufacturer"),
        product=str(device.get("product_string") or "Unknown product"),
    )


def _integer(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _access_error(action: str, collection: HIDCollection, error: OSError) -> str:
    return (
        f"Could not {action} HID collection [{collection.index}] at {collection.path_text!r}: "
        f"{error}. Close other paddle/keyer applications that may have exclusive use and retry. "
        "On Windows, keyboard HID collections may be reserved by the OS; choose a non-keyboard "
        "path shown by `devices`. If the path ends in `\\KBD`, use `morse-paddle raw-devices` "
        "and `morse-paddle raw-listen` instead."
    )
