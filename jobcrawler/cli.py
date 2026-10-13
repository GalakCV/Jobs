"""Interface de linha de comando.

Exemplos:
  python -m jobcrawler run                       # execução completa
  python -m jobcrawler run --open                # + abre o relatório HTML no navegador
  python -m jobcrawler report --days 14 --open   # HTML com o histórico do banco
  python -m jobcrawler run --explain             # + rejections.csv com motivos
  python -m jobcrawler run --sources himalayas,jobicy --dry-run
  python -m jobcrawler run --loop-hours 6        # repete a cada 6h (Ctrl+C para sair)
  python -m jobcrawler list --days 3             # vagas encontradas nos últimos 3 dias
  python -m jobcrawler import linkedin_vagas.json  # importa vagas de um JSON
  python -m jobcrawler check "Junior DevOps Engineer" --location "USA"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from jobcrawler import __version__
from jobcrawler.config import ConfigError, load_config, setup_logging

log = logging.getLogger("jobcrawler")


def _cmd_run(args, cfg) -> int:
    from jobcrawler.pipeline import run

    only = [s.strip() for s in args.sources.split(",")] if args.sources else None
    while True:
        summary = run(cfg, only=only, dry_run=args.dry_run, notify=not args.no_notify,
                      explain=args.explain, use_cache=not args.no_cache)
        if summary.new:
            print(f"\n{len(summary.new)} vaga(s) nova(s):")
            for job in summary.new:
                print(f"  • {job.title} — {job.company} [{', '.join(job.regions)}]\n    {job.url}")
        elif summary.accepted:
            print(f"\nNenhuma vaga nova ({len(summary.accepted)} já conhecidas ainda abertas).")
        else:
            print("\nNenhuma vaga passou nos filtros nesta execução.")
        html_files = [f for f in summary.files if f.name == "jobs_latest.html"]
        if html_files:
            print(f"\nRelatório: {html_files[0]}")
            if args.open:
                _open_in_browser(html_files[0])
                args.open = False   # no modo loop, abre só na primeira vez
        if not args.loop_hours:
            # código 2 se TODAS as fontes falharam (útil para alertas no cron)
            all_failed = summary.per_source and all(
                st["fetched"] == 0 and st["errors"] for st in summary.per_source.values())
            return 2 if all_failed else 0
        log.info("Próxima execução em %.1f h", args.loop_hours)
        time.sleep(args.loop_hours * 3600)


def _open_in_browser(path: Path) -> None:
    import webbrowser

    if not webbrowser.open(Path(path).resolve().as_uri()):
        print(f"Não foi possível abrir o navegador automaticamente. Abra: {path}")


def _cmd_report(args, cfg) -> int:
    """Gera o HTML a partir do histórico do banco (sem acessar a rede)."""
    from datetime import datetime, timedelta, timezone

    from jobcrawler.html_report import write_html
    from jobcrawler.storage import JobStore

    rows = JobStore(cfg["storage"]["database"]).recent(args.days)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=args.new_hours)).isoformat(timespec="seconds")
    for r in rows:
        r["is_new"] = (r.get("first_seen") or "") >= cutoff
    out = Path(args.output) if args.output else Path(cfg["storage"]["output_dir"]) / "report.html"
    write_html(out, rows, {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    print(f"{len(rows)} vaga(s) dos últimos {args.days} dia(s) em {out}")
    if args.open:
        _open_in_browser(out)
    return 0


def _cmd_import(args, cfg) -> int:
    """Importa vagas de um JSON (ex.: coletadas manualmente ou pelo navegador)."""
    import json

    from jobcrawler.filters import FilterConfig, JobFilter
    from jobcrawler.models import Job
    from jobcrawler.storage import JobStore

    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    items = data.get("jobs", []) if isinstance(data, dict) else data
    fields = Job.__dataclass_fields__
    job_filter = JobFilter(FilterConfig.from_dict(cfg["filters"]))
    accepted, rejected, invalid = [], [], 0
    for item in items:
        kw = {k: v for k, v in item.items() if k in fields}
        for key in ("tags", "regions"):
            if isinstance(kw.get(key), str):
                kw[key] = [x.strip() for x in kw[key].split(",") if x.strip()]
        try:
            job = Job(**kw)
        except TypeError:
            invalid += 1
            continue
        if not job.is_valid():
            invalid += 1
            continue
        if args.no_filter:
            accepted.append(job)
            continue
        decision = job_filter.apply(job)
        if decision.accepted:
            accepted.append(job)
        else:
            rejected.append((job, decision.reason))

    new = JobStore(cfg["storage"]["database"]).upsert(accepted)
    print(f"{len(items)} no arquivo: {len(accepted)} aceitas ({len(new)} novas no banco), "
          f"{len(rejected)} descartadas pelo filtro, {invalid} inválidas.")
    for job, reason in rejected[:10]:
        print(f"  descartada: {job.title} — {reason}")
    print("Rode `python -m jobcrawler report --open` para ver tudo junto.")
    return 0


def _cmd_list(args, cfg) -> int:
    from jobcrawler.storage import JobStore

    rows = JobStore(cfg["storage"]["database"]).recent(args.days)
    if not rows:
        print(f"Nenhuma vaga registrada nos últimos {args.days} dia(s).")
        return 0
    for r in rows:
        date = (r["published_at"] or "")[:10] or "????-??-??"
        print(f"{date}  {r['title']} — {r['company']}  [{r['regions']}]  ({r['source']})\n"
              f"            {r['url']}")
    print(f"\n{len(rows)} vaga(s).")
    return 0


def _cmd_check(args, cfg) -> int:
    """Testa o filtro com um título fictício, sem rede. Útil para ajustar o config."""
    from jobcrawler.filters import FilterConfig, JobFilter
    from jobcrawler.models import Job

    description = Path(args.description_file).read_text(encoding="utf-8") if args.description_file else ""
    job = Job(source="manual", title=args.title, company="Teste", url="https://example.com",
              location=args.location, description=description, source_level=args.level)
    decision = JobFilter(FilterConfig.from_dict(cfg["filters"])).evaluate(job)
    status = "ACEITA" if decision.accepted else "DESCARTADA"
    print(f"{status} | etapa: {decision.stage} | motivo: {decision.reason}")
    if decision.accepted:
        print(f"área: {decision.area} | júnior por: {decision.junior_signal} | regiões: {decision.regions}")
    return 0 if decision.accepted else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobcrawler",
                                     description="Crawler de vagas remotas JÚNIOR em DevOps, Security e Infra")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-c", "--config", default="config.yaml", help="caminho do config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="log DEBUG (mostra cada decisão)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="coleta, filtra, salva, exporta e notifica")
    p_run.add_argument("--sources", help="lista separada por vírgula (ignora 'enabled' do config)")
    p_run.add_argument("--dry-run", action="store_true", help="não grava no banco nem notifica")
    p_run.add_argument("--no-notify", action="store_true", help="não envia notificações")
    p_run.add_argument("--no-cache", action="store_true", help="ignora o cache HTTP em disco")
    p_run.add_argument("--explain", action="store_true", help="gera output/rejections.csv")
    p_run.add_argument("--loop-hours", type=float, default=0, help="repete a cada N horas")
    p_run.add_argument("--open", action="store_true", help="abre o relatório HTML no navegador")
    p_run.set_defaults(func=_cmd_run)

    p_report = sub.add_parser("report", help="gera HTML com o histórico do banco (sem rede)")
    p_report.add_argument("--days", type=int, default=14, help="vagas vistas nos últimos N dias")
    p_report.add_argument("--new-hours", type=int, default=24,
                          help="marca como 'Nova' o que apareceu nas últimas N horas")
    p_report.add_argument("--output", help="caminho do arquivo (padrão: output/report.html)")
    p_report.add_argument("--open", action="store_true", help="abre no navegador")
    p_report.set_defaults(func=_cmd_report)

    p_import = sub.add_parser("import", help="importa vagas de um arquivo JSON para o banco")
    p_import.add_argument("file", help="JSON: lista de vagas ou {'jobs': [...]}")
    p_import.add_argument("--no-filter", action="store_true",
                          help="grava sem passar pelo filtro (não recomendado)")
    p_import.set_defaults(func=_cmd_import)

    p_list = sub.add_parser("list", help="lista vagas salvas no banco")
    p_list.add_argument("--days", type=int, default=7)
    p_list.set_defaults(func=_cmd_list)

    p_check = sub.add_parser("check", help="testa o filtro com um título (sem rede)")
    p_check.add_argument("title")
    p_check.add_argument("--location", default="")
    p_check.add_argument("--level", default="", help="senioridade declarada pela fonte")
    p_check.add_argument("--description-file", help="arquivo .txt com a descrição")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 1
    setup_logging(cfg.get("logging") or {}, verbose=args.verbose)
    try:
        return args.func(args, cfg)
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuário")
        return 130
    except ValueError as exc:  # ex.: config de filtros inválida
        log.error("%s", exc)
        return 1
    except OSError as exc:     # arquivo inexistente, disco cheio, permissão...
        log.error("Erro de arquivo/sistema: %s", exc)
        return 1
