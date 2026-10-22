# -*- coding: utf-8 -*-
"""Файловое хранилище кандидатов."""

from pathlib import Path
from typing import Dict, List

from src.storage.base_storage import BaseStorage


class FileCandidateStorage(BaseStorage):
    """Хранит кандидатов в JSON-файле на диске."""

    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/candidates.json", "CV_")

    def _read_all(self) -> List[Dict[str, object]]:
        data = self._load()
        return sorted(data.values(), key=lambda c: c.get("timestamp", ""), reverse=True)

    def save_candidate(self, candidate: Dict[str, object]) -> Dict[str, object]:
        """Сохраняет кандидата и возвращает сохранённую запись."""
        payload = dict(candidate)
        candidate_id = str(payload.get("id", "")).strip() or self._generate_id()
        payload["id"] = candidate_id
        data = self._load()
        data[candidate_id] = payload
        self._save(data)
        return payload

    def list_candidates(self) -> List[Dict[str, object]]:
        """Возвращает список кандидатов."""
        return self._read_all()

    def get_candidate(self, candidate_id: str) -> Dict[str, object] | None:
        candidate = self._load().get(str(candidate_id))
        return candidate if isinstance(candidate, dict) else None

    def delete_candidate(self, candidate_id: str) -> bool:
        data = self._load()
        if str(candidate_id) not in data:
            return False
        del data[str(candidate_id)]
        self._save(data)
        return True
