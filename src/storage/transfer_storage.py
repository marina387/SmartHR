# -*- coding: utf-8 -*-
"""Аудит добавлений и переносов кандидатов."""

from pathlib import Path
from typing import Any, Dict, List

from src.storage.base_storage import BaseStorage


class TransferStorage(BaseStorage):
    def __init__(self, file_path: str | Path | None = None) -> None:
        super().__init__(file_path or "data/candidate_transfers.json", "TRF_")

    def list_all(self) -> List[Dict[str, Any]]:
        return list(self._load().values())

    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = dict(payload)
        record_id = str(record.get("id", "")).strip() or self._generate_id()
        record["id"] = record_id
        data = self._load()
        data[record_id] = record
        self._save(data)
        return record
