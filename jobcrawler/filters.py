"""Motor de filtragem: área (whitelist), senioridade (júnior explícito +
blacklist), modalidade (híbrido / presencial / remoto), localização e idade.

Cada vaga recebe um `FilterDecision` com o motivo exato do aceite ou descarte,
o que permite auditar o filtro com `--explain` (gera rejections.csv).

Ordem das verificações (a primeira reprovação encerra):
  1. Idade da vaga
  2. Modalidade (ex.: só híbrido) - campo da fonte, título/local ou descrição
  3. Área pelo título (+ exclusões como "Segurança do Trabalho")
  4. Blacklist de senioridade no TÍTULO          <- regra crítica
  5. Nível declarado pela fonte (Pleno/Sênior/Estágio => descarta)
  6. Descrição: frases de nível / anos de experiência (ou modo strict)
  7. Marcador júnior explícito (título, fonte ou, se habilitado, descrição)
  8. Localização: cidades-alvo (modo "cities") ou regiões US/CA/AU/Global
     (modo "regions", usado pelo perfil remoto)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobcrawler.models import Job
from jobcrawler.text import age_in_days, extract_timezones, fold

# Limites de palavra que também tratam pontuação: "sr" não casa em "sre",
# "intern" não casa em "internal", mas "sr." casa em "Sr. Engineer".
_B = r"(?<![a-z0-9])"
_E = r"(?![a-z0-9])"


def compile_terms(terms: list[str]) -> re.Pattern | None:
    """Compila uma lista de fragmentos regex em um único padrão com limites de palavra."""
    for term in terms or []:
        if not isinstance(term, str):
            # Ex.: "abc(?: x)" sem aspas no YAML vira um dicionário
            raise ValueError(f"Termo inválido no config (use aspas no YAML): {term!r}")
        try:
            re.compile(term)
        except re.error as exc:
            raise ValueError(f"Regex inválida no config: {term!r} ({exc})") from exc
    terms = [t for t in (terms or []) if t.strip()]
    if not terms:
        return None
    return re.compile(_B + "(?:" + "|".join(f"(?:{t})" for t in terms) + ")" + _E)


# ---------------------------------------------------------------------------
# Anos de experiência
# ---------------------------------------------------------------------------
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
              "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "um": 1, "dois": 2, "tres": 3, "quatro": 4, "cinco": 5}
_NUM = r"(\d{1,2}|" + "|".join(_NUM_WORDS) + r")"
_YEARS = r"(?:years?|yrs?|anos?)"
# Exige uma palavra de "experiência" logo depois (na mesma frase), para não
# confundir com "founded 10 years ago" ou "2 years of runway".
_EXP_CONTEXT = r"(?:experience|exp|experiencia|vivencia|atuacao|background|track record)" + _E

_YEARS_PATTERNS = [
    # "3-5 years of experience", "3 to 5 years of hands-on experience"
    re.compile(_B + _NUM + r"\s*\+?\s*(?:-|–|to|a)\s*" + _NUM + r"\s*\+?\s*" + _YEARS
               + r"[^.;\n]{0,60}?" + _EXP_CONTEXT),
    # "5+ years of experience", "3 years' professional experience", "5 anos de experiencia"
    re.compile(_B + _NUM + r"\s*(?:\+|plus)?\s*" + _YEARS + r"(?:'|’)?[^.;\n]{0,60}?" + _EXP_CONTEXT),
    # "minimum of 4 years", "at least 3 years", "no minimo 3 anos"
    re.compile(r"(?:minimum(?: of)?|at least|no minimo|pelo menos|min\.)\s*" + _NUM + r"\s*\+?\s*" + _YEARS),
    # "experiencia minima de 3 anos", "experiencia comprovada de 2 anos"
    re.compile(r"(?:experiencia|vivencia)\s+(?:\w+\s+){0,2}?de\s+" + _NUM + r"\s*\+?\s*" + _YEARS),
]


def _to_int(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


def required_years(text: str) -> int | None:
    """Maior mínimo de anos de experiência exigido no texto (já "dobrado").

    Usa o MAIOR valor encontrado (postura conservadora, alinhada à regra
    rígida): "1+ year of Linux and 5+ years overall" => 5.
    Faixas usam o limite inferior: "3-5 years" => 3.
    """
    best: int | None = None
    work = text
    for idx, pattern in enumerate(_YEARS_PATTERNS):
        for match in pattern.finditer(work):
            value = _to_int(match.group(1))
            if value is None or value > 30:  # "founded 50 years ago" etc.
                continue
            best = value if best is None else max(best, value)
        if idx == 0:
            # Apaga as faixas já lidas ("3-5 years") para que o "5 years" dentro
            # delas não seja contado de novo pelo padrão seguinte.
            work = pattern.sub(lambda m: " " * len(m.group(0)), work)
    return best


# ---------------------------------------------------------------------------
# Localização
# ---------------------------------------------------------------------------
_US_STATES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    "georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|"
    "massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|"
    "new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|"
    "oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|"
    "texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|"
    "district of columbia"
)
_US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}
_REGION_PATTERNS: dict[str, re.Pattern] = {
    # Inclui grafias em português/espanhol: sites como o LinkedIn localizam o
    # texto pelo idioma do navegador ("Estados Unidos", "Ilinóis", "Tenessi").
    "US": re.compile(_B + r"(?:united states|usa|u\.s\.a?\.?|us|estados unidos|eua|ee\.?\s?uu\.?|"
                     r"(?<!latin )(?<!south )(?<!central )america|" + _US_STATES + r"|"
                     r"tenessi|minesota|ilinois|pensilvania|carolina do (?:norte|sul)|"
                     r"nova (?:iorque|jersey)|luisiana|havai|distrito de columbia)" + _E),
    "CA": re.compile(_B + r"(?:canada|canadian|ontario|toronto|vancouver|british columbia|"
                     r"quebec|alberta|montreal|calgary|ottawa)" + _E),
    "AU": re.compile(_B + r"(?:australia|australian|aus|sydney|melbourne|brisbane|perth|"
                     r"adelaide|canberra|anz|oceania)" + _E),
    "NA": re.compile(_B + r"(?:north america|america do norte|americas|us\s*(?:/|&|and|or)\s*canada)" + _E),
    "APAC": re.compile(_B + r"(?:apac|asia[- ]pacific)" + _E),
    "GLOBAL": re.compile(_B + r"(?:worldwide|anywhere|global|globally|international|"
                         r"all countries|any location|no location restrictions?|"
                         r"remote anywhere|work from anywhere|"
                         r"mundo todo|qualquer lugar|global remoto|todo el mundo)" + _E),
}
_STATE_CODE_SUFFIX = re.compile(r",\s*([A-Z]{2})\b")


def classify_regions(location: str, accept_apac_as_au: bool = True) -> list[str]:
    """Classifica a localização em regiões: US, CA, AU, GLOBAL (ou OTHER / UNKNOWN)."""
    original = location or ""
    text = fold(original)
    # remove palavras que não informam região ("Remote - USA" -> "usa")
    stripped = re.sub(_B + r"(?:remote|remotely|fully|100%|only|based|from|in|or|and)" + _E,
                      " ", text)
    stripped = re.sub(r"[^a-z0-9]+", " ", stripped).strip()
    if not stripped:
        return ["UNKNOWN"]

    regions: list[str] = []
    if _REGION_PATTERNS["NA"].search(text):
        regions += ["US", "CA"]
    for code in ("US", "CA", "AU", "GLOBAL"):
        if _REGION_PATTERNS[code].search(text):
            regions.append(code)
    if accept_apac_as_au and _REGION_PATTERNS["APAC"].search(text):
        regions.append("AU")
    # "Austin, TX" / "Denver, CO" -> US (sigla de estado em maiúsculas)
    if any(code in _US_STATE_CODES for code in _STATE_CODE_SUFFIX.findall(original)):
        regions.append("US")

    return list(dict.fromkeys(regions)) or ["OTHER"]


# ---------------------------------------------------------------------------
# Modalidade (híbrido / presencial / remoto)
# ---------------------------------------------------------------------------
WORKPLACE_LABELS = {"hybrid": "Híbrido", "onsite": "Presencial", "remote": "Remoto"}

# Título, local e labels: a palavra sozinha basta. Exceções para "nuvem
# híbrida" / "hybrid cloud", que descrevem tecnologia e não o regime.
_WP_TITLE = [
    ("hybrid", re.compile(r"(?<!nuvem )(?<!nuvens )(?<!ambiente )(?<!ambientes )"
                          r"(?<!infraestrutura )" + _B + r"(?:hibrid[oa]s?|hybrid|semi[- ]?presencial)"
                          + r"(?!\s*(?:cloud|it|infra\w*|environment|multi\w*))" + _E)),
    ("onsite", re.compile(_B + r"(?:presencial|on[- ]?site|in[- ]office|onsite)" + _E)),
    ("remote", re.compile(_B + r"(?:remot[oa]s?|remote|home[- ]?office|anywhere|teletrabalho)" + _E)),
]
# Descrição: exige contexto de regime de trabalho ("modelo híbrido",
# "3x por semana no escritório"), porque "híbrido" e "remoto" aparecem
# em contextos técnicos ("acesso remoto", "ambientes híbridos").
_CTX = r"(?:modelo|regime|formato|modalidade|trabalho|jornada|atuacao|vaga|posicao|work|role|position|schedule)"
_WP_DESC = [
    ("hybrid", re.compile(
        _B + _CTX + r"\s+(?:de\s+trabalho\s+|\w+\s+)?(?:e\s+)?hibrid[oa]" + _E
        + r"|" + _B + r"hybrid\s+(?:work|role|position|schedule|model|working|setup)" + _E
        + r"|" + _B + r"\d\s*(?:x|vezes|dias?)\s*(?:por\s+semana|na\s+semana|semanais)?\s*"
                      r"(?:no|na|ao|em)?\s*(?:escritorio|presencial|office)"
        + r"|" + _B + r"(?:hibrid[oa])\s*\(\s*\d")),
    ("onsite", re.compile(
        r"100%\s*presencial|" + _B + _CTX + r"\s+(?:de\s+trabalho\s+)?(?:100%\s*)?presencial" + _E
        + r"|" + _B + r"(?:fully\s+)?on[- ]?site\s+(?:role|position|work)" + _E)),
    ("remote", re.compile(
        r"100%\s*remot[oa]|" + _B + _CTX + r"\s+(?:de\s+trabalho\s+)?(?:100%\s*)?remot[oa]" + _E
        + r"|" + _B + r"(?:fully\s+remote|remote[- ]first)" + _E)),
]
_WP_FIELD = {"hybrid": "hybrid", "hibrido": "hybrid", "on-site": "onsite", "onsite": "onsite",
             "on_site": "onsite", "presencial": "onsite", "remote": "remote", "remoto": "remote"}


def normalize_workplace(value: str | None) -> str:
    """Normaliza valores de campos estruturados ('on-site', 'Híbrido'...)."""
    return _WP_FIELD.get(fold(value or "").replace(" ", ""), "")


def detect_workplace(job: Job, use_description: bool = True) -> tuple[str, str]:
    """Retorna (modalidade, de_onde_veio). Ordem de confiança:
    campo da fonte > título/local/labels > descrição > indício da busca."""
    if wp := normalize_workplace(job.workplace):
        return wp, "fonte"
    strong_text = fold(" | ".join([job.title, job.location, " ".join(job.tags)]))
    for wp, pattern in _WP_TITLE:
        if pattern.search(strong_text):
            return wp, "título/local"
    if use_description and job.description:
        desc = fold(job.description)
        for wp, pattern in _WP_DESC:
            if pattern.search(desc):
                return wp, "descrição"
    if wp := normalize_workplace(job.workplace_hint):
        return wp, "indício"
    return "", ""


# ---------------------------------------------------------------------------
# Cidades (modo "cities")
# ---------------------------------------------------------------------------
_LOC_SPLIT = re.compile(r"\s*(?:,|/|\||;|\(|\)|\[|\]|\s[-–]\s|\s+e\s+regiao|\s+metropolitan\w*)\s*")
_LOC_NOISE = {"brasil", "brazil", "br", "remoto", "remote", "hibrido", "hybrid", "presencial",
              "on-site", "onsite", "e regiao", "regiao", "area", "grande", ""}


class CityMatcher:
    """Decide se uma localização está nas cidades-alvo.

    Regras, aplicadas aos trechos do texto em ordem ("Niterói, RJ, Brasil"):
      * trecho que é cidade-alvo, bairro/apelido ou cidade metropolitana -> casa;
      * o nome do estado ("Rio de Janeiro") só conta como CIDADE se for o
        primeiro trecho com significado. "Volta Redonda, Rio de Janeiro"
        é outra cidade do estado e NÃO casa;
      * só a sigla/nome do estado, sem cidade -> "cidade não informada".
    """

    def __init__(self, cities: dict[str, list[str]], metro: list[str], include_metro: bool,
                 state_names: list[str], state_label: str):
        self.lookup: dict[str, str] = {}
        for city, aliases in (cities or {}).items():
            for name in [city, *(aliases or [])]:
                self.lookup[fold(name)] = city
        if include_metro:
            for city in metro or []:
                self.lookup.setdefault(fold(city), city)
        self.state_names = {fold(n) for n in state_names or []}
        self.state_label = state_label

    def match(self, location: str) -> tuple[str, str]:
        """Retorna (status, rótulo): ('city', 'Niterói'), ('state', 'RJ'),
        ('unknown', '') ou ('other', 'São Paulo')."""
        parts = [p for p in (x.strip(" .") for x in _LOC_SPLIT.split(fold(location)))
                 if p not in _LOC_NOISE]
        if not parts:
            return "unknown", ""
        seen_other = False
        only_state = True
        for part in parts:
            if part in self.lookup and not (seen_other and part in self.state_names):
                return "city", self.lookup[part]
            if part in self.state_names:
                continue
            only_state = False
            seen_other = True
        if only_state:
            return "state", self.state_label
        return "other", parts[0].title()


# ---------------------------------------------------------------------------
# Configuração e decisão
# ---------------------------------------------------------------------------
@dataclass
class FilterConfig:
    areas: dict[str, list[str]] = field(default_factory=dict)
    title_area_exclusions: list[str] = field(default_factory=list)
    junior_markers: list[str] = field(default_factory=list)
    accept_roman_one: bool = True
    seniority_blacklist: list[str] = field(default_factory=list)
    description_mode: str = "smart"
    max_years_experience: int = 2
    description_reject_phrases: list[str] = field(default_factory=list)
    junior_marker_in_description: bool = False
    trust_source_seniority: bool = True
    require_junior_marker: bool = True
    # --- modalidade ---
    workplace_types: list[str] = field(default_factory=lambda: ["remote"])
    unknown_workplace: str = "keep"          # keep (com aviso) | reject
    workplace_from_description: bool = True
    # --- localização ---
    location_mode: str = "regions"           # regions (US/CA/AU/Global) | cities
    accepted_regions: list[str] = field(default_factory=lambda: ["US", "CA", "AU", "GLOBAL"])
    accept_apac_as_au: bool = True
    target_cities: dict[str, list[str]] = field(default_factory=dict)
    metro_cities: list[str] = field(default_factory=list)
    include_metro: bool = True
    target_state: dict = field(default_factory=dict)   # {label: RJ, names: [...]}
    accept_state_only: bool = True
    allow_unknown_location: bool = True
    reject_onsite_terms: list[str] = field(default_factory=list)   # legado, ignorado
    max_age_days: int = 30

    @classmethod
    def from_dict(cls, data: dict | None) -> "FilterConfig":
        data = data or {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        if cfg.description_mode not in ("smart", "strict"):
            raise ValueError("filters.description_mode deve ser 'smart' ou 'strict'")
        if not cfg.areas:
            raise ValueError("filters.areas está vazio: nenhuma vaga passaria no filtro")
        if not cfg.seniority_blacklist:
            raise ValueError("filters.seniority_blacklist está vazio (filtro crítico)")
        bad = set(cfg.workplace_types) - set(WORKPLACE_LABELS)
        if bad or not cfg.workplace_types:
            raise ValueError("filters.workplace_types aceita: hybrid, onsite, remote")
        if cfg.unknown_workplace not in ("keep", "reject"):
            raise ValueError("filters.unknown_workplace deve ser 'keep' ou 'reject'")
        if cfg.location_mode not in ("regions", "cities"):
            raise ValueError("filters.location_mode deve ser 'regions' ou 'cities'")
        if cfg.location_mode == "cities" and not cfg.target_cities:
            raise ValueError("filters.target_cities está vazio no modo 'cities'")
        return cfg


@dataclass
class FilterDecision:
    accepted: bool
    reason: str
    stage: str
    area: str = ""
    junior_signal: str = ""
    regions: list[str] = field(default_factory=list)
    workplace: str = ""
    notes: list[str] = field(default_factory=list)


# Nível declarado por fontes (Himalayas, Jobicy, ...)
_SOURCE_REJECT = re.compile(_B + r"(?:mid|midweight|mid[- ]level|senior|sr|lead|manager|"
                            r"director|executive|principal|staff|intern|internship|"
                            r"pleno|especialista|estagio|estagiario|trainee|aprendiz|"
                            r"banco de talentos|talent pool|summer)" + _E)
_SOURCE_JUNIOR = re.compile(_B + r"(?:entry[- ]?level|entry|junior|jr|graduate|assistente)" + _E)
_DESC_JUNIOR = re.compile(r"(?:this is an?|hiring an?|for an?|seeking an?|looking for an?)\s+"
                          r"(?:junior|entry[- ]level)\b")
_ROMAN_ONE = re.compile(r"\b(?:Engineer|Analyst|Administrator|Admin|Technician|Specialist|"
                        r"Associate|Developer|Operator)\s+I\b(?!\s*[IVX])"
                        # "Analista de Infraestrutura I", "Técnico de Suporte I - Híbrido"
                        r"|(?<=[a-zà-ú])\s+I(?=\s*(?:$|[-–(),/|]))")


class JobFilter:
    def __init__(self, cfg: FilterConfig):
        self.cfg = cfg
        self.area_patterns = {name: compile_terms(terms) for name, terms in cfg.areas.items()}
        self.area_exclusions = compile_terms(cfg.title_area_exclusions)
        self.junior = compile_terms(cfg.junior_markers)
        self.blacklist = compile_terms(cfg.seniority_blacklist)
        self.desc_phrases = compile_terms(cfg.description_reject_phrases)
        self.cities = None
        if cfg.location_mode == "cities":
            state = cfg.target_state or {}
            self.cities = CityMatcher(cfg.target_cities, cfg.metro_cities, cfg.include_metro,
                                      state.get("names", []), state.get("label", ""))

    # ------------------------------------------------------------------
    def evaluate(self, job: Job) -> FilterDecision:
        title = fold(job.title)
        description = fold(job.description)

        # 1. Idade -------------------------------------------------------
        if self.cfg.max_age_days:
            age = age_in_days(job.published_at)
            if age is not None and age > self.cfg.max_age_days:
                return self._no("age", f"publicada há {age:.0f} dias (> {self.cfg.max_age_days})")

        # 2. Modalidade ----------------------------------------------------
        notes: list[str] = []
        workplace, origin = detect_workplace(job, self.cfg.workplace_from_description)
        allowed = " ou ".join(WORKPLACE_LABELS[w].lower() for w in self.cfg.workplace_types)
        if workplace and workplace not in self.cfg.workplace_types:
            return self._no("workplace", f"é {WORKPLACE_LABELS[workplace].lower()} "
                                         f"({origin}), procurando {allowed}")
        if not workplace:
            if self.cfg.unknown_workplace == "reject":
                return self._no("workplace", "modalidade não informada")
            if self.cfg.workplace_types != ["remote"]:
                # em sites só de vagas remotas, "não informado" significa remoto
                notes.append("Modalidade não informada; confira se é "
                             f"{allowed} antes de se candidatar.")
        elif origin == "indício":
            notes.append(f"{WORKPLACE_LABELS[workplace]} segundo o filtro de busca da fonte, "
                         "que nem sempre acerta; confira na vaga.")

        # 3. Área ----------------------------------------------------------
        if self.area_exclusions and (m := self.area_exclusions.search(title)):
            return self._no("area", f"título fora da área ('{m.group(0)}')")
        area = next((name for name, pat in self.area_patterns.items()
                     if pat and pat.search(title)), "")
        if not area:
            return self._no("area", "título não pertence a DevOps/Security/Infra")

        # 4. Blacklist de senioridade no título (CRÍTICO) -------------------
        if m := self.blacklist.search(title):
            return self._no("seniority_title", f"título contém termo proibido '{m.group(0)}'", area)

        # 5. Nível declarado pela fonte --------------------------------------
        source_level = fold(job.source_level)
        if source_level and (m := _SOURCE_REJECT.search(source_level)):
            return self._no("seniority_source", f"fonte classifica como '{job.source_level}'", area)

        # 6. Descrição -----------------------------------------------------
        if description:
            if self.cfg.description_mode == "strict":
                if m := self.blacklist.search(description):
                    return self._no("seniority_description",
                                    f"[strict] descrição contém '{m.group(0)}'", area)
            elif self.desc_phrases and (m := self.desc_phrases.search(description)):
                return self._no("seniority_description",
                                f"descrição indica outro nível ('{m.group(0)}')", area)
            years = required_years(description)
            if years is not None and years > self.cfg.max_years_experience:
                return self._no("experience", f"exige {years}+ anos de experiência", area)

        # 7. Marcador júnior explícito ------------------------------------
        signal = ""
        if m := self.junior.search(title):
            signal = f"título: '{m.group(0)}'"
        elif self.cfg.accept_roman_one and (m := _ROMAN_ONE.search(job.title)):
            signal = f"título: '{m.group(0).strip()}'"
        elif self.cfg.trust_source_seniority and source_level and _SOURCE_JUNIOR.search(source_level):
            signal = f"fonte: '{job.source_level}'"
        elif self.cfg.junior_marker_in_description and (m := _DESC_JUNIOR.search(description)):
            signal = f"descrição: '{m.group(0)}'"
        if not signal:
            if self.cfg.require_junior_marker:
                return self._no("junior_marker", "não é explicitamente júnior", area)
            signal = "nível não informado"
            notes.append("Nível não informado no título; confira se aceita júnior.")

        # 8. Localização ---------------------------------------------------
        if self.cities is not None:
            status, label = self.cities.match(job.location)
            if status == "city":
                regions = [label]
            elif status == "state" and self.cfg.accept_state_only:
                regions = [f"{label} (cidade não informada)"]
                notes.append("Só o estado foi informado; confira a cidade.")
            elif status == "unknown" and self.cfg.allow_unknown_location:
                regions = ["NÃO INFORMADO"]
                notes.append("Localização não informada; confira.")
            else:
                where = f"'{job.location}'" if job.location else "não informada"
                return self._no("region", f"localização fora do escopo ({where})", area)
        else:
            regions = classify_regions(job.location, self.cfg.accept_apac_as_au)
            if regions == ["UNKNOWN"]:
                if not self.cfg.allow_unknown_location:
                    return self._no("region", "localização não informada", area)
                regions = ["NÃO INFORMADO"]
            elif not set(regions) & set(self.cfg.accepted_regions):
                return self._no("region", f"região fora do escopo ('{job.location}')", area)
            regions = [r for r in regions if r != "OTHER"]

        if not workplace and self.cfg.workplace_types == ["remote"]:
            workplace = "remote"
        return FilterDecision(True, "ok", "accepted", area=area, junior_signal=signal,
                              regions=regions, workplace=workplace, notes=notes)

    # ------------------------------------------------------------------
    def apply(self, job: Job) -> FilterDecision:
        """Avalia e, se aceita, enriquece a vaga com área, regiões e fuso."""
        decision = self.evaluate(job)
        if decision.accepted:
            job.area = decision.area
            job.regions = decision.regions
            job.junior_signal = decision.junior_signal
            job.workplace = decision.workplace
            for note in decision.notes:
                job.add_note(note)
            # Fusos só fazem sentido para vagas remotas internacionais; em
            # português, "PT" (idioma) seria lido como Pacific Time.
            if not job.timezone and self.cfg.location_mode == "regions":
                job.timezone = extract_timezones(job.location, job.description)
        return decision

    @staticmethod
    def _no(stage: str, reason: str, area: str = "") -> FilterDecision:
        return FilterDecision(False, reason, stage, area=area)
