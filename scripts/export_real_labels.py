# -*- coding: utf-8 -*-
"""Выгружает реальные решения рекрутеров из feedback.payload в CSV.

Запуск:
    python scripts/export_real_labels.py
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd


def main() -> None:
    db_path = ROOT / "data" / "smarthr.db"
    if not db_path.exists():
        print(f"БД не найдена: {db_path}")
        return

    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT id, candidate_id, vacancy_id, payload, created_at FROM feedback"
    ).fetchall()

    records = []
    for fid, cand, vac, payload_json, created_at in rows:
        try:
            outer = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        except Exception:
            continue
        if not isinstance(outer, dict):
            continue
        # Разворачиваем двойную вложенность
        inner = outer.get("payload") if isinstance(outer.get("payload"), dict) else outer
        if inner.get("type") != "decision":
            continue
        payload = inner
        records.append({
            "feedback_id": fid,
            "candidate_id": cand,
            "vacancy_id": vac,
            "decision": int(payload["decision"]),
            "model_probability": payload.get("model_probability"),
            "features": payload.get("features", {}),
            "hr_id": payload.get("hr_id"),
            "comment": payload.get("comment", ""),
            "created_at": created_at,
        })

    if not records:
        print("Реальных решений: 0. Пока нечего выгружать. Нажмите кнопки в UI.")
        return

    df = pd.DataFrame(records)
    out = ROOT / "data" / "trudvsem" / "processed_v2" / "real_labels.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")

    print(f"Реальных решений: {len(df)}")
    print(f"  'подходит': {(df['decision'] == 1).sum()}")
    print(f"  'не подходит': {(df['decision'] == 0).sum()}")
    print(f"Сохранено: {out}")


if __name__ == "__main__":
    main()