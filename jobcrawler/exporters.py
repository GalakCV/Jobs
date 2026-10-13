"""Exportação dos resultados para JSON e CSV."""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from jobcrawler.filters import WORKPLACE_LABELS
from jobcrawler.html_report import write_html
from jobcrawler.models import Job

log = logging.getLogger(__name__)

AREA_LABELS = {
    "security": "Cibersegurança",
    "devops_sre_platform": "DevOps / SRE / Platform",
    "infra_cloud_sysadmin": "Infra / Cloud / SysAdmin",
}

# Ordem e nomes das colunas no CSV (abre direto no Excel / Google Sheets)
CSV_COLUMNS = [
    ("published_at", "Publicada em"),
    ("title", "Título"),
    ("company", "Empresa"),
    ("area_label", "Área"),
    ("workplace_label", "Modalidade"),
    ("location", "Localização"),
    ("regions", "Regiões"),
    ("timezone", "Fuso exigido"),
    ("junior_signal", "Por que é júnior"),
    ("salary", "Salário"),
    ("source", "Fonte"),
    ("is_new", "Nova?"),
    ("url", "Link"),
]


def _rows(jobs: list[Job], new_fingerprints: set[str]) -> list[dict]:
    rows = []
    for job in sorted(jobs, key=lambda j: j.published_at or "", reverse=True):
        rec = job.to_record()
        rec["area_label"] = AREA_LABELS.get(job.area, job.area)
        rec["workplace_label"] = WORKPLACE_LABELS.get(job.workplace, "Não informada")
        rec["is_new"] = "sim" if job.fingerprint in new_fingerprints else "não"
        rows.append(rec)
    return rows


def export(jobs: list[Job], new_jobs: list[Job], output_dir: str | Path,
           formats: list[str], meta: dict | None = None) -> list[Path]:
    """Grava os arquivos `jobs_latest.*` e uma cópia datada de cada execução."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rows = _rows(jobs, {j.fingerprint for j in new_jobs})
    written: list[Path] = []

    if "html" in formats:
        for name in ("jobs_latest.html", f"jobs_{stamp}.html"):
            written.append(write_html(out / name, rows, meta))

    if "json" in formats:
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total": len(rows),
            "new": len(new_jobs),
            "jobs": rows,
        }
        for name in ("jobs_latest.json", f"jobs_{stamp}.json"):
            path = out / name
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            written.append(path)

    if "csv" in formats:
        for name in ("jobs_latest.csv", f"jobs_{stamp}.csv"):
            path = out / name
            # utf-8-sig: acentos aparecem certos ao abrir no Excel
            with path.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow([label for _, label in CSV_COLUMNS])
                for row in rows:
                    writer.writerow([row.get(key, "") for key, _ in CSV_COLUMNS])
            written.append(path)

    log.info("Exportado: %s", ", ".join(str(p) for p in written if "latest" in p.name))
    return written


def export_rejections(rejections: list[tuple[Job, str, str]], output_dir: str | Path) -> Path:
    """Gera rejections.csv para auditar o filtro (usado com --explain)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "rejections.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Etapa", "Motivo", "Título", "Empresa", "Localização", "Modalidade",
                         "Fonte", "Link"])
        for job, stage, reason in rejections:
            writer.writerow([stage, reason, job.title, job.company, job.location,
                             job.workplace or job.workplace_hint, job.source, job.url])
    return path
