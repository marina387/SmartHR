# -*- coding: utf-8 -*-
"""Обучение модели на РЕАЛЬНЫХ метках рекрутеров.

Источники:
    data/trudvsem/processed_v2/real_labels.csv  — решения рекрутеров (decision=0/1)
    data/trudvsem/processed_v2/pairs.csv        — фичи для пар

Выход:
    models/matching_model_real_labels.pkl
    models/model_metadata_real_labels.json

Запуск:
    python scripts/train_on_real_labels.py
    python scripts/train_on_real_labels.py --min-labels 50
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix,
    f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split

from src.matching_service import MatchingService


def load_real_labels(path: Path) -> pd.DataFrame:
    """Читает real_labels.csv, нормализует decision и features."""
    if not path.exists():
        raise FileNotFoundError(f"Нет файла меток: {path}")
    df = pd.read_csv(path)
    if df.empty:
        raise ValueError("real_labels.csv пустой — нажмите кнопки в UI.")

    required = {"candidate_id", "vacancy_id", "decision"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"В real_labels.csv нет колонок: {missing}")

    df["decision"] = pd.to_numeric(df["decision"], errors="coerce")
    df = df.dropna(subset=["decision"])
    df = df[df["decision"].isin([0, 1])]
    df["decision"] = df["decision"].astype(int)

    # Дедуп: если один и тот же кандидат×вакансия нажали несколько раз — берём последнее.
    if "created_at" in df.columns:
        df = df.sort_values("created_at").drop_duplicates(
            subset=["candidate_id", "vacancy_id"], keep="last"
        )
    else:
        df = df.drop_duplicates(subset=["candidate_id", "vacancy_id"], keep="last")

    return df.reset_index(drop=True)


def attach_features_from_pairs(labels: pd.DataFrame, pairs_path: Path) -> pd.DataFrame:
    """Джойнит фичи из pairs.csv по (candidate_id, vacancy_id)."""
    if not pairs_path.exists():
        print(f"[warn] pairs.csv не найден: {pairs_path}")
        return labels.assign(_has_features=False)

    print(f"[pairs] читаю {pairs_path} ...")
    cols = [
        "candidate_id", "vacancy_id",
        "experience_years", "min_experience", "max_experience",
        "expected_salary", "max_salary",
        "education", "required_education",
        "specialization", "specialization_vac",
        "skills", "required_skills",
    ]
    pairs = pd.read_csv(pairs_path, usecols=[c for c in cols if c in pd.read_csv(pairs_path, nrows=0).columns])
    print(f"[pairs] строк: {len(pairs):,}")

    merged = labels.merge(
        pairs.drop_duplicates(subset=["candidate_id", "vacancy_id"]),
        on=["candidate_id", "vacancy_id"],
        how="left",
        suffixes=("", "_pair"),
    )
    merged["_has_features"] = merged["experience_years"].notna()
    return merged


def compute_features_for_missing(df: pd.DataFrame, svc: MatchingService) -> pd.DataFrame:
    """Для пар без фич из pairs.csv считает фичи «на лету» через MatchingService."""
    result = df.copy()
    if result["_has_features"].all():
        return result

    missing = result[~result["_has_features"]].copy()
    print(f"[compute] считаю фичи на лету для {len(missing):,} пар ...")

    rows = []
    for _, row in missing.iterrows():
        cand = {
            "experience_years": row.get("experience_years", 0),
            "skills": row.get("skills", ""),
            "education": row.get("education", ""),
            "specialization": row.get("specialization", ""),
            "expected_salary": row.get("expected_salary", 0),
        }
        vac = {
            "min_experience": row.get("min_experience", 0),
            "max_experience": row.get("max_experience", 0),
            "required_skills": row.get("required_skills", ""),
            "max_salary": row.get("max_salary", 0),
            "required_education": row.get("required_education", ""),
            "specialization": row.get("specialization_vac", ""),
        }
        try:
            feats = svc.prepare_features(cand, vac).iloc[0].to_dict()
        except Exception:
            feats = {}
        rows.append(feats)

    feats_df = pd.DataFrame(rows, index=missing.index)
    for col in svc.feature_names:
        if col not in result.columns:
            result[col] = np.nan
        result.loc[missing.index, col] = feats_df[col] if col in feats_df.columns else np.nan
    result.loc[missing.index, "_has_features"] = feats_df.notna().all(axis=1).values
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", type=Path,
                    default=ROOT / "data" / "trudvsem" / "processed_v2" / "real_labels.csv")
    ap.add_argument("--pairs", type=Path,
                    default=ROOT / "data" / "trudvsem" / "processed_v2" / "pairs.csv")
    ap.add_argument("--out-model", type=Path,
                    default=ROOT / "models" / "matching_model_real_labels.pkl")
    ap.add_argument("--out-meta", type=Path,
                    default=ROOT / "models" / "model_metadata_real_labels.json")
    ap.add_argument("--min-labels", type=int, default=30,
                    help="Минимум меток для обучения (по умолчанию 30)")
    ap.add_argument("--test-size", type=float, default=0.25,
                    help="Доля теста (по умолчанию 0.25)")
    args = ap.parse_args()

    print(f"[labels] читаю {args.labels} ...")
    labels = load_real_labels(args.labels)
    print(f"[labels] всего: {len(labels):,}")
    print(f"[labels] 'подходит' (1): {(labels['decision'] == 1).sum():,}")
    print(f"[labels] 'не подходит' (0): {(labels['decision'] == 0).sum():,}")

    if len(labels) < args.min_labels:
        print(f"\n[WARN] меток {len(labels):,} < {args.min_labels}. "
              f"Модель обучится, но качество будет нестабильным. "
              f"Продолжайте собирать фидбек.")

    if labels["decision"].nunique() < 2:
        raise SystemExit("[ERROR] В метках только один класс. Нужны и 0, и 1.")

    # Джойн с pairs.csv (фичи из обучения)
    merged = attach_features_from_pairs(labels, args.pairs)

    # Для пар, которых нет в pairs.csv — считаем фичи через MatchingService
    svc = MatchingService()
    merged = compute_features_for_missing(merged, svc)

    # Оставляем только строки с полными фичами
    before = len(merged)
    merged = merged[merged["_has_features"]].copy()
    print(f"[features] после фильтра: {len(merged):,} из {before:,} "
          f"(отброшено {before - len(merged):,} без фич)")

    if len(merged) < 5:
        raise SystemExit("[ERROR] Слишком мало пар с фичами для обучения.")

    # Split по candidate_id — без утечки
    cand_ids = merged["candidate_id"].unique()
    if len(cand_ids) < 3:
        raise SystemExit("[ERROR] Слишком мало уникальных кандидатов.")

    train_ids, test_ids = train_test_split(
        cand_ids, test_size=args.test_size, random_state=42
    )
    train_mask = merged["candidate_id"].isin(train_ids).values
    test_mask = merged["candidate_id"].isin(test_ids).values

    X = merged[svc.feature_names].fillna(0).values
    y = merged["decision"].values
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]

    print(f"\n[split] train: {len(X_train):,} (pos {y_train.sum()}), "
          f"test: {len(X_test):,} (pos {y_test.sum()})")

    if y_train.sum() == 0 or y_test.sum() == 0:
        print("[WARN] В train или test нет позитивов. Метрики будут нестабильными.")

    print("\n[train] GradientBoosting на реальных метках ...")
    model = GradientBoostingClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42
    )
    model.fit(X_train, y_train)

    print("[eval] ...")
    if len(X_test) > 0 and y_test.sum() > 0 and (y_test == 0).sum() > 0:
        pred_proba = model.predict_proba(X_test)[:, 1]
        pred = (pred_proba >= 0.5).astype(int)
        metrics = {
            "roc_auc": float(roc_auc_score(y_test, pred_proba)),
            "accuracy": float(accuracy_score(y_test, pred)),
            "precision": float(precision_score(y_test, pred, zero_division=0)),
            "recall": float(recall_score(y_test, pred, zero_division=0)),
            "f1": float(f1_score(y_test, pred, zero_division=0)),
        }
        print(json.dumps(metrics, indent=2))
        print(classification_report(y_test, pred, digits=4))
        print("confusion_matrix:", confusion_matrix(y_test, pred).tolist())
    else:
        metrics = {"note": "test set слишком мал для метрик"}
        print("[WARN] test set слишком мал — метрики не считаются.")

    print("\n[importance]")
    for name, imp in sorted(zip(svc.feature_names, model.feature_importances_), key=lambda x: -x[1]):
        print(f"  {name:25s} {imp:.4f}")

    args.out_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, args.out_model)
    metadata = {
        "features": svc.feature_names,
        "metrics": metrics,
        "training_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "unique_candidates": int(len(cand_ids)),
        "label_counts": {
            "total": int(len(merged)),
            "positive": int(y.sum()),
            "negative": int((y == 0).sum()),
        },
        "feature_importance": dict(zip(svc.feature_names, model.feature_importances_.tolist())),
        "trained_on": "real_labels_from_recruiters",
        "label_source": str(args.labels),
        "features_source": str(args.pairs),
        "note": "Модель обучена на реальных решениях рекрутеров (decision 0/1 из UI). "
                "ROC-AUC < 1.0 — это нормально: реальные решения шумные.",
    }
    args.out_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[save] {args.out_model}")
    print(f"[save] {args.out_meta}")


if __name__ == "__main__":
    main()