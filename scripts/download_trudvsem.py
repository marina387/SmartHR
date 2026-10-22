# scripts/download_trudvsem.py
"""Скачивает вакансии с opendata.trudvsem.ru (открытый API, без авторизации)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

API = "http://opendata.trudvsem.ru/api/v1/vacancies"
REGION_API = "http://opendata.trudvsem.ru/api/v1/vacancies/region/{region}"


def fetch_page(url: str, retries: int = 3, timeout: int = 30) -> dict:
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            print(f"[retry {attempt + 1}/{retries}] {exc}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Не удалось скачать: {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/trudvsem/vacancies"))
    ap.add_argument("--region", type=str, default=None, help="Код региона, напр. 77 (Москва)")
    ap.add_argument("--limit", type=int, default=100, help="Записей на страницу (макс 100)")
    ap.add_argument("--pages", type=int, default=50, help="Сколько страниц скачать")
    ap.add_argument("--sleep", type=float, default=0.5, help="Пауза между запросами, сек")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    base = REGION_API.format(region=args.region) if args.region else API

    total_saved = 0
    for page in range(args.pages):
        offset = page * args.limit
        url = f"{base}?offset={offset}&limit={args.limit}"
        print(f"[{page + 1}/{args.pages}] {url}")
        data = fetch_page(url)
        meta = data.get("meta", {})
        items = data.get("results", {}).get("vacancies", []) or []
        if not items:
            print("  пусто, останавливаемся")
            break
        path = args.out / f"page_{page:04d}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        total_saved += len(items)
        print(f"  сохранено {len(items)}, всего: {total_saved} (из {meta.get('total')})")
        time.sleep(args.sleep)

    print(f"\nГотово: {total_saved} вакансий в {args.out}")


if __name__ == "__main__":
    main()