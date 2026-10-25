from unittest.mock import Mock
import pytest
import requests
from src.services.parsing import parse_hh_url


@pytest.mark.parametrize('url',[
    'http://127.0.0.1/internal?source=hh.ru', 'https://hh.ru.evil.test/resume/abc',
    'https://evil.test/hh.ru/resume/abc', 'https://hh.ru@evil.test/resume/abc',
    'https://user:password@hh.ru/resume/abc', 'file:///hh.ru/resume/abc',
    'http://hh.ru/resume/abc','https://hh.ru:8443/resume/abc',
    'https://hh.ru/vacancy/abc','https://hh.ru/resume/../abc',
    'https://hh.ru/resume/abc\n','https://hh.ru/resume/abc#fragment',
])
def test_invalid_hh_url_never_makes_network_request(monkeypatch,url):
    get=Mock()
    monkeypatch.setattr(requests,'get',get)
    with pytest.raises(ValueError):
        parse_hh_url(url)
    get.assert_not_called()


def test_hh_redirect_is_not_followed(monkeypatch):
    response=Mock(status_code=302)
    get=Mock(return_value=response)
    monkeypatch.setattr(requests,'get',get)
    with pytest.raises(ValueError,match='перенаправил'):
        parse_hh_url('https://hh.ru/resume/abc')
    assert get.call_args.kwargs['allow_redirects'] is False
    assert get.call_count==1
    response.iter_content.assert_not_called()
    response.close.assert_called_once()


def test_hh_stream_size_is_bounded_and_closed(monkeypatch):
    response=Mock(status_code=200,encoding='utf-8')
    response.iter_content.return_value=iter([b'x'*65536]*33)
    monkeypatch.setattr(requests,'get',Mock(return_value=response))
    with pytest.raises(ValueError,match='2 МБ'):
        parse_hh_url('https://www.hh.ru/resume/abc')
    response.close.assert_called_once()


def test_valid_hh_resume_is_parsed(monkeypatch):
    response=Mock(status_code=200,encoding='utf-8')
    response.iter_content.return_value=iter(['<div data-field="resume_block">Резюме Python</div>'.encode()])
    monkeypatch.setattr(requests,'get',Mock(return_value=response))
    assert parse_hh_url('https://hh.ru/resume/abc?from=search')=='Резюме Python'
    response.close.assert_called_once()
