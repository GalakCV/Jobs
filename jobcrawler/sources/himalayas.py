"""Himalayas - API pública JSON (https://himalayas.app/api).

Usa o endpoint de busca, que aceita `q` e `seniority`. Termos da API: citar o
Himalayas como fonte e manter o link original (fazemos isso salvando `url`).
"""

from __future__ import annotations

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import html_to_text, parse_date, utc_offsets_to_label

SEARCH_URL = "https://himalayas.app/jobs/api/search"


def _salary(item: dict) -> str:
    lo, hi = item.get("minSalary"), item.get("maxSalary")
    if not lo and not hi:
        return ""
    cur = item.get("currency") or ""
    period = item.get("salaryPeriod") or "annual"
    rng = f"{lo:,.0f}–{hi:,.0f}" if lo and hi else f"{(lo or hi):,.0f}"
    return f"{cur} {rng} ({period})".strip()


def parse_job(item: dict) -> Job:
    restrictions = item.get("locationRestrictions") or []
    location = ", ".join(r if isinstance(r, str) else str(r.get("name", "")) for r in restrictions)
    return Job(
        source="himalayas",
        title=item["title"],
        company=item.get("companyName", ""),
        url=item.get("applicationLink") or item.get("guid") or "",
        location=location or "Worldwide",       # sem restrição = vaga global
        description=html_to_text(item.get("description") or item.get("excerpt")),
        published_at=parse_date(item.get("pubDate")),
        tags=list(item.get("categories") or [])[:8],
        salary=_salary(item),
        source_level=", ".join(item.get("seniority") or []),
        source_category=", ".join(item.get("parentCategories") or []),
        timezone=utc_offsets_to_label(item.get("timezoneRestrictions") or item.get("timezoneRestriction")),
    )


def extract_items(data) -> list[dict]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("jobs", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    raise SchemaChangedError(f"resposta sem lista de vagas (chaves: {list(data)[:10] if isinstance(data, dict) else type(data).__name__})")


class HimalayasSource(Source):
    name = "himalayas"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        seniority = self.cfg.get("seniority", "Entry-level")
        max_pages = int(self.cfg.get("max_pages", 3))
        for query in self.cfg.get("queries", ["devops"]):
            def run(q=query):
                jobs: list[Job] = []
                for page in range(1, max_pages + 1):
                    params = {"q": q, "sort": "recent", "page": page}
                    if seniority:
                        params["seniority"] = seniority
                    items = extract_items(self.http.get_json(SEARCH_URL, params=params))
                    if not items:
                        break
                    jobs += parse_many(items, parse_job, self.name)
                    if len(items) < 20:   # última página (máximo de 20 por requisição)
                        break
                return jobs
            self._safe(result, f"q={query}", run)
        return result
