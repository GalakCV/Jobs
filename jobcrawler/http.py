"""Cliente HTTP resiliente e educado.

Responsabilidades:
  * Rate limit por host (intervalo mínimo entre requisições ao mesmo domínio).
  * Retry com backoff exponencial + jitter para 429, 5xx e falhas de rede,
    respeitando o cabeçalho Retry-After.
  * Detecção de bloqueio (403 / páginas de CAPTCHA / Cloudflare): NÃO insiste,
    apenas sinaliza. Contornar bloqueios (proxies rotativos, quebra de CAPTCHA)
    está fora do escopo de propósito.
  * Circuit breaker: após N falhas seguidas, o host é ignorado no resto da execução.
  * Cache em disco com TTL, para não consultar as APIs a cada teste.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

from jobcrawler import __version__

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
BLOCK_MARKERS = ("captcha", "cf-chl", "attention required", "access denied",
                 "unusual traffic", "are you a robot")


class HttpError(Exception):
    """Falha definitiva ao buscar uma URL."""


class BlockedError(HttpError):
    """O site recusou o acesso (403, CAPTCHA, WAF). Não adianta insistir."""


class CircuitOpenError(HttpError):
    """O host falhou demais nesta execução e foi desativado temporariamente."""


@dataclass
class HttpConfig:
    timeout_seconds: float = 20
    max_retries: int = 4
    backoff_base_seconds: float = 2.0
    min_interval_per_host_seconds: float = 1.5
    circuit_breaker_failures: int = 3
    cache_ttl_minutes: float = 60
    cache_dir: str = ".cache/http"

    @classmethod
    def from_dict(cls, data: dict | None) -> "HttpConfig":
        data = data or {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)


class HttpClient:
    def __init__(self, config: HttpConfig, contact: str | None = None, use_cache: bool = True):
        self.cfg = config
        self.use_cache = use_cache and config.cache_ttl_minutes > 0
        self.cache_dir = Path(config.cache_dir)
        self.session = requests.Session()
        contact = contact or os.getenv("CRAWLER_CONTACT", "")
        ua = f"remote-junior-jobs-crawler/{__version__} (+personal job search)"
        if contact:
            ua += f" contact: {contact}"
        self.session.headers.update({
            "User-Agent": ua,
            "Accept": "application/json, application/rss+xml, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_request: dict[str, float] = {}
        self._failures: dict[str, int] = {}

    # ------------------------------------------------------------------ API
    def get_json(self, url: str, params: dict | None = None, **kw: Any) -> Any:
        body = self.get_text(url, params=params, **kw)
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            # Geralmente significa que recebemos uma página HTML (erro/bloqueio)
            raise HttpError(f"Resposta não é JSON válido em {url}: {body[:120]!r}") from exc

    def get_text(self, url: str, params: dict | None = None,
                 min_interval: float | None = None, cache: bool = True,
                 headers: dict | None = None) -> str:
        full_url = f"{url}?{urlencode(params, doseq=True)}" if params else url
        if cache and self.use_cache:
            cached = self._cache_read(full_url)
            if cached is not None:
                log.debug("cache hit: %s", full_url)
                return cached
        body = self._request_with_retries(full_url, min_interval, headers)
        if cache and self.use_cache:
            self._cache_write(full_url, body)
        return body

    # ------------------------------------------------------------ internals
    def _host(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _respect_rate_limit(self, host: str, min_interval: float | None) -> None:
        interval = self.cfg.min_interval_per_host_seconds if min_interval is None else min_interval
        last = self._last_request.get(host)
        if last is not None:
            wait = interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _check_circuit(self, host: str) -> None:
        if self._failures.get(host, 0) >= self.cfg.circuit_breaker_failures:
            raise CircuitOpenError(f"{host} desativado nesta execução após falhas repetidas")

    def _record(self, host: str, ok: bool) -> None:
        with self._lock:
            self._failures[host] = 0 if ok else self._failures.get(host, 0) + 1

    @staticmethod
    def _retry_after_seconds(resp: requests.Response) -> float | None:
        value = resp.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
            except (TypeError, ValueError):
                return None

    @staticmethod
    def _looks_blocked(resp: requests.Response) -> bool:
        if resp.status_code in (401, 403, 451, 999):  # 999 = resposta típica do LinkedIn
            return True
        ctype = resp.headers.get("Content-Type", "")
        if "html" in ctype and resp.status_code >= 400:
            sample = resp.text[:3000].lower()
            return any(marker in sample for marker in BLOCK_MARKERS)
        return False

    def _request_with_retries(self, url: str, min_interval: float | None,
                              headers: dict | None = None) -> str:
        host = self._host(url)
        # Um lock por host serializa as requisições ao mesmo domínio (rate limit
        # correto mesmo com várias fontes rodando em threads).
        with self._host_lock(host):
            self._check_circuit(host)
            last_error: Exception | None = None
            for attempt in range(self.cfg.max_retries + 1):
                self._respect_rate_limit(host, min_interval)
                try:
                    resp = (self.session.get(url, timeout=self.cfg.timeout_seconds, headers=headers)
                            if headers else self.session.get(url, timeout=self.cfg.timeout_seconds))
                except requests.exceptions.ProxyError as exc:
                    # Proxy/firewall corporativo recusando o destino: persistente.
                    self._failures[host] = self.cfg.circuit_breaker_failures
                    raise BlockedError(f"{host} bloqueado pelo proxy/firewall da rede: {exc}") from exc
                except (requests.ConnectionError, requests.Timeout) as exc:
                    last_error = exc
                    if attempt < self.cfg.max_retries:
                        delay = self._backoff(attempt)
                        log.warning("Erro de rede em %s (%s). Tentativa %d/%d, nova tentativa em %.1fs",
                                    host, exc.__class__.__name__, attempt + 1,
                                    self.cfg.max_retries + 1, delay)
                        time.sleep(delay)
                    continue

                if (resp.status_code in (403, 429)
                        and resp.headers.get("X-RateLimit-Remaining") == "0"):
                    self._failures[host] = self.cfg.circuit_breaker_failures
                    raise BlockedError(
                        f"{host}: limite de requisições da API atingido. "
                        "Para o GitHub, defina GITHUB_TOKEN no .env (limite sobe de 60 para 5000/h).")

                if self._looks_blocked(resp):
                    self._record(host, ok=False)
                    # Bloqueio é quase sempre persistente: abre o circuito já.
                    self._failures[host] = self.cfg.circuit_breaker_failures
                    raise BlockedError(
                        f"{host} recusou o acesso (HTTP {resp.status_code}). "
                        "Possível bloqueio de IP/WAF; a fonte será pulada nesta execução.")

                if resp.status_code in RETRY_STATUS:
                    retry_after = self._retry_after_seconds(resp)
                    delay = retry_after if retry_after is not None else self._backoff(attempt)
                    delay = min(delay, 120)  # nunca trava a execução por muito tempo
                    last_error = HttpError(f"HTTP {resp.status_code}")
                    if attempt < self.cfg.max_retries:
                        log.warning("%s respondeu HTTP %d (rate limit/instabilidade). "
                                    "Tentativa %d/%d, nova tentativa em %.1fs",
                                    host, resp.status_code, attempt + 1,
                                    self.cfg.max_retries + 1, delay)
                        time.sleep(delay)
                    continue

                if resp.status_code >= 400:
                    self._record(host, ok=False)
                    raise HttpError(f"HTTP {resp.status_code} em {url}")

                self._record(host, ok=True)
                resp.encoding = resp.encoding or "utf-8"
                return resp.text

            self._record(host, ok=False)
            raise HttpError(f"Falhou após {self.cfg.max_retries + 1} tentativas: {url} ({last_error})")

    def _backoff(self, attempt: int) -> float:
        return self.cfg.backoff_base_seconds * (2 ** attempt) + random.uniform(0, 1)

    # ---------------------------------------------------------------- cache
    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".json")

    def _cache_read(self, url: str) -> str | None:
        path = self._cache_path(url)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if time.time() - payload.get("ts", 0) > self.cfg.cache_ttl_minutes * 60:
            return None
        return payload.get("body")

    def _cache_write(self, url: str, body: str) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._cache_path(url).write_text(
                json.dumps({"ts": time.time(), "url": url, "body": body}), encoding="utf-8")
        except OSError as exc:  # cache é otimização; nunca derruba a execução
            log.debug("Não foi possível gravar cache: %s", exc)
