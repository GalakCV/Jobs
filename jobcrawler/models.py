"""Modelo de dados normalizado: toda fonte converte suas vagas para `Job`."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from jobcrawler.text import clean_ws, fingerprint


@dataclass
class Job:
    # --- campos obrigatórios, preenchidos pelo adaptador da fonte ---
    source: str                 # "himalayas", "remotive", ...
    title: str
    company: str
    url: str                    # link canônico na fonte (atribuição)

    # --- campos opcionais / enriquecidos ---
    location: str = ""          # texto livre informado pela fonte
    description: str = ""       # texto plano (HTML já removido)
    published_at: str | None = None   # ISO-8601 UTC
    tags: list[str] = field(default_factory=list)
    salary: str = ""
    source_level: str = ""      # senioridade declarada pela fonte, se houver
    source_category: str = ""
    timezone: str = ""          # fuso exigido (preenchido pela fonte ou extraído)

    # --- preenchidos pelo motor de filtros ---
    area: str = ""              # security | devops_sre_platform | infra_cloud_sysadmin
    regions: list[str] = field(default_factory=list)   # US, CA, AU, GLOBAL...
    junior_signal: str = ""     # o que tornou a vaga "explicitamente júnior"
    note: str = ""              # aviso para quem lê (ex.: "remoto não confirmado")

    def __post_init__(self) -> None:
        self.title = clean_ws(self.title)
        self.company = clean_ws(self.company) or "(não informado)"
        self.location = clean_ws(self.location)
        self.url = (self.url or "").strip()

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.title, self.company)

    def is_valid(self) -> bool:
        """Uma vaga sem título ou link não serve para nada."""
        return bool(self.title and self.url.startswith(("http://", "https://")))

    def to_record(self, excerpt_chars: int = 400) -> dict:
        """Representação plana para CSV/JSON/SQLite (descrição resumida)."""
        data = asdict(self)
        data["description"] = self.description[:excerpt_chars]
        data["tags"] = ", ".join(self.tags)
        data["regions"] = ", ".join(self.regions)
        data["fingerprint"] = self.fingerprint
        return data
