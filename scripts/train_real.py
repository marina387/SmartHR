# -*- coding: utf-8 -*-
"""Обучение matching_model_real.pkl на реальных данных trudvsem."""
from __future__ import annotations
import argparse, json, re
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


def build_features(df):
    exp = df["experience_years"].clip(0, 60).fillna(0)
    min_e = df["min_experience"].clip(0, 60).fillna(0)
    max_e = df["max_experience"].clip(0, 60).fillna(0)
    exp_within = ((exp >= min_e) & (exp <= max_e)).astype(float)

    exp_sal = df["expected_salary"].fillna(0)
    max_sal = df["max_salary"].fillna(0)
    salary_ratio = np.where(max_sal > 0, exp_sal / max_sal, 1.0)
    salary_ratio = np.clip(salary_ratio, 0, 5)

    cand_edu = df["education"].apply(edu_idx).values
    vac_edu = df["required_education"].apply(edu_idx).values
    edu_match = (cand_edu >= vac_edu).astype(float)

    spec_match = (df["specialization"].astype(str) == df["specialization_vac"].astype(str)).astype(float)

    cand_sk = df["skills"].apply(split_skills)
    vac_sk = df["required_skills"].apply(split_skills)
    skills_match = cand_sk.combine(vac_sk, lambda a, b: len(a & b) / max(len(b), 1)).values
    cand_skills_count = cand_sk.apply(len).values
    vac_skills_count = vac_sk.apply(len).values

    return pd.DataFrame({
        "experience_years": exp,
        "exp_within_range": exp_within,
        "salary_ratio": salary_ratio,
        "edu_match": edu_match,
        "spec_match": spec_match,
        "skills_match": skills_match,
        "cand_skills_count": cand_skills_count,
        "vac_skills_count": vac_skills_count,
    })


def build_labels(X):
    return (
        (X["exp_within_range"] == 1)
        & (X["salary_ratio"] <= 1.3)
        & (X["edu_match"] == 1)
        & (X["spec_match"] == 1)
    ).astype(int).values


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=Path, default=Path("data/trudvsem/processed_v2/pairs.csv"))
    ap.add_argument("--out-model", type=Path, default=Path("models/matching_model_real.pkl"))
    ap.add_argument("--out-meta", type=Path, default=Path("models/model_metadata_real.json"))
    args = ap.parse_args()

    print("[load] pairs ...")
    df = pd.read_csv(args.pairs)
    print(f"[load] строк: {len(df):,}")

    print("[features] ...")
    X = build_features(df)
    y = build_labels(X)
    print(f"[labels] позитивов: {y.sum():,} ({y.mean()*100:.1f}%)")

    cand_ids = df["candidate_id"].unique()
    train_ids, test_ids = train_test_split(cand_ids, test_size=0.2, random_state=42)
    train_mask = df["candidate_id"].isin(train_ids)
    test_mask = df["candidate_id"].isin(test_ids)
    X_train, y_train = X[train_mask], y[train_mask]
    X_test, y_test = X[test_mask], y[test_mask]
    print(f"[split] train: {len(X_train):,} (pos {y_train.sum()}), test: {len(X_test):,} (pos {y_test.sum()})")

    print("[train] ...")
    model = GradientBoostingClassifier(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42)
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

    args.out_model.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, args.out_model)
    metadata = {
        "features": X.columns.tolist(),
        "metrics": metrics,
        "training_rows": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "positive_rate_train": float(y_train.mean()),
        "trained_on": "trudvsem_real",
        "label_rule": "exp_within_range & salary_ratio<=1.3 & edu_match & spec_match",
    }
    args.out_meta.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[save] {args.out_model}, {args.out_meta}")


if __name__ == "__main__":
    main()