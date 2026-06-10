"""JSON serialisation / deserialisation for AppData."""
import json
from pathlib import Path

from models import (
    AppData, Engine, MachineBar, MaintenanceBar,
    DEFAULT_COLORS, MACHINE_IDS, parse_date8, dump_date8,
)


def _req(d: dict, key: str, expected_type=None):
    if key not in d:
        raise ValueError(f"必須項目が欠落: {key!r}")
    val = d[key]
    if expected_type and not isinstance(val, expected_type):
        raise ValueError(f"型不一致: {key!r} は {expected_type.__name__} 型が必要")
    return val


def load_json(path: str) -> AppData:
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)

    engines = []
    for e in data.get("engines", []):
        eid = str(_req(e, "id"))
        engines.append(Engine(
            id=eid,
            color=e.get("color", DEFAULT_COLORS.get(eid, "#888888")),
            initial_hours=float(e.get("initial_hours", 0)),
        ))

    sched = data.get("schedule", {})

    machine_bars = []
    for b in sched.get("machine_bars", []):
        machine_bars.append(MachineBar(
            machine_id=str(_req(b, "machine_id")),
            engine_id=str(_req(b, "engine_id")),
            start=parse_date8(str(_req(b, "start"))),
            end=parse_date8(str(_req(b, "end"))),
            operation_rate=float(b.get("operation_rate", 0.8)),
        ))

    maintenance_bars = []
    for b in sched.get("maintenance_bars", []):
        maintenance_bars.append(MaintenanceBar(
            engine_id=str(_req(b, "engine_id")),
            start=parse_date8(str(_req(b, "start"))),
            end=parse_date8(str(_req(b, "end"))),
            status=str(_req(b, "status")),
            required_duration=str(b.get("required_duration", "")),
        ))

    return AppData(engines=engines, machine_bars=machine_bars, maintenance_bars=maintenance_bars)


def save_json(app_data: AppData, path: str) -> None:
    data = {
        "engines": [
            {"id": e.id, "color": e.color, "initial_hours": e.initial_hours}
            for e in app_data.engines
        ],
        "machines": [
            {"id": mid, "name": f"{mid}号機"} for mid in MACHINE_IDS
        ],
        "schedule": {
            "machine_bars": [
                {
                    "machine_id": b.machine_id,
                    "engine_id": b.engine_id,
                    "start": dump_date8(b.start),
                    "end": dump_date8(b.end),
                    "operation_rate": b.operation_rate,
                }
                for b in app_data.machine_bars
            ],
            "maintenance_bars": [
                {
                    "engine_id": b.engine_id,
                    "start": dump_date8(b.start),
                    "end": dump_date8(b.end),
                    "status": b.status,
                    "required_duration": b.required_duration,
                }
                for b in app_data.maintenance_bars
            ],
        },
    }
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
