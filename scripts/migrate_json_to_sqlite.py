"""Однократный перенос рабочих JSON-хранилищ SmartHR в SQLite."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from src.extensions import db
from src.models import ScoreResult
from src.storage.sql_storage import (
    SqlCandidateStorage, SqlCandidateVacancyStorage, SqlFeedbackStorage,
    SqlInterviewStorage, SqlStageEventStorage, SqlTemplateStorage,
    SqlTransferStorage, SqlVacancyStorage,
)


SOURCES = [
    ("vacancies.json", SqlVacancyStorage()),
    ("templates.json", SqlTemplateStorage()),
    ("candidates.json", SqlCandidateStorage()),
    ("candidate_vacancies.json", SqlCandidateVacancyStorage()),
    ("candidate_stage_events.json", SqlStageEventStorage()),
    ("interviews.json", SqlInterviewStorage()),
    ("feedback.json", SqlFeedbackStorage()),
    ("candidate_transfers.json", SqlTransferStorage()),
]


def read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8").strip() or "{}"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        # Старые файловые записи могли склеиться (например, ``{}{}``).
        decoder = json.JSONDecoder()
        position = 0
        fragments: list[Any] = []
        while position < len(text):
            value, position = decoder.raw_decode(text, position)
            fragments.append(value)
            while position < len(text) and text[position].isspace():
                position += 1
        merged: dict[str, Any] = {}
        for fragment in fragments:
            if isinstance(fragment, dict):
                merged.update(fragment)
        raw = merged
    if isinstance(raw, dict):
        return [value for value in raw.values() if isinstance(value, dict)]
    return [value for value in raw if isinstance(value, dict)] if isinstance(raw, list) else []


def backup_sources() -> Path:
    target = ROOT / "data" / "json_backup" / datetime.now().strftime("%Y%m%d_%H%M%S")
    target.mkdir(parents=True, exist_ok=True)
    for filename, _ in SOURCES:
        source = ROOT / "data" / filename
        if source.exists():
            shutil.copy2(source, target / filename)
    return target


def migrate() -> dict[str, int]:
    counts: dict[str, int] = {}
    for filename, repository in SOURCES:
        records = read_records(ROOT / "data" / filename)
        for record in records:
            repository.save(record)
        counts[filename] = len(records)

    candidates = SqlCandidateStorage().list_candidates()
    existing_pairs = {
        (str(row.candidate_id), str(row.vacancy_id), str(row.created_at))
        for row in db.session.query(ScoreResult).all()
    }
    added_scores = 0
    for candidate in candidates:
        if candidate.get("total") is None or not candidate.get("vacancy_id"):
            continue
        created_at = str(candidate.get("timestamp") or candidate.get("created_at") or "")
        key = (str(candidate["id"]), str(candidate["vacancy_id"]), created_at)
        if key in existing_pairs:
            continue
        db.session.add(ScoreResult(
            candidate_id=str(candidate["id"]), vacancy_id=str(candidate["vacancy_id"]),
            total=int(candidate.get("total", 0)),
            model_probability=candidate.get("model_probability"),
            model_version=candidate.get("model_version"), created_at=created_at,
            payload={
                "scores": candidate.get("scores", {}), "used_weights": candidate.get("used_weights", {}),
                "model_features": candidate.get("model_features", {}), "evidence": candidate.get("evidence", {}),
            },
        ))
        added_scores += 1
    db.session.commit()
    counts["score_results"] = added_scores
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Перенос данных SmartHR из JSON в SQLite")
    parser.parse_args()
    with app.app_context():
        backup = backup_sources()
        result = migrate()
        print(json.dumps({"backup": str(backup), "migrated": result}, ensure_ascii=False, indent=2))
