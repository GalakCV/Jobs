"""Perfis de busca: cada perfil tem suas fontes e seus ajustes de filtro.

O config tem uma seção `filters` comum (áreas, senioridade...) e uma seção
`profiles`, em que cada perfil sobrescreve só o que muda (modalidade,
localização). Todos os perfis rodam na mesma execução e o resultado vai para
o mesmo banco e o mesmo relatório.

Configs sem `profiles` continuam funcionando: viram um perfil único com a
seção `filters` inteira e todas as fontes habilitadas.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from jobcrawler.filters import FilterConfig, FilterDecision, JobFilter
from jobcrawler.models import Job

DEFAULT_KEY = "padrao"


def deep_merge(base: dict, override: dict) -> dict:
    """Mescla dicionários recursivamente; listas e valores simples são substituídos."""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


@dataclass
class Profile:
    key: str
    label: str
    sources: list[str] | None      # None = todas as fontes habilitadas
    job_filter: JobFilter

    def uses(self, source: str) -> bool:
        return self.sources is None or source in self.sources

    def apply(self, job: Job) -> FilterDecision:
        decision = self.job_filter.apply(job)
        if decision.accepted:
            job.profile = self.key
        return decision


def build_profiles(cfg: dict, only: list[str] | None = None) -> list[Profile]:
    """Cria os perfis do config. `only` restringe a alguns perfis (--profile)."""
    base = cfg.get("filters") or {}
    raw = cfg.get("profiles") or {}
    if not raw:
        label = (cfg.get("report") or {}).get("title") or "Vagas"
        return [Profile(DEFAULT_KEY, label, None, JobFilter(FilterConfig.from_dict(base)))]

    unknown = set(only or []) - set(raw)
    if unknown:
        raise ValueError(f"Perfil inexistente: {', '.join(sorted(unknown))}. "
                         f"Perfis no config: {', '.join(raw)}")
    profiles = []
    for key, spec in raw.items():
        spec = spec or {}
        if only and key not in only:
            continue
        if spec.get("enabled") is False:
            continue
        try:
            filter_cfg = FilterConfig.from_dict(deep_merge(base, spec.get("filters") or {}))
        except ValueError as exc:
            raise ValueError(f"profiles.{key}: {exc}") from exc
        sources = spec.get("sources")
        profiles.append(Profile(key, spec.get("label") or key, list(sources) if sources else None,
                                JobFilter(filter_cfg)))
    if not profiles:
        raise ValueError("Nenhum perfil habilitado em 'profiles'")
    return profiles


def profile_labels(cfg: dict) -> dict[str, str]:
    """{chave: rótulo} de todos os perfis do config (para o relatório)."""
    raw = cfg.get("profiles") or {}
    if not raw:
        return {DEFAULT_KEY: (cfg.get("report") or {}).get("title") or "Vagas"}
    return {key: (spec or {}).get("label") or key for key, spec in raw.items()}


def evaluate_any(profiles: list[Profile], job: Job,
                 origin: str | None = None) -> tuple[Profile | None, FilterDecision]:
    """Avalia a vaga nos perfis (só nos que usam `origin`, se informado); o
    primeiro que aceitar vence. Se nenhum aceitar, devolve a decisão do
    primeiro perfil avaliado (o motivo mais útil)."""
    first: FilterDecision | None = None
    for profile in profiles:
        if origin is not None and not profile.uses(origin):
            continue
        decision = profile.apply(job)
        if decision.accepted:
            return profile, decision
        first = first or decision
    if first is None:
        first = FilterDecision(False, f"nenhum perfil usa a fonte '{origin}'", "profile")
    return None, first
