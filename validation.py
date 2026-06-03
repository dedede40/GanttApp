"""Schedule constraint validation."""
from datetime import date, timedelta
from typing import List

from models import AppData, MACHINE_IDS, PERIOD_START, PERIOD_END, MACHINE_NAMES


def validate(app_data: AppData) -> List[str]:
    errors: List[str] = []
    bars  = app_data.machine_bars
    maint = app_data.maintenance_bars

    # Date sanity per bar
    for b in bars:
        name = MACHINE_NAMES.get(b.machine_id, b.machine_id)
        if b.end < b.start:
            errors.append(f"{name} {b.engine_id}: 終了日が開始日より前です")
        if b.start < PERIOD_START or b.end > PERIOD_END:
            errors.append(f"{name} {b.engine_id}: 対象期間外です")

    for b in maint:
        if b.end < b.start:
            errors.append(f"別枠 {b.engine_id}: 終了日が開始日より前です")
        if b.start < PERIOD_START or b.end > PERIOD_END:
            errors.append(f"別枠 {b.engine_id}: 対象期間外です")
        if not b.status:
            errors.append(f"別枠 {b.engine_id}: 状態名が未入力です")

    # Continuity per machine (no gap, no overlap, full period coverage)
    for mid in MACHINE_IDS:
        mbars = sorted([b for b in bars if b.machine_id == mid], key=lambda x: x.start)
        name  = MACHINE_NAMES[mid]
        if not mbars:
            errors.append(f"{name}: 配置されていません")
            continue
        if mbars[0].start != PERIOD_START:
            errors.append(f"{name}: {PERIOD_START} から始まっていません")
        if mbars[-1].end != PERIOD_END:
            errors.append(f"{name}: {PERIOD_END} まで続いていません")
        for i in range(len(mbars) - 1):
            expected = mbars[i].end + timedelta(days=1)
            if mbars[i + 1].start != expected:
                errors.append(f"{name}: バー間に隙間または重複があります")

    # No engine on multiple machines at same time
    for i, b1 in enumerate(bars):
        for b2 in bars[i + 1:]:
            if b1.engine_id != b2.engine_id:
                continue
            if b1.start <= b2.end and b2.start <= b1.end:
                errors.append(
                    f"ガスタービン {b1.engine_id}: 同時に複数本体に配置されています"
                )

    # No engine on machine and in maintenance at same time
    for mb in bars:
        for mn in maint:
            if mb.engine_id != mn.engine_id:
                continue
            if mb.start <= mn.end and mn.start <= mb.end:
                errors.append(
                    f"ガスタービン {mb.engine_id}: 本体バーと別枠バーが期間重複しています"
                )

    return errors
