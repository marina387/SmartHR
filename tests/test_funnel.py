"""Тесты истории этапов и накопительной воронки."""

from pathlib import Path

from src.services.candidate_stage_service import CandidateStageService
from src.services.funnel_service import FunnelService
from src.storage.candidate_stage_event_storage import CandidateStageEventStorage
from src.storage.candidate_vacancy_storage import CandidateVacancyStorage
from src.storage.file_storage import FileCandidateStorage


def make_services(tmp_path: Path):
    relations = CandidateVacancyStorage(tmp_path / "relations.json")
    events = CandidateStageEventStorage(tmp_path / "events.json")
    candidates = FileCandidateStorage(tmp_path / "candidates.json")
    return CandidateStageService(relations, events), FunnelService(relations, events, candidates), relations, events


def test_stage_history_and_cumulative_funnel(tmp_path: Path) -> None:
    stages, funnel, _, events = make_services(tmp_path)
    stages.transition("CV_1", "VAC_1", "new")
    stages.transition("CV_1", "VAC_1", "scored")
    stages.transition("CV_1", "VAC_1", "recommended")
    stages.transition("CV_1", "VAC_1", "in_review")
    stages.transition("CV_1", "VAC_1", "interview")
    result = funnel.get_funnel(group_by="applications")
    counts = {item["key"]: item["count"] for item in result["stages"]}
    assert counts["new"] == 1
    assert counts["interview"] == 1
    assert counts["offer"] == 0
    assert len(events.list_all()) == 5


def test_unique_candidates_do_not_double_count_transfers(tmp_path: Path) -> None:
    stages, funnel, _, _ = make_services(tmp_path)
    stages.transition("CV_1", "VAC_1", "recommended")
    stages.transition("CV_1", "VAC_1", "transferred")
    stages.transition("CV_1", "VAC_2", "in_review")
    applications = funnel.get_funnel(group_by="applications")
    candidates = funnel.get_funnel(group_by="candidates")
    assert applications["initial_count"] == 2
    assert candidates["initial_count"] == 1
    assert applications["outcomes"]["transferred"] == 1


def test_funnel_filters_by_vacancy(tmp_path: Path) -> None:
    stages, funnel, _, _ = make_services(tmp_path)
    stages.transition("CV_1", "VAC_1", "recommended")
    stages.transition("CV_2", "VAC_2", "recommended")
    result = funnel.get_funnel(vacancy_id="VAC_1")
    assert result["initial_count"] == 1
