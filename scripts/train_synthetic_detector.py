# -*- coding: utf-8 -*-
"""Обучает бинарный классификатор real vs synthetic на данных data/chat/.

Устойчив к:
- разным схемам jsonl (text/content/message/messages/resume_text/summary);
- кириллице (явный token_pattern);
- пустым документам (пропускаются до fit).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _flatten_messages(value: Any) -> str:
    """messages: [{role, content}, ...] -> 'role: content\n'."""
    if not isinstance(value, list):
        return ""
    parts = []
    for m in value:
        if isinstance(m, dict):
            role = str(m.get("role") or "")
            content = str(m.get("content") or m.get("text") or "")
            if content.strip():
                parts.append(f"{role}: {content}" if role else content)
        elif isinstance(m, str):
            parts.append(m)
    return "\n".join(parts)


def record_text(rec: Dict[str, Any]) -> str:
    """Пытается вытащить текст из любой схемы, которая встречается в data/chat/."""
    # 1. Прямые строковые поля
    for key in ("text", "content", "resume_text", "summary", "answer", "prompt", "message"):
        value = rec.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    # 2. messages (chat format)
    text = _flatten_messages(rec.get("messages"))
    if text.strip():
        return text
    # 3. Поля-кандидаты: resume/description/requirements
    for key in ("resume", "description", "requirements", "skills", "title"):
        value = rec.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            joined = " ".join(str(v) for v in value if str(v).strip())
            if joined:
                return joined
    # 4. Склеиваем все строковые значения — грубо, но не теряем данные
    return " ".join(str(v) for v in rec.values() if isinstance(v, str) and v.strip())


def build_corpus(real_dir: Path, synthetic_dir: Path):
    X: List[str] = []
    y: List[int] = []
    sources: List[str] = []

    for p in sorted(real_dir.glob("*.jsonl")):
        rows = _read_jsonl(p)
        for r in rows:
            t = record_text(r)
            if t:
                X.append(t); y.append(1); sources.append(f"real:{p.name}")
    for name in ("train.jsonl", "synthetic_chat.jsonl", "synthetic_rag.jsonl"):
        p = synthetic_dir / name
        if not p.exists():
            continue
        rows = _read_jsonl(p)
        for r in rows:
            t = record_text(r)
            if t:
                X.append(t); y.append(0); sources.append(f"synthetic:{p.name}")
    return X, y, sources


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--real-dir", type=Path, default=Path("data/chat/collected"))
    ap.add_argument("--synthetic-dir", type=Path, default=Path("data/chat/synthetic"))
    ap.add_argument("--out", type=Path, default=Path("models/synthetic_detector.pkl"))
    ap.add_argument("--min-doc-chars", type=int, default=15,
                    help="Пропускать документы короче N символов")
    args = ap.parse_args()

    X, y, sources = build_corpus(args.real_dir, args.synthetic_dir)
    if not X:
        raise SystemExit("Не удалось извлечь ни одного непустого текста")

    # Отбрасываем слишком короткие документы — они не несут сигнала.
    filtered = [(t, label, src) for t, label, src in zip(X, y, sources) if len(t) >= args.min_doc_chars]
    X = [t for t, _, _ in filtered]
    y = [label for _, label, _ in filtered]
    sources = [src for _, _, src in filtered]

    print(f"real={sum(y)}, synthetic={len(y) - sum(y)}, total={len(y)}")
    print(f"пример real: {repr(next(t for t, l in zip(X, y) if l == 1)[:160])}")
    print(f"пример synthetic: {repr(next(t for t, l in zip(X, y) if l == 0)[:160])}")

    if len(set(y)) < 2:
        raise SystemExit("В корпусе только один класс — нечего классифицировать")

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=42
    )
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(
            ngram_range=(1, 2),
            min_df=2,
            max_features=50000,
            token_pattern=r"(?u)\b\w+\b",   # кириллица + любые word-символы
            lowercase=True,
            sublinear_tf=True,
        )),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)),
    ])
    pipe.fit(X_tr, y_tr)
    pred = pipe.predict(X_te)
    print(classification_report(y_te, pred, target_names=["synthetic", "real"], digits=4))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, args.out)
    print(f"модель сохранена: {args.out}")


if __name__ == "__main__":
    main()