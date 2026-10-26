# -*- coding: utf-8 -*-
"""Сервисы извлечения требований и работы с файлами."""

import io
import re
from urllib.parse import urlsplit
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
    """Извлекает текст из PDF через pypdf."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(stream.read()))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_docx(stream) -> str:
    """Извлекает текст из DOCX через python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(stream.read()))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def validate_hh_url(url: str) -> str:
    """Only direct HTTPS resume links on HH's explicitly permitted hosts."""
    try:
        if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
            raise ValueError
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in {"hh.ru", "www.hh.ru"}
                or parts.username is not None or parts.password is not None
                or parts.port not in {None, 443} or parts.fragment
                or not re.fullmatch(r"/resume/[A-Za-z0-9]+/?", parts.path)):
            raise ValueError
    except ValueError:
        raise ValueError("Укажите прямую HTTPS-ссылку вида https://hh.ru/resume/ID") from None
    return url


def parse_hh_url(url: str) -> str:
    """Скачивает страницу hh.ru с User-Agent и извлекает текст резюме."""
    import requests
    from bs4 import BeautifulSoup

    url = validate_hh_url(url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    response = requests.get(url, headers=headers, timeout=(5, 15), allow_redirects=False, stream=True)
    try:
        if 300 <= response.status_code < 400:
            raise ValueError("hh.ru перенаправил запрос. Скопируйте прямую ссылку на резюме.")
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            content.extend(chunk)
            if len(content) > 2 * 1024 * 1024:
                raise ValueError("Страница резюме превышает допустимый размер (2 МБ)")
        html = content.decode(response.encoding or "utf-8", errors="replace")
    finally:
        response.close()

    soup = BeautifulSoup(html, "html.parser")

    resume_block = soup.find("div", {"data-field": "resume_block"})
    if resume_block:
        return resume_block.get_text(separator="\n", strip=True)

    content = soup.find("div", class_="member-page__content")
    if content:
        return content.get_text(separator="\n", strip=True)

    return soup.get_text(separator="\n", strip=True)[:5000]
