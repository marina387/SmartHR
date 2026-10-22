# -*- coding: utf-8 -*-
"""Расчёт накопительной воронки найма по реальным рассмотрениям."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from src.config import FUNNEL_STAGES, FUNNEL_TERMINAL_STATUSES
from src.storage.candidate_stage_event_storage import CandidateStageEventStorage
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.file_storage import FileCandidateStorage


STAGE_LABELS = {
    "new": "Все кандидаты", "scored": "Прошли scoring", "recommended": "Рекомендованы",
    "in_review": "В работе HR", "interview": "Приглашены на интервью",
    "interview_completed": "Прошли интервью", "offer": "Получили оффер", "hired": "Наняты",
}


class FunnelService:
    def __init__(self, relations: CandidateVacancyStorage, events: CandidateStageEventStorage,
                 candidates: FileCandidateStorage) -> None:
        self.relations = relations
        self.events = events
        self.candidates = candidates

    @staticmethod
    def _in_period(value: str, date_from: str | None, date_to: str | None) -> bool:
        day = str(value or "")[:10]
        return (not date_from or day >= date_from) and (not date_to or day <= date_to)

    def _applications(self, vacancy_id: str | None, date_from: str | None, date_to: str | None) -> List[Dict[str, Any]]:
        applications = list(self.relations.list_all())
        linked = {(str(item.get("candidate_id")), str(item.get("vacancy_id"))) for item in applications}
        for candidate in self.candidates.list_candidates():
            candidate_id = str(candidate.get("id", ""))
            candidate_vacancy = str(candidate.get("vacancy_id", "VAC_001"))
            if not candidate_id or (candidate_id, candidate_vacancy) in linked:
                continue
            color = str(candidate.get("status", "yellow"))
            stage = "recommended" if color == "green" else "rejected" if color == "red" else "scored"
            applications.append({
                "id": f"legacy:{candidate_id}:{candidate_vacancy}", "candidate_id": candidate_id,
                "vacancy_id": candidate_vacancy, "status": stage, "total": candidate.get("total", 0),
                "created_at": candidate.get("timestamp", ""), "updated_at": candidate.get("timestamp", ""),
            })
        return [item for item in applications
                if (not vacancy_id or str(item.get("vacancy_id")) == vacancy_id)
                and self._in_period(str(item.get("created_at", "")), date_from, date_to)]

    def get_funnel(self, vacancy_id: str | None = None, date_from: str | None = None,
                   date_to: str | None = None, group_by: str = "applications") -> Dict[str, Any]:
        if group_by not in {"applications", "candidates"}:
            raise ValueError("group_by должен быть applications или candidates")
        for value in (date_from, date_to):
            if value:
                datetime.strptime(value, "%Y-%m-%d")
        if date_from and date_to and date_from > date_to:
            raise ValueError("Начальная дата не может быть позже конечной")
        applications = self._applications(vacancy_id, date_from, date_to)
        archived = {str(candidate['id']) for candidate in self.candidates.list_candidates() if candidate.get('lifecycle_status') == 'archived'}
        event_map: Dict[tuple[str, str], set[str]] = {}
        for event in self.events.list_all():
            if vacancy_id and str(event.get("vacancy_id")) != vacancy_id:
                continue
            key = (str(event.get("candidate_id")), str(event.get("vacancy_id")))
            event_map.setdefault(key, set()).add(str(event.get("to_stage")))

        achieved: Dict[str, set[str]] = {}
        outcome_entities = {status: set() for status in FUNNEL_TERMINAL_STATUSES}
        active_entities = set()
        for app in applications:
            candidate_id, app_vacancy = str(app.get("candidate_id")), str(app.get("vacancy_id"))
            entity = candidate_id if group_by == "candidates" else str(app.get("id") or f"{candidate_id}:{app_vacancy}")
            stages = achieved.setdefault(entity, {"new"})
            status = "archived" if candidate_id in archived else str(app.get("status", "new"))
            stages.update(event_map.get((candidate_id, app_vacancy), set()))
            if status in FUNNEL_STAGES:
                stages.update(FUNNEL_STAGES[:FUNNEL_STAGES.index(status) + 1])
            if status in outcome_entities:
                outcome_entities[status].add(entity)
            if status not in set(FUNNEL_TERMINAL_STATUSES) | {"hired"}:
                active_entities.add(entity)

        initial = len(achieved)
        rows = []
        previous = initial
        for stage in FUNNEL_STAGES:
            count = sum(stage in stages for stages in achieved.values())
            rows.append({
                "key": stage, "label": STAGE_LABELS[stage], "count": count,
                "dropped": max(0, previous - count),
                "conversion_from_previous": round(count / previous * 100, 1) if previous else 0,
                "conversion_from_initial": round(count / initial * 100, 1) if initial else 0,
            })
            previous = count
        outcomes = {status: len(entities) for status, entities in outcome_entities.items()}
        active = len(active_entities)
        hired = rows[-1]["count"] if rows else 0
        return {
            "group_by": group_by, "vacancy_id": vacancy_id, "date_from": date_from, "date_to": date_to,
            "initial_count": initial, "current_count": active, "hired_count": hired,
            "overall_conversion": round(hired / initial * 100, 1) if initial else 0,
            "stages": rows, "outcomes": outcomes,
        }
