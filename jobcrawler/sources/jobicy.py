"""Jobicy - API pública JSON (https://jobicy.com/jobs-rss-feed).

Retorna vagas dos últimos 7 dias, com paginação por cursor. Pede atribuição e
no máximo uma varredura por hora (o cache de 60 min do HttpClient garante isso).
"""

from __future__ import annotations

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import html_to_text, parse_date

API_URL = "https://jobicy.com/api/v2/remote-jobs"


def _salary(item: dict) -> str:
    lo, hi = item.get("salaryMin"), item.get("salaryMax")
    if not lo and not hi:
        return ""
    rng = f"{lo:,.0f}–{hi:,.0f}" if lo and hi else f"{(lo or hi):,.0f}"
    return f"{item.get('salaryCurrency', '')} {rng} ({item.get('salaryPeriod', '')})".strip()


def parse_job(item: dict) -> Job:
    return Job(
        source="jobicy",
        title=item["jobTitle"],
        company=item.get("companyName", ""),
        url=item["url"],
        location=item.get("jobGeo", ""),
        description=html_to_text(item.get("jobDescription") or item.get("jobExcerpt")),
        published_at=parse_date(item.get("pubDate")),
        tags=list(item.get("jobType") or []),
        salary=_salary(item),
        source_level=item.get("jobLevel", "") if item.get("jobLevel") != "Any" else "",
        source_category=", ".join(item.get("jobIndustry") or []),
    )


class JobicySource(Source):
    name = "jobicy"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        count = int(self.cfg.get("count", 100))
        max_pages = int(self.cfg.get("max_pages", 3))
        for industry in self.cfg.get("industries", ["admin"]):
            def run(ind=industry):
                jobs: list[Job] = []
                cursor = None
                for _ in range(max_pages):
                    params = {"count": count, "industry": ind}
                    if cursor:
                        params["cursor"] = cursor
                    data = self.http.get_json(API_URL, params=params)
                    if not isinstance(data, dict) or "jobs" not in data:
                        raise SchemaChangedError(f"campo 'jobs' ausente: {str(data)[:120]}")
                    if data.get("success") is False:
                        raise SchemaChangedError(f"API retornou erro: {data.get('error')}")
                    jobs += parse_many(data["jobs"], parse_job, self.name)
                    cursor = data.get("nextCursor")
                    if not cursor:
                        break
                return jobs
            self._safe(result, f"industry={industry}", run)
        return result
