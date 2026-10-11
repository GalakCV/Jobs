"""Remotive - API pública JSON (https://remotive.com/api/remote-jobs).

O Remotive pede para não consultar a API mais do que algumas vezes por dia e
para linkar de volta para a vaga; respeitamos isso com cache e o campo `url`.
"""

from __future__ import annotations

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import html_to_text, parse_date

API_URL = "https://remotive.com/api/remote-jobs"


def parse_job(item: dict) -> Job:
    return Job(
        source="remotive",
        title=item["title"],
        company=item.get("company_name", ""),
        url=item["url"],
        location=item.get("candidate_required_location", ""),
        description=html_to_text(item.get("description")),
        published_at=parse_date(item.get("publication_date")),
        tags=list(item.get("tags") or [])[:8],
        salary=item.get("salary") or "",
        source_category=item.get("category", ""),
    )


def extract_items(data) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise SchemaChangedError(f"campo 'jobs' ausente: {str(data)[:120]}")
    return data["jobs"]


class RemotiveSource(Source):
    name = "remotive"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        queries = [("category", c) for c in self.cfg.get("categories", ["devops"])]
        queries += [("search", s) for s in self.cfg.get("searches", [])]
        for key, value in queries:
            def run(k=key, v=value):
                data = self.http.get_json(API_URL, params={k: v})
                return parse_many(extract_items(data), parse_job, self.name)
            self._safe(result, f"{key}={value}", run)
        return result
