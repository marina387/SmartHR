# -*- coding: utf-8 -*-
"""Обучение matching_model_real.pkl v2 — БЕЗ тавтологии в фичах.

Метка = exp_within & salary_ratio<=1.3 & edu_match & spec_match
Фичи = СЫРЫЕ значения (experience_years, min_experience, max_experience,
        expected_salary, max_salary, cand_edu_idx, vac_edu_idx,
        same_spec, skills_match, cand_skills_count, vac_skills_count)

Модель должна сама научиться правилу «exp >= min AND exp <= max»,
а не получить его в готовом виде.
"""

from __future__ import annotations
import argparse
import json
import re
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (accuracy_score, classification_report, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split

EDU_LEVELS = ["none", "high_school", "associate", "bachelor", "master", "phd"]


def edu_idx(val):
    try:
        return EDU_LEVELS.index(str(val))
    except ValueError:
        return 0


def split_skills(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return set()
    text = str(value).strip()
    if not text or text in {"[]", "{}", "None", "nan"}:
        return set()
    return {s.strip().strip("'\"").lower() for s in re.split(r"[,\[\]]", text) if s.strip()}


def build_labels(df: pd.DataFrame) -> np.ndarray:
    """Метка считается из СЫРЫХ значений — ровно то же правило, что в v1."""
    exp = df["experience_years"].clip(0, 60).fillna(0)
    min_e = df["min_experience"].clip(0, 60).fillna(0)
    max_e = df["max_experience"].clip(0, 60).fillna(0)
    exp_within = ((exp >= min_e) & (exp <= max_e)).astype(int)

    exp_sal = df["expected_salary"].fillna(0)
    max_sal = df["max_salary"].fillna(0)
    salary_ratio = np.where(max_sal > 0, exp_sal / max_sal, 1.0)
    salary_ok = (salary_ratio <= 1.3).astype(int)

    cand_edu = df["education"].apply(edu_idx).values
    vac_edu = df["required_education"].apply(edu_idx).values
    edu_ok = (cand_edu >= vac_edu).astype(int)

    spec_ok = (df["specialization"].astype(str) == df["specialization_vac"].astype(str)).astype(int)

    return (exp_within & salary_ok & edu_ok & spec_ok).astype(int).values


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Фичи — СЫРЫЕ. Никаких производных exp_within / salary_ratio / edu_match."""
    cand_sk = df["skills"].apply(split_skills)
    vac_sk = df["required_skills"].apply(split_skills)
    skills_match = cand_sk.combine(vac_sk, lambda a, b: len(a & b) / max(len(b), 1)).values

    return pd.DataFrame({
        "experience_years": df["experience_years"].clip(0, 60).fillna(0),
        "min_experience": df["min_experience"].clip(0, 60).fillna(0),
        "max_experience": df["max_experience"].clip(0, 60).fillna(0),
        "expected_salary": df["expected_salary"].fillna(0),
        "max_salary": df["max_salary"].fillna(0),
        "cand_edu_idx": df["education"].apply(edu_idx),
        "vac_edu_idx": df["required_education"].apply(edu_idx),
        "same_spec": (df["specialization"].astype(str) == df["specialization_vac"].astype(str)).astype(int),
        "skills_match": skills_match,
        "cand_skills_count": cand_sk.apply(len).values,
        "vac_skills_count": vac_sk.apply(len).values,
    })


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=Path, default=Path("data/trudvsem/processed_v2/pairs.csv"))
    ap.add_argument("--out-model", type=Path, default=Path("models/matching_model_real.pkl"))
    ap.add_argument("--out-meta", type=Path, default=Path("models/model_metadata_real.json"))
    args = ap.parse_args()

    print("[load] pairs ...")
    df = pd.read_csv(args.pairs)
    print(f"[load] строк: {len(df):,}")

    print("[labels] ...")
    y = build_labels(df)
    print(f"[labels] позитивов: {y.sum():,} ({y.mean()*100:.1f}%)")

    print("[features] ...")
    X = build_features(df)
    print(X.describe())

    # Split по candidate_id — не по парам. Иначе утечка.
    cand_ids = df["candidate_id"].unique()
    train_ids, test_ids = train_test_split(cand_ids, test_size=0.2, random_state=42)
    train_mask = df["candidate_id"].isin(train_ids).values
    test_mask = df["candidate_id"].isin(test_ids).values

    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]
    print(f"[split] train: {len(X_train):,} (pos {y_train.sum()}), test: {len(X_test):,} (pos {y_test.sum()})")

    print("[train] GradientBoosting ...")
    model = GradientBoostingClassifier(n_estimators=300, max_depth=5, learning_rate=0.05, random_state=42)
    model.fit(X_train, y_train)

    print("[eval] ...")
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

    # Feature importance
    print("\n[importance]")
    for name, imp in sorted(zip(X.columns, model.feature_importances_), key=lambda x: -x[1]):
        print(f"  {name:25s} {imp:.4f}")

    args.out_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, args.out_model)
    metadata = {
        "features": X.columns.tolist(),
        "metrics": metrics,
        "feature_importance": dict(zip(X.columns, model.feature_importances_.tolist())),
        "training_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "positive_rate_train": float(y_train.mean()),
        "trained_on": "trudvsem_real",
        "label_rule": "exp_within & salary_ratio<=1.3 & edu_match & spec_match",
        "note": "Фичи — сырые, БЕЗ тавтологии. Модель восстанавливает правило из данных.",
    }
    args.out_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[save] {args.out_model}")


if __name__ == "__main__":
    main()