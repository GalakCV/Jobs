"""Contrato comum das fontes de vagas.

Cada fonte separa:
  * `fetch()`  -> I/O (usa o HttpClient, paginação, várias consultas)
  * `parse_*`  -> funções PURAS que convertem o JSON/XML/HTML bruto em `Job`

Isso permite testar os parsers com fixtures, sem rede, e detectar mudanças de
schema/DOM: se a maioria dos itens falhar no parse, a fonte registra um erro
claro em vez de devolver silenciosamente uma lista vazia.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from jobcrawler.http import BlockedError, CircuitOpenError, HttpClient, HttpError
from jobcrawler.models import Job


class SchemaChangedError(Exception):
    """A resposta da fonte não tem mais o formato esperado."""


@dataclass
class SourceResult:
    source: str
    jobs: list[Job] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    requests_ok: int = 0


class Source(ABC):
    name: str = "base"

    def __init__(self, http: HttpClient, cfg: dict | None = None):
        self.http = http
        self.cfg = cfg or {}
        self.log = logging.getLogger(f"jobcrawler.sources.{self.name}")

    @abstractmethod
    def fetch(self) -> SourceResult:
        ...

    # ---------------------------------------------------------------- helpers
    def _safe(self, result: SourceResult, label: str, fn: Callable[[], Iterable[Job]]) -> None:
        """Executa uma consulta isolando falhas: um erro não derruba as demais consultas."""
        try:
            jobs = list(fn())
            result.jobs.extend(jobs)
            result.requests_ok += 1
            self.log.info("%s: %d vagas brutas em '%s'", self.name, len(jobs), label)
        except (BlockedError, CircuitOpenError) as exc:
            # Bloqueio / host desativado: não adianta tentar as outras consultas.
            result.errors.append(f"{label}: {exc}")
            self.log.error("%s - %s", self.name, exc)
            raise
        except HttpError as exc:
            # Erro pontual (ex.: 404 numa consulta): segue com as demais.
            msg = f"{label}: {exc}"
            self.log.error("%s - %s", self.name, msg)
            result.errors.append(msg)
        except SchemaChangedError as exc:
            msg = f"{label}: possível mudança de formato da fonte - {exc}"
            self.log.error("%s - %s", self.name, msg)
            result.errors.append(msg)


def parse_many(items: Iterable[Any], parser: Callable[[Any], Job | None],
               source: str, min_success_ratio: float = 0.5) -> list[Job]:
    """Aplica `parser` a cada item; detecta drift de schema pela taxa de falhas."""
    log = logging.getLogger(f"jobcrawler.sources.{source}")
    items = list(items)
    jobs: list[Job] = []
    failures = 0
    for item in items:
        try:
            job = parser(item)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            failures += 1
            log.debug("Item ignorado em %s: %s", source, exc)
            continue
        if job is not None and job.is_valid():
            jobs.append(job)
        elif job is not None:
            failures += 1
    if items and failures / len(items) > (1 - min_success_ratio):
        sample = items[0]
        keys = sorted(sample.keys())[:15] if isinstance(sample, dict) else type(sample).__name__
        raise SchemaChangedError(f"{failures}/{len(items)} itens falharam no parse; "
                                 f"campos recebidos: {keys}")
    return jobs
