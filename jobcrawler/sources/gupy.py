"""Gupy - API pública do portal de vagas (https://portal.gupy.io).

Endpoint: GET https://portal.api.gupy.io/api/v1/jobs?jobName=<termo>&limit=&offset=
Resposta: {"data": [vaga, ...], "pagination": {"offset", "limit", "total"}}

Campos usados (com nomes alternativos, caso a API mude):
  name/title, careerPageName/companyName, city, state, workplaceType
  ("hybrid", "remote", "on-site"), isRemoteWork, type ("vacancy_type_effective",
  "vacancy_type_internship", ...), publishedDate, jobUrl, description.

A modalidade vem de um campo estruturado, então é tratada como confiável.
"""

from __future__ import annotations

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import html_to_text, parse_date

API_URL = "https://portal.api.gupy.io/api/v1/jobs"

# Tipo de vaga do Gupy -> rótulo legível (vira `source_level`, que o filtro lê).
# Estágio, trainee, aprendiz e banco de talentos são descartados pelo filtro.
VACANCY_TYPES = {
    "vacancy_type_internship": "Estágio",
    "vacancy_type_summer": "Estágio (summer)",
    "vacancy_type_trainee": "Trainee",
    "vacancy_type_apprentice": "Jovem aprendiz",
    "vacancy_type_young_apprentice": "Jovem aprendiz",
    "vacancy_type_talent_pool": "Banco de talentos",
}
WORKPLACE = {"hybrid": "hybrid", "remote": "remote", "on-site": "onsite", "onsite": "onsite"}


def _first(item: dict, *keys: str):
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _location(item: dict) -> str:
    city = (_first(item, "city", "jobCity") or "").strip()
    state = (_first(item, "state", "jobState") or "").strip()
    if city:
        return ", ".join(p for p in (city, state) if p)
    # Sem cidade: deixa claro que só o estado é conhecido, para o filtro não
    # confundir "Rio de Janeiro" (estado) com a cidade.
    return f"Estado do {state}" if state else ""


def parse_job(item: dict) -> Job:
    workplace = WORKPLACE.get(str(item.get("workplaceType") or "").lower(), "")
    if not workplace and item.get("isRemoteWork") is True:
        workplace = "remote"
    vacancy_type = str(item.get("type") or "")
    return Job(
        source="gupy",
        title=_first(item, "name", "title"),
        company=_first(item, "careerPageName", "companyName", "company") or "",
        url=_first(item, "jobUrl", "url", "careerPageUrl") or "",
        location=_location(item),
        description=html_to_text(item.get("description")),
        published_at=parse_date(_first(item, "publishedDate", "publishedAt", "createdAt")),
        workplace=workplace,
        source_level=VACANCY_TYPES.get(vacancy_type, ""),
        source_category=vacancy_type,
        tags=[s for s in (item.get("skills") or []) if isinstance(s, str)][:8],
    )


def extract_page(data) -> tuple[list[dict], int | None]:
    """Retorna (vagas, total) e acusa mudança de formato da resposta."""
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        total = (data.get("pagination") or {}).get("total")
        return data["data"], total if isinstance(total, int) else None
    if isinstance(data, list):
        return data, None
    keys = list(data)[:10] if isinstance(data, dict) else type(data).__name__
    raise SchemaChangedError(f"esperava {{'data': [...]}}, veio {keys}")


class GupySource(Source):
    name = "gupy"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        page_size = int(self.cfg.get("page_size", 50))
        max_pages = int(self.cfg.get("max_pages", 4))
        extra = dict(self.cfg.get("extra_params") or {})
        for query in self.cfg.get("queries", ["devops"]):
            def run(q=query):
                jobs: list[Job] = []
                for page in range(max_pages):
                    params = {"jobName": q, "limit": page_size, "offset": page * page_size, **extra}
                    items, total = extract_page(self.http.get_json(API_URL, params=params))
                    if not items:
                        break
                    jobs += parse_many(items, parse_job, self.name)
                    fetched = (page + 1) * page_size
                    if len(items) < page_size or (total is not None and fetched >= total):
                        break
                return jobs
            self._safe(result, f"jobName={query}", run)
        return result
