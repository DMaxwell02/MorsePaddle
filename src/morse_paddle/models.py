from dataclasses import dataclass
from enum import Enum


class Contact(str, Enum):
    DIT = "dit"
    DAH = "dah"


@dataclass(frozen=True, slots=True)
class RawSample:
    timestamp_ns: int
    dit_pressed: bool
    dah_pressed: bool
    report: bytes


@dataclass(frozen=True, slots=True)
class ContactEvent:
    timestamp_ns: int
    contact: Contact
    pressed: bool
    bounced: bool = False

