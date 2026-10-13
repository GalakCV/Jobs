"""Orquestração: coleta -> deduplicação -> filtro -> persistência -> exportação -> notificação."""

from __future__ import annotations

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from jobcrawler.exporters import export, export_rejections
from jobcrawler.http import HttpClient, HttpConfig, HttpError
from jobcrawler.models import Job
from jobcrawler.notifiers import build_notifiers
from jobcrawler.profiles import Profile, build_profiles, profile_labels
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
    per_profile: dict[str, int] = field(default_factory=dict)
    notified: int = 0
    files: list = field(default_factory=list)   # arquivos exportados nesta execução


def _collect(cfg: dict, only: list[str] | None, use_cache: bool,
             profiles: list[Profile]) -> list[SourceResult]:
    http = HttpClient(HttpConfig.from_dict(cfg.get("http")), use_cache=use_cache)
    sources_cfg = cfg.get("sources") or {}
    selected = []
    for name, scfg in sources_cfg.items():
        scfg = scfg or {}
        if only and name not in only:
            continue
        if not only and not scfg.get("enabled"):
            continue
        if not any(p.uses(name) for p in profiles):
            continue          # nenhum perfil desta execução usa a fonte
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
        notify: bool = True, explain: bool = False, use_cache: bool = True,
        profiles_only: list[str] | None = None) -> RunSummary:
    summary = RunSummary()
    profiles = build_profiles(cfg, profiles_only)
    store = None if dry_run else JobStore(cfg["storage"]["database"])
    run_id = store.start_run() if store else None

    # 1. Coleta (cada fonte uma vez, mesmo que vários perfis a usem) ---------
    results = _collect(cfg, only, use_cache, profiles)
    raw: list[tuple[Job, str]] = []        # (vaga, nome da fonte que a coletou)
    for res in results:
        raw += [(job, res.source) for job in res.jobs]
        summary.per_source[res.source] = {"fetched": len(res.jobs), "accepted": 0,
                                          "errors": len(res.errors)}
        if res.errors:
            summary.errors[res.source] = res.errors
    summary.fetched = len(raw)
    summary.unique = len({job.fingerprint for job, _ in raw})
    origin_of = {id(job): origin for job, origin in raw}

    # 2. Deduplicação + 3. Filtro, perfil por perfil -------------------------
    # Cada perfil só vê as vagas das suas fontes. Uma vaga aceita por um perfil
    # não é avaliada pelos seguintes (o primeiro perfil do config tem prioridade).
    accepted_fps: set[str] = set()
    first_rejection: dict[str, tuple[Job, str, str]] = {}
    for profile in profiles:
        pool = _dedupe([job for job, origin in raw if profile.uses(origin)])
        count = 0
        for job in pool:
            if job.fingerprint in accepted_fps:
                continue
            decision = profile.apply(job)
            if decision.accepted:
                accepted_fps.add(job.fingerprint)
                first_rejection.pop(job.fingerprint, None)
                summary.accepted.append(job)
                summary.per_source[origin_of[id(job)]]["accepted"] += 1
                count += 1
                log.debug("ACEITA  [%s] %s | %s | %s", profile.key, job.title, job.company,
                          decision.junior_signal)
            else:
                first_rejection.setdefault(job.fingerprint, (job, decision.stage, decision.reason))
                log.debug("REJEITA [%s] %s | %s -> %s", profile.key, job.title, job.company,
                          decision.reason)
        summary.per_profile[profile.key] = count
    rejections = list(first_rejection.values())
    summary.rejection_stages.update(stage for _, stage, _ in rejections)

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
        "report": cfg.get("report") or {},
        "profiles": profile_labels(cfg),
        "per_profile": summary.per_profile,
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
            labels = profile_labels(cfg)
            for item in pending:
                item["profile_label"] = labels.get(item.get("profile") or "", "")
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
    if len(s.per_profile) > 1:
        log.info("Aceitas por perfil: %s", ", ".join(f"{k}={v}" for k, v in s.per_profile.items()))
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
