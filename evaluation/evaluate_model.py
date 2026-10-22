"""Воспроизводимая оценка готовой базовой модели без переобучения."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import joblib
import matplotlib
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, average_precision_score, classification_report,
    confusion_matrix, f1_score, precision_recall_curve, precision_score,
    recall_score, roc_auc_score, roc_curve,
)
from sklearn.model_selection import train_test_split

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "evaluation" / "results"
FEATURES = [
    "skills_match", "experience_years", "exp_within_range", "salary_ratio",
    "spec_match", "edu_match", "eng_match", "has_portfolio",
    "cand_skills_count", "vac_skills_count",
]
EDUCATION = ["none", "bachelor", "master", "phd"]
ENGLISH = ["A1", "A2", "B1", "B2", "C1", "C2"]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category_index(value: object, categories: list[str]) -> int:
    return categories.index(value) if value in categories else 0


def skills_match(candidate: object, vacancy: object) -> float:
    candidate_set = set(str(candidate).split(", "))
    vacancy_set = set(str(vacancy).split(", "))
    return len(candidate_set & vacancy_set) / len(vacancy_set) if vacancy_set else 0.0


def prepare_dataset() -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    matches = pd.read_csv(ROOT / "data" / "matches.csv")
    candidates = pd.read_csv(ROOT / "data" / "candidates.csv")
    vacancies = pd.read_csv(ROOT / "data" / "vacancies.csv")
    merged = matches.merge(candidates, on="candidate_id").merge(vacancies, on="vacancy_id")
    features = pd.DataFrame(index=merged.index)
    features["skills_match"] = merged.apply(lambda row: skills_match(row["skills"], row["required_skills"]), axis=1)
    features["experience_years"] = merged["experience_years"]
    features["exp_within_range"] = (
        (merged["experience_years"] >= merged["min_experience"])
        & (merged["experience_years"] <= merged["max_experience"])
    ).astype(int)
    expected_salary_rubles = merged["expected_salary"] * 1000
    features["salary_ratio"] = expected_salary_rubles / merged["max_salary"]
    features["spec_match"] = (merged["specialization_x"] == merged["specialization_y"]).astype(int)
    features["edu_match"] = (
        merged["education"].map(lambda value: category_index(value, EDUCATION))
        >= merged["required_education"].map(lambda value: category_index(value, EDUCATION))
    ).astype(int)
    features["eng_match"] = (
        merged["english_level"].map(lambda value: category_index(value, ENGLISH))
        >= merged["english_required"].map(lambda value: category_index(value, ENGLISH))
    ).astype(int)
    features["has_portfolio"] = merged["has_portfolio"]
    features["cand_skills_count"] = merged["skills"].str.count(",") + 1
    features["vac_skills_count"] = merged["required_skills"].str.count(",") + 1
    return features[FEATURES], merged["decision"].astype(int), merged


def save_confusion_matrix(matrix: np.ndarray) -> None:
    fig, axis = plt.subplots(figsize=(6, 5))
    image = axis.imshow(matrix, cmap="Blues")
    axis.set(xticks=[0, 1], yticks=[0, 1], xticklabels=["Отказ", "Приглашение"], yticklabels=["Отказ", "Приглашение"])
    axis.set_xlabel("Предсказание")
    axis.set_ylabel("Фактический класс")
    axis.set_title("Матрица ошибок, порог 0.5")
    for row in range(2):
        for column in range(2):
            axis.text(column, row, str(matrix[row, column]), ha="center", va="center", color="white" if matrix[row, column] > matrix.max() / 2 else "black")
    fig.colorbar(image, ax=axis)
    fig.tight_layout()
    fig.savefig(RESULTS / "confusion_matrix.png", dpi=180)
    plt.close(fig)


def save_curves(y_true: pd.Series, probabilities: np.ndarray) -> None:
    fpr, tpr, _ = roc_curve(y_true, probabilities)
    precision, recall, _ = precision_recall_curve(y_true, probabilities)
    fig, axis = plt.subplots(figsize=(6, 5))
    axis.plot(fpr, tpr, label=f"ROC-AUC = {roc_auc_score(y_true, probabilities):.6f}")
    axis.plot([0, 1], [0, 1], "--", color="gray")
    axis.set(xlabel="False Positive Rate", ylabel="True Positive Rate", title="ROC-кривая")
    axis.legend()
    axis.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(RESULTS / "roc_curve.png", dpi=180)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(6, 5))
    axis.plot(recall, precision, label=f"PR-AUC = {average_precision_score(y_true, probabilities):.6f}")
    axis.set(xlabel="Recall", ylabel="Precision", title="Precision–Recall кривая")
    axis.legend()
    axis.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(RESULTS / "precision_recall_curve.png", dpi=180)
    plt.close(fig)


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    model_path = ROOT / "models" / "matching_model.pkl"
    metadata_path = ROOT / "models" / "model_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata["features"] != FEATURES:
        raise RuntimeError("Порядок признаков не совпадает с метаданными модели")

    features, target, merged = prepare_dataset()
    indices = np.arange(len(features))
    _, test_indices = train_test_split(indices, test_size=0.2, random_state=42, stratify=target)
    x_test = features.iloc[test_indices]
    y_test = target.iloc[test_indices]
    model = joblib.load(model_path)
    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)

    metrics = {
        "model_file": str(model_path.relative_to(ROOT)),
        "model_sha256": file_hash(model_path),
        "dataset_sha256": {name: file_hash(ROOT / "data" / name) for name in ("candidates.csv", "vacancies.csv", "matches.csv")},
        "full_pairs": int(len(features)), "test_pairs": int(len(x_test)),
        "positive_test_pairs": int(y_test.sum()), "negative_test_pairs": int((1 - y_test).sum()),
        "split": {"test_size": 0.2, "random_state": 42, "stratify": "decision"},
        "threshold": 0.5,
        "accuracy": float(accuracy_score(y_test, predictions)),
        "precision": float(precision_score(y_test, predictions, zero_division=0)),
        "recall": float(recall_score(y_test, predictions, zero_division=0)),
        "f1": float(f1_score(y_test, predictions, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, probabilities)),
        "pr_auc": float(average_precision_score(y_test, probabilities)),
        "metadata_roc_auc": float(metadata["roc_auc"]),
    }
    metrics["roc_auc_difference"] = abs(metrics["roc_auc"] - metrics["metadata_roc_auc"])
    matrix = confusion_matrix(y_test, predictions)
    metrics["confusion_matrix"] = matrix.tolist()
    metrics["classification_report"] = classification_report(y_test, predictions, output_dict=True, zero_division=0)
    (RESULTS / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    prediction_rows = merged.iloc[test_indices][["match_id", "candidate_id", "vacancy_id", "decision"]].copy()
    prediction_rows["model_probability"] = probabilities
    prediction_rows["prediction_0_5"] = predictions
    prediction_rows["correct"] = prediction_rows["decision"].to_numpy() == predictions
    prediction_rows.to_csv(RESULTS / "predictions.csv", index=False)

    threshold_rows = []
    for threshold in np.arange(0.1, 0.91, 0.05):
        threshold_predictions = (probabilities >= threshold).astype(int)
        threshold_rows.append({
            "threshold": round(float(threshold), 2),
            "precision": precision_score(y_test, threshold_predictions, zero_division=0),
            "recall": recall_score(y_test, threshold_predictions, zero_division=0),
            "f1": f1_score(y_test, threshold_predictions, zero_division=0),
            "accuracy": accuracy_score(y_test, threshold_predictions),
            "recommended": int(threshold_predictions.sum()),
        })
    thresholds = pd.DataFrame(threshold_rows)
    thresholds.to_csv(RESULTS / "threshold_metrics.csv", index=False)
    best = thresholds.loc[thresholds["f1"].idxmax()].to_dict()

    save_confusion_matrix(matrix)
    save_curves(y_test, probabilities)
    report = f"""# Отчёт об оценке базовой модели

