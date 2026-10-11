"""Testes de resiliência do HttpClient (sem rede: `session.get` é simulado)."""

import pytest
import requests

from jobcrawler.http import BlockedError, CircuitOpenError, HttpClient, HttpConfig, HttpError


class FakeResponse:
    def __init__(self, status=200, text="{}", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {"Content-Type": "application/json"}
        self.encoding = "utf-8"


def client(tmp_path, responses, **overrides):
    cfg = HttpConfig(backoff_base_seconds=0, min_interval_per_host_seconds=0,
                     max_retries=3, cache_dir=str(tmp_path / "cache"), **overrides)
    c = HttpClient(cfg)
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    c.session.get = fake_get
    c._backoff = lambda attempt: 0  # testes rápidos
    return c, calls


def test_retries_on_429_then_succeeds(tmp_path):
    c, calls = client(tmp_path, [FakeResponse(429, headers={"Retry-After": "0"}),
                                 FakeResponse(503), FakeResponse(200, '{"ok": 1}')],
                      cache_ttl_minutes=0)
    assert c.get_json("https://api.test/x") == {"ok": 1}
    assert len(calls) == 3


def test_retries_on_network_error(tmp_path):
    c, calls = client(tmp_path, [requests.ConnectionError("boom"), FakeResponse(200, "[]")],
                      cache_ttl_minutes=0)
    assert c.get_json("https://api.test/x") == []


def test_gives_up_after_max_retries(tmp_path):
    c, _ = client(tmp_path, [FakeResponse(500)] * 4, cache_ttl_minutes=0)
    with pytest.raises(HttpError):
        c.get_text("https://api.test/x")


def test_blocked_is_not_retried_and_opens_circuit(tmp_path):
    c, calls = client(tmp_path, [FakeResponse(403, "<html>Access denied</html>",
                                              {"Content-Type": "text/html"})],
                      cache_ttl_minutes=0)
    with pytest.raises(BlockedError):
        c.get_text("https://site.test/a")
    assert len(calls) == 1
    with pytest.raises(CircuitOpenError):  # mesmo host: nem tenta de novo
        c.get_text("https://site.test/b")


def test_html_instead_of_json_is_clear_error(tmp_path):
    c, _ = client(tmp_path, [FakeResponse(200, "<html>maintenance</html>")], cache_ttl_minutes=0)
    with pytest.raises(HttpError, match="não é JSON"):
        c.get_json("https://api.test/x")


def test_disk_cache_avoids_second_request(tmp_path):
    c, calls = client(tmp_path, [FakeResponse(200, '{"a": 1}')], cache_ttl_minutes=60)
    assert c.get_json("https://api.test/x", params={"q": "devops"}) == {"a": 1}
    assert c.get_json("https://api.test/x", params={"q": "devops"}) == {"a": 1}
    assert len(calls) == 1
