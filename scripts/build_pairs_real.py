# -*- coding: utf-8 -*-
"""Собирает пары резюме×вакансия из данных trudvsem с псевдометками.

Стратегия: для каждого резюме — 5 вакансий:
- 1 из той же специализации (правдоподобная)
- 2 из того же региона (по нормализованному субъекту РФ)
- 2 случайных (негативы)

Выход: pairs.csv с ~556k строк.
"""

from __future__ import annotations

import argparse
import random
import re
from pathlib import Path
from typing import Dict, List

import pandas as pd

random.seed(42)


def _normalize_region(region: str) -> str:
    """Приводит 'Красноярский-край,-г-Лесосибирск' и 'Красноярский край' к общему виду."""
    if not region:
        return ""
    text = str(region).lower()
    text = re.sub(r"[-,]", " ", text)
    text = re.sub(r"\b(город|г|поселок|пос|село|с|деревня|д|район|р-н)\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(text.split()[:2])


def sample_resumes(path: Path, n: int) -> pd.DataFrame:
    print(f"[sample] беру {n:,} резюме ...")
    chunks = []
    total = 0
    for chunk in pd.read_csv(path, chunksize=200_000, usecols=[
        "candidate_id", "specialization", "region", "experience_years",
        "expected_salary", "education", "skills",
    ]):
        if total >= n:
            break
        take = min(len(chunk), n - total)
        chunks.append(chunk.sample(n=take, random_state=42))
        total += take
    return pd.concat(chunks, ignore_index=True)


def load_vacancies(path: Path) -> pd.DataFrame:
    print(f"[load] вакансии ...")
    return pd.read_csv(path, usecols=[
        "vacancy_id", "specialization", "region",
        "min_experience", "max_experience",
        "min_salary", "max_salary",
        "required_education", "required_skills",
    ])


def build_pairs(resumes: pd.DataFrame, vacancies: pd.DataFrame) -> pd.DataFrame:
    by_spec: Dict[str, List[int]] = {}
    by_region: Dict[str, List[int]] = {}
    for idx, row in vacancies.iterrows():
        spec = str(row["specialization"])
        region = _normalize_region(row["region"])
        by_spec.setdefault(spec, []).append(idx)
        by_region.setdefault(region, []).append(idx)

    all_vac = vacancies.index.tolist()
    pairs = []

    for _, r in resumes.iterrows():
        cand_id = r["candidate_id"]
        spec = str(r["specialization"])
        region = _normalize_region(r["region"])

        # 1. Правдоподобная (та же специализация)
        if by_spec.get(spec):
            v_idx = random.choice(by_spec[spec])
            pairs.append({"candidate_id": cand_id, "vacancy_id": vacancies.loc[v_idx, "vacancy_id"],
                          "pair_type": "same_spec"})

        # 2-3. По региону
        if by_region.get(region) and len(by_region[region]) >= 2:
            for _ in range(2):
                v_idx = random.choice(by_region[region])
                pairs.append({"candidate_id": cand_id, "vacancy_id": vacancies.loc[v_idx, "vacancy_id"],
                              "pair_type": "same_region"})

        # 4-5. Случайные
        for _ in range(2):
            v_idx = random.choice(all_vac)
            pairs.append({"candidate_id": cand_id, "vacancy_id": vacancies.loc[v_idx, "vacancy_id"],
                          "pair_type": "random"})

    return pd.DataFrame(pairs)


def attach_features(pairs: pd.DataFrame, resumes: pd.DataFrame, vacancies: pd.DataFrame) -> pd.DataFrame:
    r = resumes.set_index("candidate_id")
    v = vacancies.set_index("vacancy_id")
    out = pairs.copy()
    out = out.join(r, on="candidate_id", rsuffix="_cand")
    out = out.join(v, on="vacancy_id", rsuffix="_vac")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resumes", type=Path, default=Path("data/trudvsem/processed_v2/candidates.csv"))
    ap.add_argument("--vacancies", type=Path, default=Path("data/trudvsem/processed_v2/vacancies.csv"))
    ap.add_argument("--out", type=Path, default=Path("data/trudvsem/processed_v2/pairs.csv"))
    ap.add_argument("--n-resumes", type=int, default=200_000)
    args = ap.parse_args()

    resumes = sample_resumes(args.resumes, args.n_resumes)
    print(f"[sample] резюме: {len(resumes):,}")

    vacancies = load_vacancies(args.vacancies)
    print(f"[load] вакансий: {len(vacancies):,}")

    print("[pairs] генерирую ...")
    pairs = build_pairs(resumes, vacancies)
    print(f"[pairs] пар: {len(pairs):,}")
    print(f"[pairs] по типу:\n{pairs['pair_type'].value_counts()}")

    print("[join] присоединяю фичи ...")
    full = attach_features(pairs, resumes, vacancies)
    print(f"[join] итого: {len(full):,}")

    full.to_csv(args.out, index=False, encoding="utf-8")
    print(f"[saved] {args.out}")


if __name__ == "__main__":
    main()