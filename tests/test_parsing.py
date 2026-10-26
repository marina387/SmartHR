# -*- coding: utf-8 -*-
"""Тесты для парсинга текста и файлов."""

from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.parsing import extract_requirements, parse_docx, parse_pdf


@pytest.fixture
def sample_vacancy_text() -> str:
    """Возвращает текст вакансии для тестов."""
    return "Обязательно наличие профильного образования. Требуется опыт работы от 3 лет. Необходимо умение работать с документацией."


def test_extract_requirements_returns_unique_requirements(sample_vacancy_text: str) -> None:
    """Из текста вакансии должны извлекаться уникальные требования."""
    requirements = extract_requirements(sample_vacancy_text)

    assert requirements
    assert any("опыт работы" in item.lower() for item in requirements)
    assert len(requirements) == len(set(requirements))


def test_parse_pdf_reads_text_from_stream() -> None:
    """PDF-парсер должен читать текст из байтового потока."""
    fake_pdf_reader = MagicMock()
    fake_page = MagicMock()
    fake_page.extract_text.return_value = "Текст страницы"
    fake_pdf_reader.pages = [fake_page]

    with patch("pypdf.PdfReader", return_value=fake_pdf_reader):
        stream = BytesIO(b"fake-pdf")
        assert parse_pdf(stream) == "Текст страницы"


def test_pdf_readers_extract_real_pdf(tmp_path) -> None:
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from src.core.loaders import load_document

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 20 250 Td (Python SQL resume) Tj ET')
    page[NameObject('/Contents')] = content
    path = tmp_path / 'resume.pdf'
    writer.write(path)
    with path.open('rb') as stream:
        assert 'Python SQL resume' in parse_pdf(stream)
    assert 'Python SQL resume' in load_document(path).text


def test_parse_docx_reads_paragraphs() -> None:
    """DOCX-парсер должен читать текст из документов Word."""
    fake_document = MagicMock()
    fake_document.paragraphs = [MagicMock(text="Первая строка"), MagicMock(text="   "), MagicMock(text="Вторая строка")]

    with patch("docx.Document", return_value=fake_document):
        stream = BytesIO(b"fake-docx")
        assert parse_docx(stream) == "Первая строка\nВторая строка"
