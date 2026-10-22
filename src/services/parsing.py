# -*- coding: utf-8 -*-
"""Сервисы извлечения требований и работы с файлами."""

import io
import re
from typing import List

from src.config import REQUIREMENT_MARKERS


def extract_requirements(text: str) -> List[str]:
    """Извлекает требования из текста вакансии по ключевым словам-маркерам."""
    requirements = []
    fragments: List[str] = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"(?<=[.!?])\s+", line)
        fragments.extend(p.strip() for p in parts if p.strip())

    for fragment in fragments:
        fragment_lower = fragment.lower()
        for marker in REQUIREMENT_MARKERS:
            if marker in fragment_lower:
                idx = fragment_lower.find(marker)
                requirement = fragment[idx:].rstrip(".,;:!?")
                if len(requirement) > 3:
                    requirements.append(requirement)
                break

    seen = set()
    unique = []
    for req in requirements:
        key = req.lower()
        if key not in seen:
            seen.add(key)
            unique.append(req)

    return unique


def parse_pdf(stream) -> str:
    """Извлекает текст из PDF через PyPDF2."""
    import PyPDF2

    reader = PyPDF2.PdfReader(io.BytesIO(stream.read()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_docx(stream) -> str:
    """Извлекает текст из DOCX через python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(stream.read()))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_hh_url(url: str) -> str:
    """Скачивает страницу hh.ru с User-Agent и извлекает текст резюме."""
    import requests
    from bs4 import BeautifulSoup

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    resume_block = soup.find("div", {"data-field": "resume_block"})
    if resume_block:
        return resume_block.get_text(separator="\n", strip=True)

    content = soup.find("div", class_="member-page__content")
    if content:
        return content.get_text(separator="\n", strip=True)

    return soup.get_text(separator="\n", strip=True)[:5000]