## Методика

Готовая модель `models/matching_model.pkl` загружена с диска и **не переобучалась**.
Признаки восстановлены из `candidates.csv`, `vacancies.csv` и `matches.csv` тем же способом,
что и в `scripts/train_model.py`. Тестовая часть восстановлена параметрами
`test_size=0.2`, `random_state=42`, `stratify=decision`.

## Выборка

- Полный набор: {metrics['full_pairs']} пар.
- Тестовая часть: {metrics['test_pairs']} пар.
- Положительный класс: {metrics['positive_test_pairs']}.
- Отрицательный класс: {metrics['negative_test_pairs']}.

## Метрики при пороге 0.5

| Метрика | Значение |
|---|---:|
| Accuracy | {metrics['accuracy']:.6f} |
| Precision | {metrics['precision']:.6f} |
| Recall | {metrics['recall']:.6f} |
| F1 | {metrics['f1']:.6f} |
| ROC-AUC | {metrics['roc_auc']:.12f} |
| PR-AUC | {metrics['pr_auc']:.12f} |

Матрица ошибок: TN={matrix[0,0]}, FP={matrix[0,1]}, FN={matrix[1,0]}, TP={matrix[1,1]}.

ROC-AUC в метаданных: `{metrics['metadata_roc_auc']:.12f}`. Разница: `{metrics['roc_auc_difference']:.12g}`.
Значения очень близки, но не идентичны. Это подтверждает совместимость модели с данным
набором признаков и делает обучение на этих CSV наиболее вероятным сценарием. Однако без
исходного журнала запуска точное происхождение артефакта нельзя доказать математически.

Лучший проверенный порог по F1: `{best['threshold']:.2f}` (F1={best['f1']:.6f},
precision={best['precision']:.6f}, recall={best['recall']:.6f}).

## Ограничения

- Это восстановление исходной тестовой части, а не новая внешняя выборка.
- ROC-AUC отличается от метаданных на {metrics['roc_auc_difference']:.12f}; вероятная причина —
  модель или метаданные были сохранены после другого запуска либо промежуточной версии данных.
- Датасет имеет синтетический и почти детерминированный характер, поэтому показатели близки к 1.
- Метрики подтверждают воспроизводимость сохранённой модели, но не гарантируют такое же качество на реальных резюме.
- Итоговый взвешенный балл приложения не оценивался: здесь проверяется только базовая ML-модель.
"""
    (RESULTS / "evaluation_report.md").write_text(report, encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
