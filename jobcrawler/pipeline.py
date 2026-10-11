"""Orquestração: coleta -> deduplicação -> filtro -> persistência -> exportação -> notificação."""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from jobcrawler.exporters import export, export_rejections
from jobcrawler.filters import FilterConfig, JobFilter
from jobcrawler.http import HttpClient, HttpConfig, HttpError
from jobcrawler.models import Job
from jobcrawler.notifiers import build_notifiers
from jobcrawler.sources import REGISTRY, SourceResult
from jobcrawler.storage import JobStore

log = logging.getLogger(__name__)


@dataclass
class RunSummary:
    fetched: int = 0
    unique: int = 0
    accepted: list[Job] = field(default_factory=list)
    new: list[Job] = field(default_factory=list)
    per_source: dict[str, dict] = field(default_factory=dict)
    rejection_stages: Counter = field(default_factory=Counter)
    errors: dict[str, list[str]] = field(default_factory=dict)
    notified: int = 0
    files: list = field(default_factory=list)   # arquivos exportados nesta execução


def _collect(cfg: dict, only: list[str] | None, use_cache: bool) -> list[SourceResult]:
    http = HttpClient(HttpConfig.from_dict(cfg.get("http")), use_cache=use_cache)
    sources_cfg = cfg.get("sources") or {}
    selected = []
    for name, scfg in sources_cfg.items():
        scfg = scfg or {}
        if only and name not in only:
            continue
        if not only and not scfg.get("enabled"):
            continue
        if name not in REGISTRY:
            log.warning("Fonte '%s' no config não existe no código; ignorando", name)
            continue
        selected.append(REGISTRY[name](http, scfg))
    if not selected:
        raise ValueError("Nenhuma fonte selecionada para esta execução")

    log.info("Coletando de: %s", ", ".join(s.name for s in selected))
    results: list[SourceResult] = []
    # Uma thread por fonte; o HttpClient serializa as requisições por host.
    with ThreadPoolExecutor(max_workers=len(selected)) as pool:
        futures = {pool.submit(src.fetch): src for src in selected}
        for fut in as_completed(futures):
            src = futures[fut]
            try:
                results.append(fut.result())
            except HttpError as exc:   # bloqueio / circuito aberto: fonte pulada
                results.append(SourceResult(src.name, errors=[str(exc)]))
            except Exception as exc:   # nunca deixa uma fonte derrubar a execução
                log.exception("Erro inesperado na fonte %s", src.name)
                results.append(SourceResult(src.name, errors=[f"erro inesperado: {exc!r}"]))
    return results


def _dedupe(jobs: list[Job]) -> list[Job]:
    """Mesma vaga em várias fontes/consultas: mantém a versão com mais informação."""
    best: dict[str, Job] = {}
    for job in jobs:
        current = best.get(job.fingerprint)
        if current is None or len(job.description) > len(current.description):
            best[job.fingerprint] = job
    return list(best.values())


def run(cfg: dict, *, only: list[str] | None = None, dry_run: bool = False,
        notify: bool = True, explain: bool = False, use_cache: bool = True) -> RunSummary:
    summary = RunSummary()
    store = None if dry_run else JobStore(cfg["storage"]["database"])
    run_id = store.start_run() if store else None

    # 1. Coleta -----------------------------------------------------------
    results = _collect(cfg, only, use_cache)
    raw: list[Job] = []
    for res in results:
        raw += res.jobs
        summary.per_source[res.source] = {"fetched": len(res.jobs), "accepted": 0,
                                          "errors": len(res.errors)}
        if res.errors:
            summary.errors[res.source] = res.errors
    summary.fetched = len(raw)

    # 2. Deduplicação + 3. Filtro ------------------------------------------
    unique = _dedupe(raw)
    summary.unique = len(unique)
    job_filter = JobFilter(FilterConfig.from_dict(cfg["filters"]))
    rejections: list[tuple[Job, str, str]] = []
    for job in unique:
        decision = job_filter.apply(job)
        if decision.accepted:
            summary.accepted.append(job)
            stats = summary.per_source.setdefault(job.source, {"fetched": 0, "accepted": 0, "errors": 0})
            stats["accepted"] += 1
            log.debug("ACEITA  %s | %s | %s", job.title, job.company, decision.junior_signal)
        else:
            summary.rejection_stages[decision.stage] += 1
            rejections.append((job, decision.stage, decision.reason))
            log.debug("REJEITA %s | %s -> %s", job.title, job.company, decision.reason)

    # 4. Persistência --------------------------------------------------------
    if store:
        summary.new = store.upsert(summary.accepted)
    else:
        summary.new = list(summary.accepted)

    # 5. Exportação ---------------------------------------------------------
    storage_cfg = cfg["storage"]
    meta = {
        "fetched": summary.fetched,
        "unique": summary.unique,
        "per_source": summary.per_source,
        "errors": summary.errors,
        "rejection_stages": dict(summary.rejection_stages),
    }
    summary.files = export(summary.accepted, summary.new, storage_cfg["output_dir"],
                           storage_cfg.get("export_formats", ["html", "json", "csv"]), meta)
    if explain:
        path = export_rejections(rejections, storage_cfg["output_dir"])
        log.info("Motivos de descarte em %s", path)

    # 6. Notificação (somente vagas novas ainda não notificadas) ------------
    if store and notify:
        ncfg = cfg.get("notifications") or {}
        notifiers = build_notifiers(ncfg)
        if notifiers:
            pending = store.pending_notifications(int(ncfg.get("max_per_run", 25)))
            if pending:
                results_ok = []
                for notifier in notifiers:
                    try:
                        results_ok.append(notifier.send(pending))
                    except Exception as exc:  # rede, credencial inválida...
                        log.error("Falha no notificador %s: %s", notifier.name, exc)
                        results_ok.append(False)
                if all(results_ok):
                    store.mark_notified([p["fingerprint"] for p in pending])
                    summary.notified = len(pending)

    if store and run_id is not None:
        store.finish_run(run_id, summary.fetched, len(summary.accepted), len(summary.new),
                         summary.errors)
    _log_summary(summary)
    return summary


def _log_summary(s: RunSummary) -> None:
    log.info("=" * 64)
    log.info("Coletadas: %d | únicas: %d | aceitas: %d | novas: %d | notificadas: %d",
             s.fetched, s.unique, len(s.accepted), len(s.new), s.notified)
    for name, st in sorted(s.per_source.items()):
        log.info("  %-15s brutas=%-4d aceitas=%-3d erros=%d",
                 name, st["fetched"], st["accepted"], st["errors"])
    if s.rejection_stages:
        log.info("Descartes por etapa: %s",
                 ", ".join(f"{k}={v}" for k, v in s.rejection_stages.most_common()))
    for name, errs in s.errors.items():
        for err in errs:
            log.warning("  [%s] %s", name, err)
    log.info("=" * 64)
