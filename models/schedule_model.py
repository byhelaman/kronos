from dataclasses import dataclass
from typing import Optional


@dataclass
class Schedule:
    date: str
    shift: str
    area: str
    start_time: str
    end_time: str
    code: str
    instructor: str
    group: str
    minutes: str
    units: int
