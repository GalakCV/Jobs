"""Remote OK - API pública JSON (https://remoteok.com/api).

O primeiro elemento da lista é um aviso legal (termos da API: mencionar o
Remote OK e linkar de volta). Ele é ignorado automaticamente.
"""

from __future__ import annotations

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import fix_mojibake, html_to_text, parse_date

API_URL = "https://remoteok.com/api"


def _salary(item: dict) -> str:
    lo, hi = item.get("salary_min") or 0, item.get("salary_max") or 0
    if not lo and not hi:
        return ""
    return f"USD {lo:,.0f}–{hi:,.0f}" if lo and hi else f"USD {(lo or hi):,.0f}"


def parse_job(item: dict) -> Job:
    return Job(
        source="remoteok",
        title=fix_mojibake(item["position"]),
        company=fix_mojibake(item.get("company", "")),
        url=item.get("url") or item.get("apply_url") or "",
        location=fix_mojibake(item.get("location", "")),
        description=html_to_text(item.get("description")),
        published_at=parse_date(item.get("date") or item.get("epoch")),
        tags=list(item.get("tags") or [])[:10],
        salary=_salary(item),
    )


def extract_items(data) -> list[dict]:
    if not isinstance(data, list):
        raise SchemaChangedError(f"esperava uma lista, veio {type(data).__name__}")
    # descarta o aviso legal e qualquer outro item que não seja vaga
    return [x for x in data if isinstance(x, dict) and "position" in x]


class RemoteOkSource(Source):
    name = "remoteok"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        tags = self.cfg.get("tags") or [None]
        for tag in tags:
            def run(t=tag):
                data = self.http.get_json(API_URL, params={"tag": t} if t else None)
                return parse_many(extract_items(data), parse_job, self.name)
            self._safe(result, f"tag={tag or 'todas'}", run)
        return result
