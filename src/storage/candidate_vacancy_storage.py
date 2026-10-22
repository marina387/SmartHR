# -*- coding: utf-8 -*-
"""Хранилище связей кандидатов с вакансиями."""

from pathlib import Path
from typing import Any, Dict, List

from src.storage.base_storage import BaseStorage


class CandidateVacancyStorage(BaseStorage):
    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/candidate_vacancies.json", "APP_")

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self._load().values())

    def list_by_candidate(self, candidate_id: str) -> List[Dict[str, Any]]:
        return [item for item in self.list_all() if str(item.get("candidate_id")) == str(candidate_id)]

    def find(self, candidate_id: str, vacancy_id: str) -> Dict[str, Any] | None:
        return next((item for item in self.list_by_candidate(candidate_id) if str(item.get("vacancy_id")) == str(vacancy_id)), None)

    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(payload)
        record_id = str(record.get("id", "")).strip() or self._generate_id()
        record["id"] = record_id
        data = self._load()
        data[record_id] = record
        self._save(data)
        return record
