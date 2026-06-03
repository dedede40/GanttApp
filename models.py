"""Data models and constants for GanttApp."""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

# ── Constants ─────────────────────────────────────────────────────────────────

ENGINE_IDS   = ["1868", "2445", "2446", "2450"]
MACHINE_IDS  = ["1", "2", "3"]
MACHINE_NAMES = {"1": "1号機", "2": "2号機", "3": "3号機"}
MAINTENANCE_STATUSES = ["6k点検", "12k点検", "96kOH"]

PERIOD_START = date(2025, 1, 1)
PERIOD_END   = date(2034, 12, 31)
SEG1_START   = date(2025, 1, 1)
SEG1_END     = date(2029, 12, 31)
SEG2_START   = date(2030, 1, 1)
SEG2_END     = date(2034, 12, 31)

DEFAULT_COLORS = {
    "1868": "#4A90D9",
    "2445": "#E8852A",
    "2446": "#2EAA60",
    "2450": "#9B5BB5",
}

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class MachineBar:
    machine_id: str
    engine_id: str
    start: date
    end: date
    operation_rate: float = 0.8  # 0.0 – 1.0

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def hours(self) -> float:
        return self.days * 24.0 * self.operation_rate


@dataclass
class MaintenanceBar:
    engine_id: str
    start: date
    end: date
    status: str


@dataclass
class Engine:
    id: str
    color: str
    initial_hours: float = 0.0


@dataclass
class AppData:
    engines: List[Engine] = field(default_factory=list)
    machine_bars: List[MachineBar] = field(default_factory=list)
    maintenance_bars: List[MaintenanceBar] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(d: date, n: int) -> date:
    month = d.month - 1 + n
    year  = d.year + month // 12
    month = month % 12 + 1
    day   = min(d.day, days_in_month(year, month))
    return date(year, month, day)


def months_between(d1: date, d2: date) -> float:
    return ((d2 - d1).days + 1) / 30.4375


def round_half_month(months: float) -> str:
    v = round(months * 2) / 2
    if v == int(v):
        return f"{int(v)}ヶ月"
    return f"{v:.1f}ヶ月"


def fmt_date(d: date) -> str:
    return d.strftime("%Y年%m月%d日")


def parse_date8(s: str) -> date:
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def dump_date8(d: date) -> str:
    return d.strftime("%Y%m%d")


def engine_by_id(app_data: AppData, eid: str) -> Optional[Engine]:
    for e in app_data.engines:
        if e.id == eid:
            return e
    return None
