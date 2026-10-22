# scripts/filter_trudvsem_resumes.py
"""Фильтрует большой cv.csv чанками, не загружая всё в память."""

import argparse
from pathlib import Path
import pandas as pd

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, default=Path("data/trudvsem/cv.csv"))
    ap.add_argument("--output", type=Path, default=Path("data/trudvsem/resumes_filtered.csv"))
    ap.add_argument("--regions", nargs="+", default=["Москва", "Санкт-Петербург"])
    ap.add_argument("--chunk", type=int, default=100_000)
    ap.add_argument("--max-rows", type=int, default=500_000)
    args = ap.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    total_read = 0
    kept = 0
    first = True

    for chunk in pd.read_csv(args.input, chunksize=args.chunk, low_memory=False):
        total_read += len(chunk)
        # Оставляем только строки с непустыми навыками и нужным регионом.
        mask = chunk.get("skills", pd.Series([""] * len(chunk))).notna()
        for region in args.regions:
            if "region" in chunk.columns:
                mask &= chunk["region"].astype(str).str.contains(region, case=False, na=False)
        filtered = chunk[mask]
        if filtered.empty:
            continue
        filtered.to_csv(args.output, mode="a", header=first, index=False, encoding="utf-8")
        first = False
        kept += len(filtered)
        print(f"прочитано: {total_read:,}, оставлено: {kept:,}")
        if kept >= args.max_rows:
            print(f"достигнут лимит {args.max_rows}, останавливаемся")
            break

    print(f"\nГотово: {kept:,} строк в {args.output}")

if __name__ == "__main__":
    main()