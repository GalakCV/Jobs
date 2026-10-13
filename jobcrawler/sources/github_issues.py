"""Repositórios de vagas no GitHub (cada issue é uma vaga), ex.: backend-br/vagas.

API: GET https://api.github.com/repos/{owner}/{repo}/issues?state=open
Sem token: 60 requisições/hora por IP. Com GITHUB_TOKEN no .env: 5000/hora.

Convenção comum dos títulos: "[Rio de Janeiro] Analista DevOps Júnior na Empresa X".
  * colchetes  -> localização e/ou modalidade
  * " na/no/@ " -> empresa
  * labels     -> modalidade (Híbrido/Remoto/Presencial) e nível (Júnior/Pleno/
                  Sênior/Estagiário/Especialista)
"""

from __future__ import annotations

import os
import re

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import clean_ws, fold, parse_date

API_URL = "https://api.github.com/repos/{repo}/issues"

_BRACKETS = re.compile(r"\[([^\]]+)\]")
_COMPANY = re.compile(r"\s+(?:na|no|@|at)\s+(?=\S)", re.IGNORECASE)
_LOCAL_LINE = re.compile(r"^\W*(?:local(?:iza[cç][aã]o)?|cidade|location)\s*[:\-–]\s*(.+)$",
                         re.IGNORECASE | re.MULTILINE)

WORKPLACE_LABELS = {"hibrido": "hybrid", "remoto": "remote", "presencial": "onsite"}
LEVEL_LABELS = {"junior": "Júnior", "pleno": "Pleno", "senior": "Sênior", "estagiario": "Estágio",
                "estagio": "Estágio", "especialista": "Especialista", "trainee": "Trainee"}
# Palavras que aparecem em colchetes mas não são lugar
_NOT_PLACE = {"hibrido", "remoto", "presencial", "clt", "pj", "freela", "freelance",
              "junior", "pleno", "senior", "estagio", "estagiario", "urgente"}


_COMPANY_TAIL = re.compile(r"\s+(?:-|–|\||em|no|na)\s+", re.IGNORECASE)


def _split_title(raw: str) -> tuple[str, str, list[str]]:
    """'[RJ] Analista DevOps Jr na Acme - Niterói'
    -> ('Analista DevOps Jr', 'Acme', ['RJ', 'Niterói'])."""
    places = [clean_ws(b) for b in _BRACKETS.findall(raw)]
    title = clean_ws(_BRACKETS.sub(" ", raw)).strip(" -–|:")
    company = ""
    parts = _COMPANY.split(title, maxsplit=1)
    if len(parts) == 2:
        title = parts[0].strip(" -–|:")
        # "Banco X - Rio de Janeiro" / "Empresa no Rio": o resto vira local
        company, *tail = _COMPANY_TAIL.split(parts[1].strip(" -–|:"))
        places += [t.strip(" -–|:") for t in tail if t.strip(" -–|:")]
    return title, company.strip(), places


def parse_issue(issue: dict) -> Job | None:
    if "pull_request" in issue:          # a API de issues também lista PRs
        return None
    title, company, places = _split_title(issue["title"])
    labels = [lbl["name"] if isinstance(lbl, dict) else str(lbl) for lbl in issue.get("labels") or []]
    folded_labels = [fold(lbl) for lbl in labels]

    workplace = next((WORKPLACE_LABELS[lbl] for lbl in folded_labels if lbl in WORKPLACE_LABELS), "")
    level = next((LEVEL_LABELS[lbl] for lbl in folded_labels if lbl in LEVEL_LABELS), "")

    modifiers = [p for p in places if fold(p) in _NOT_PLACE]   # "[Híbrido]", "[CLT]"
    places = [p for p in places if fold(p) not in _NOT_PLACE]
    body = issue.get("body") or ""
    if m := _LOCAL_LINE.search(body):
        places.append(clean_ws(m.group(1))[:80])

    return Job(
        source="github",
        title=title,
        company=company,
        url=issue["html_url"],
        # Colchetes de modalidade ficam no texto do título original, então
        # o filtro também os enxerga pelas tags.
        location=" / ".join(places),
        description=clean_ws(body)[:6000],
        published_at=parse_date(issue.get("created_at")),
        tags=labels + modifiers,
        workplace=workplace,
        source_level=level,
        source_category=issue.get("repository_url", "").rsplit("/repos/", 1)[-1],
    )


class GitHubIssuesSource(Source):
    name = "github_issues"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token := os.getenv("GITHUB_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        max_pages = int(self.cfg.get("max_pages", 3))
        for repo in self.cfg.get("repos", []):
            def run(r=repo):
                jobs: list[Job] = []
                for page in range(1, max_pages + 1):
                    data = self.http.get_json(
                        API_URL.format(repo=r), headers=headers,
                        params={"state": "open", "per_page": 100, "page": page,
                                "sort": "created", "direction": "desc"})
                    if not isinstance(data, list):
                        raise SchemaChangedError(f"esperava lista de issues: {str(data)[:120]}")
                    if not data:
                        break
                    issues = [i for i in data if isinstance(i, dict) and "pull_request" not in i]
                    for job in parse_many(issues, parse_issue, self.name):
                        job.source = f"github:{r}"
                        jobs.append(job)
                    if len(data) < 100:
                        break
                return jobs
            self._safe(result, repo, run)
        return result
