"""Schedule constraint validation."""
from datetime import date, timedelta
from typing import List

from models import AppData, MACHINE_IDS, ENGINE_IDS, PERIOD_START, PERIOD_END, MACHINE_NAMES

# 各号機に必ずタービンが乗っていなければならない期間の末日
MACHINE_RULE_END = date(2032, 12, 31)


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
        if mbars[-1].end < MACHINE_RULE_END:
            errors.append(f"{name}: {MACHINE_RULE_END} まで続いていません（2032年末まで搭載必須）")
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

    # 各タービンは本体＋別枠で 2032年末まで空白なくカバーされていること
    for eid in ENGINE_IDS:
        segs = sorted(
            [(b.start, b.end) for b in bars if b.engine_id == eid] +
            [(b.start, b.end) for b in maint if b.engine_id == eid]
        )
        if not segs:
            errors.append(f"ガスタービン {eid}: 配置されていません")
            continue
        cursor = PERIOD_START
        for s, e in segs:
            if s > cursor:
                errors.append(f"ガスタービン {eid}: {cursor} 付近に空白期間があります")
                break
            cursor = max(cursor, e + timedelta(days=1))
        else:
            if cursor <= MACHINE_RULE_END:
                errors.append(
                    f"ガスタービン {eid}: {MACHINE_RULE_END} までに空白期間があります"
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
