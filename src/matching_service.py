# -*- coding: utf-8 -*-
"""Рабочий сервис модели соответствия кандидата вакансии.

Модель: matching_model.pkl (обучена на реальных данных trudvsem).
Фичи (11): experience_years, min_experience, max_experience,
           expected_salary, max_salary, cand_edu_idx, vac_edu_idx,
           same_spec, skills_match, cand_skills_count, vac_skills_count.

Все методы — обратная совместимость:
- predict(candidate, vacancy) -> dict с probability, decision, features
- predict_match(candidate_id, vacancy_id) -> dict для UI
- batch_predict(candidate_ids, vacancy_id) -> list
- find_best_candidates(vacancy_id, top_n) -> list
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import joblib
import pandas as pd

from src.services.skill_matching import SkillMatcher


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MODEL_PATH = ROOT_DIR / "models" / "matching_model.pkl"
DEFAULT_META_PATH = ROOT_DIR / "models" / "model_metadata.json"
DEFAULT_CANDIDATES_CSV = ROOT_DIR / "data" / "candidates.csv"
DEFAULT_VACANCIES_CSV = ROOT_DIR / "data" / "vacancies.csv"
THRESHOLD_METRICS_PATH = ROOT_DIR / "evaluation" / "results" / "threshold_metrics.csv"

# Уровни образования — должны совпадать с порядком в конвертере.
EDU_LEVELS = ["none", "high_school", "associate", "bachelor", "master", "phd"]

# Дефолтные пороги, если threshold_metrics.csv нет.
DEFAULT_DECISION_THRESHOLD = 0.5
DEFAULT_INVITE_THRESHOLD = 0.6


@lru_cache(maxsize=4)
def _load_threshold_metrics(path: Path, mtime: float) -> Optional[pd.DataFrame]:
    """Кэширует threshold_metrics.csv до изменения mtime."""
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


class MatchingService:
    """Загружает модель и формирует 11 входных признаков."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        meta_path: str | Path | None = None,
        candidates_path: str | Path | None = None,
        vacancies_path: str | Path | None = None,
        threshold_metrics_path: str | Path | None = None,
    ) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self.meta_path = Path(meta_path or DEFAULT_META_PATH)
        self.candidates_path = Path(candidates_path or DEFAULT_CANDIDATES_CSV)
        self.vacancies_path = Path(vacancies_path or DEFAULT_VACANCIES_CSV)
        self.threshold_metrics_path = Path(threshold_metrics_path or THRESHOLD_METRICS_PATH)

        if not self.model_path.exists():
            raise RuntimeError(f"Файл модели не найден: {self.model_path}")
        if not self.meta_path.exists():
            raise RuntimeError(f"Метаданные модели не найдены: {self.meta_path}")

        self.model = joblib.load(self.model_path)
        self.metadata = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.feature_names: List[str] = list(self.metadata.get("features", []))
        if not self.feature_names:
            raise RuntimeError("В metadata отсутствует список features")

        # Мягкая проверка: sklearn не всегда сохраняет feature_names_in_.
        model_features = list(getattr(self.model, "feature_names_in_", []))
        if model_features and model_features != self.feature_names:
            raise RuntimeError(
                f"Порядок признаков модели не совпадает с metadata: "
                f"model={model_features}, metadata={self.feature_names}"
            )

        self.education_levels: List[str] = list(self.metadata.get("education_levels", EDU_LEVELS))
        self.model_loaded = True
        self.skill_matcher = SkillMatcher()

        self.candidates_df = self._safe_read_csv(self.candidates_path)
        self.vacancies_df = self._safe_read_csv(self.vacancies_path)

        self._decision_threshold = self._calibrate_threshold("f1", DEFAULT_DECISION_THRESHOLD)
        self._invite_threshold = self._calibrate_threshold("precision", DEFAULT_INVITE_THRESHOLD)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _safe_read_csv(path: Path) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()

    def _calibrate_threshold(self, metric: str, fallback: float) -> float:
        df = self._threshold_df()
        if df is None or df.empty:
            return fallback
        if "threshold" not in df.columns or metric not in df.columns:
            return fallback
        try:
            idx = df[metric].astype(float).idxmax()
            value = float(df.loc[idx, "threshold"])
        except Exception:
            return fallback
        if not (0.0 < value < 1.0):
            return fallback
        return value

    def _threshold_df(self) -> Optional[pd.DataFrame]:
        if not self.threshold_metrics_path.exists():
            return None
        mtime = self.threshold_metrics_path.stat().st_mtime
        return _load_threshold_metrics(self.threshold_metrics_path, mtime)

    @property
    def decision_threshold(self) -> float:
        return self._decision_threshold

    @property
    def invite_threshold(self) -> float:
        return self._invite_threshold

    @staticmethod
    def _items(value: Any) -> List[str]:
        if isinstance(value, (list, tuple, set)):
            raw: Iterable[Any] = value
        elif value is None or (isinstance(value, float) and pd.isna(value)):
            raw = []
        else:
            raw = str(value).replace(";", ",").split(",")
        return [str(item).strip().casefold() for item in raw if str(item).strip()]

    @staticmethod
    def _number(value: Any, default: float) -> float:
        try:
            if value is None or (isinstance(value, float) and pd.isna(value)):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _edu_idx(value: Any) -> int:
        """Индекс уровня образования. Порядок: none, high_school, associate, bachelor, master, phd."""
        text = str(value or "").strip().lower()
        # Прямое совпадение с EDU_LEVELS
        if text in EDU_LEVELS:
            return EDU_LEVELS.index(text)
        # Маппинг русских названий (для совместимости со старыми данными)
        mapping = {
            "не указано": 0, "не имеет значение": 0, "требования не предъявляются": 0,
            "общее образование": 1, "среднее общее": 1, "основное общее": 1,
            "среднее профессиональное": 2, "среднее специальное": 2,
            "бакалавриат": 3, "бакалавр": 3,
            "специалитет": 4, "магистратура": 4, "магистр": 4,
            "подготовка кадров высшей квалификации": 5, "аспирантура": 5,
        }
        for key, idx in mapping.items():
            if key in text:
                return idx
        return 0

    # ------------------------------------------------------------------ features

    def calculate_skills_match(self, candidate_skills: Any, vacancy_skills: Any) -> float:
        result = self.skill_matcher.compare(candidate_skills, vacancy_skills)
        return float(result.get("score", 0.0))

    def prepare_features(self, candidate: Any, vacancy: Any) -> pd.DataFrame:
        """Формирует 11 фич ровно в порядке self.feature_names."""
        exp = self._number(candidate.get("experience_years"), 0.0)
        exp = max(0.0, min(exp, 60.0))

        min_e = self._number(vacancy.get("min_experience"), 0.0)
        min_e = max(0.0, min(min_e, 60.0))

        max_e = self._number(vacancy.get("max_experience"), min_e)
        max_e = max(min_e, min(max_e, 60.0))

        exp_sal = self._number(candidate.get("expected_salary"), 0.0)
        max_sal = self._number(vacancy.get("max_salary"), 0.0)

        cand_edu_idx = float(self._edu_idx(candidate.get("education")))
        vac_edu_idx = float(self._edu_idx(vacancy.get("required_education")))

        cand_spec = str(candidate.get("specialization") or "").strip().casefold()
        vac_spec = str(vacancy.get("specialization") or "").strip().casefold()
        same_spec = float(bool(cand_spec and vac_spec and cand_spec == vac_spec))

        cand_sk = set(self._items(candidate.get("skills")))
        vac_sk = set(self._items(vacancy.get("required_skills") or vacancy.get("critical_requirements")))
        skills_match = float(len(cand_sk & vac_sk) / max(len(vac_sk), 1)) if vac_sk else 0.0
        cand_skills_count = float(len(cand_sk))
        vac_skills_count = float(len(vac_sk))

        values: Dict[str, float] = {
            "experience_years": exp,
            "min_experience": min_e,
            "max_experience": max_e,
            "expected_salary": exp_sal,
            "max_salary": max_sal,
            "cand_edu_idx": cand_edu_idx,
            "vac_edu_idx": vac_edu_idx,
            "same_spec": same_spec,
            "skills_match": skills_match,
            "cand_skills_count": cand_skills_count,
            "vac_skills_count": vac_skills_count,
        }
        return pd.DataFrame([[values[name] for name in self.feature_names]], columns=self.feature_names)

    # ------------------------------------------------------------------ prediction

    def predict(self, candidate: Any, vacancy: Any) -> Dict[str, Any]:
        features = self.prepare_features(candidate, vacancy)
        probability = float(self.model.predict_proba(features)[0, 1])
        predicted_class = int(self.model.predict(features)[0])
        required_skills = vacancy.get("required_skills") or vacancy.get("critical_requirements") or []
        return {
            "probability": probability,
            "predicted_class": predicted_class,
            "decision": "invite" if probability >= self._invite_threshold else "reject",
            "threshold_used": self._invite_threshold,
            "features": {name: float(features.iloc[0][name]) for name in self.feature_names},
            "model_version": self.model_path.stem,
            "skill_match": self.skill_matcher.compare(candidate.get("skills"), required_skills),
        }

    def predict_match(self, candidate_id: int, vacancy_id: int) -> Dict[str, Any]:
        if self.candidates_df.empty or self.vacancies_df.empty:
            return {"error": "Данные кандидатов или вакансий не загружены"}
        candidate_rows = self.candidates_df[self.candidates_df["candidate_id"] == candidate_id]
        vacancy_rows = self.vacancies_df[self.vacancies_df["vacancy_id"] == vacancy_id]
        if candidate_rows.empty or vacancy_rows.empty:
            return {"error": "Кандидат или вакансия не найдены"}
        candidate, vacancy = candidate_rows.iloc[0], vacancy_rows.iloc[0]
        prediction = self.predict(candidate, vacancy)
        return {
            "candidate_name": str(candidate.get("name", candidate.get("candidate_id", ""))),
            "vacancy_title": str(vacancy.get("title", vacancy.get("vacancy_id", ""))),
            "match_probability": round(prediction["probability"], 6),
            "decision": prediction["decision"],
            "threshold_used": prediction["threshold_used"],
            "details": prediction["features"],
            "model_version": prediction["model_version"],
        }

    def batch_predict(self, candidate_ids: Iterable[int], vacancy_id: int) -> List[Dict[str, Any]]:
        valid = [
            item for item in (self.predict_match(cid, vacancy_id) for cid in candidate_ids)
            if "error" not in item
        ]
        return sorted(valid, key=lambda item: item["match_probability"], reverse=True)

    def find_best_candidates(self, vacancy_id: int, top_n: int = 10) -> List[Dict[str, Any]]:
        if self.candidates_df.empty or "candidate_id" not in self.candidates_df.columns:
            return []
        candidate_ids = self.candidates_df["candidate_id"].head(100).tolist()
        return self.batch_predict(candidate_ids, vacancy_id)[:top_n]