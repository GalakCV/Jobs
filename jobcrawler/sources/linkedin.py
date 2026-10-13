"""LinkedIn - endpoint "guest" de busca (HTML). OPCIONAL e DESLIGADO por padrão.

AVISO: os Termos de Uso do LinkedIn proíbem coleta automatizada, e o site
bloqueia IPs (HTTP 429/999) com facilidade. Este adaptador existe para uso
pessoal, em volume mínimo, e NÃO tenta contornar bloqueios: ao primeiro sinal
de bloqueio a fonte é desativada até a próxima execução.

Limitação: a busca guest não traz a descrição, então o filtro de anos de
experiência não se aplica a vagas do LinkedIn (só título e localização).

Parâmetros (configuráveis): f_WT = modalidade (1 presencial, 2 remoto,
3 híbrido) e f_E = nível (1 estágio, 2 "Assistente"/Entry level, 3 "Júnior"/
Associate). O filtro de modalidade do LinkedIn falha com frequência, por isso
ele vira só um indício (`workplace_hint`) e a vaga recebe aviso no relatório.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult
from jobcrawler.text import clean_ws, parse_date

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
PAGE_SIZE = 25

# Vários seletores por campo: se o LinkedIn mudar uma classe, tentamos a próxima.
SELECTORS = {
    "card": ["div.base-card", "div.job-search-card", "li"],
    "title": ["h3.base-search-card__title", "h3"],
    "company": ["h4.base-search-card__subtitle", "a.hidden-nested-link", "h4"],
    "location": ["span.job-search-card__location", "span[class*=location]"],
    "link": ["a.base-card__full-link", "a[href*='/jobs/view/']"],
}


def _first(node, selectors: list[str]):
    for sel in selectors:
        found = node.select_one(sel)
        if found is not None:
            return found
    return None


_WT_CODES = {1: "onsite", 2: "remote", 3: "hybrid"}


def parse_cards(html: str, workplace_hint: str = "", level: str = "") -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for sel in SELECTORS["card"]:
        cards = soup.select(sel)
        if cards:
            break
    jobs: list[Job] = []
    for card in cards:
        title = _first(card, SELECTORS["title"])
        link = _first(card, SELECTORS["link"])
        if title is None or link is None:
            continue
        company = _first(card, SELECTORS["company"])
        location = _first(card, SELECTORS["location"])
        time_tag = card.select_one("time[datetime]")
        jobs.append(Job(
            source="linkedin",
            title=clean_ws(title.get_text()),
            company=clean_ws(company.get_text()) if company else "",
            url=(link.get("href") or "").split("?")[0],
            location=clean_ws(location.get_text()) if location else "",
            published_at=parse_date(time_tag["datetime"]) if time_tag else None,
            source_level=level,
            workplace_hint=workplace_hint,
        ))
    if html.strip() and cards and not jobs:
        raise SchemaChangedError("cards encontrados mas nenhum campo extraído (DOM mudou?)")
    return jobs


class LinkedInSource(Source):
    name = "linkedin"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        delay = float(self.cfg.get("min_delay_seconds", 6))
        max_pages = int(self.cfg.get("max_pages", 2))
        wt = [int(x) for x in self.cfg.get("workplace", [2])]
        levels = [int(x) for x in self.cfg.get("experience_levels", [2])]
        # Só dá para atribuir modalidade/nível às vagas quando a busca usa um único valor
        hint = _WT_CODES.get(wt[0], "") if len(wt) == 1 else ""
        level = "Entry level" if levels == [2] else ""
        for location in self.cfg.get("locations", ["United States"]):
            for keywords in self.cfg.get("keywords", []):
                def run(kw=keywords, loc=location):
                    jobs: list[Job] = []
                    for page in range(max_pages):
                        params = {"keywords": kw, "location": loc,
                                  "f_WT": ",".join(map(str, wt)), "f_E": ",".join(map(str, levels)),
                                  "start": page * PAGE_SIZE}
                        html = self.http.get_text(SEARCH_URL, params=params, min_interval=delay)
                        page_jobs = parse_cards(html, hint, level)
                        jobs += page_jobs
                        if len(page_jobs) < PAGE_SIZE:
                            break
                    return jobs
                self._safe(result, f"{keywords} @ {location}", run)
        return result
