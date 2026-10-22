# -*- coding: utf-8 -*-
"""Базовый класс для JSON-хранилищ."""

import json
from pathlib import Path
from typing import Any, Dict


class BaseStorage:
    """Общий слой чтения и записи JSON-файлов."""

    def __init__(self, file_path: str | Path, id_prefix: str) -> None:
        self.file_path = Path(file_path)
        self.id_prefix = id_prefix
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._save({})

    def _load(self) -> Dict[str, Any]:
        """Загружает данные из JSON-файла."""
        if not self.file_path.exists():
            self._save({})
            return {}

        try:
            raw = self.file_path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, OSError):
            return {}

        if isinstance(data, dict):
            return {str(key): value for key, value in data.items() if isinstance(value, dict)}

        if isinstance(data, list):
            result: Dict[str, Any] = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id", "")).strip()
                if item_id:
                    result[item_id] = item
            return result

        return {}

    def _save(self, data: Dict[str, Any]) -> None:
        """Сохраняет данные в JSON-файл."""
        self.file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _generate_id(self) -> str:
        """Генерирует следующий ID на основе префикса хранилища."""
        data = self._load()
        max_number = 0

        for raw_id in data.keys():
            key = str(raw_id)
            if not key.startswith(self.id_prefix):
                continue
            suffix = key.replace(self.id_prefix, "", 1)
            if suffix.isdigit():
                max_number = max(max_number, int(suffix))

        return f"{self.id_prefix}{max_number + 1:03d}"