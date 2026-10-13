"""Perfil padrão (config.yaml): vagas HÍBRIDAS júnior no Rio de Janeiro."""

import pytest

from jobcrawler.filters import CityMatcher, FilterConfig, JobFilter, detect_workplace, required_years
from jobcrawler.models import Job


def make(title, location="Rio de Janeiro, Rio de Janeiro", workplace="hybrid", description="",
         level="", hint="", tags=()):
    return Job(source="test", title=title, company="Acme", url="https://example.com/vaga",
               location=location, workplace=workplace, description=description,
               source_level=level, workplace_hint=hint, tags=list(tags))


@pytest.mark.parametrize("title,area", [
    ("Analista de Segurança da Informação Júnior", "security"),
    ("Analista de SOC Jr", "security"),
    ("Analista de Cibersegurança Júnior", "security"),
    ("Analista de Gestão de Vulnerabilidades Júnior", "security"),
    ("Engenheiro DevOps Júnior", "devops_sre_platform"),
    ("SRE Jr", "devops_sre_platform"),
    ("Analista de Infraestrutura Júnior", "infra_cloud_sysadmin"),
    ("Analista de Infra Jr", "infra_cloud_sysadmin"),
    ("Analista de Redes Júnior", "infra_cloud_sysadmin"),
    ("Analista de Suporte N1", "infra_cloud_sysadmin"),
    ("Técnico de TI Júnior", "infra_cloud_sysadmin"),
    ("Analista de Infraestrutura I", "infra_cloud_sysadmin"),
    ("Analista Cloud Júnior", "infra_cloud_sysadmin"),
])
def test_accepts_junior_hybrid_in_rio(rio_filter, title, area):
    decision = rio_filter.evaluate(make(title))
    assert decision.accepted, decision.reason
    assert decision.area == area and decision.regions == ["Rio de Janeiro"]


@pytest.mark.parametrize("title", [
    "Analista de Infraestrutura Pleno", "Analista de Infra PL", "Analista de Segurança Sênior",
    "Analista DevOps Sr", "Especialista em Segurança da Informação", "Estágio em Infraestrutura",
    "Estagiário de TI", "Trainee de Tecnologia - Infraestrutura", "Jovem Aprendiz - Suporte de TI",
    "Coordenador de Infraestrutura", "Gerente de Segurança da Informação", "Arquiteto Cloud",
    "Analista de Infraestrutura II", "Analista de Suporte N2", "Tech Lead DevOps",
    "Analista de Infraestrutura Júnior/Pleno",
])
def test_rejects_other_levels(rio_filter, title):
    assert not rio_filter.evaluate(make(title)).accepted


@pytest.mark.parametrize("title", [
    "Técnico de Segurança do Trabalho Júnior", "Vigilante de Segurança Patrimonial",
    "Analista de Redes Sociais Júnior", "Engenheiro Civil de Infraestrutura Júnior",
    "Analista Comercial de Cloud Júnior",
])
def test_rejects_false_friends(rio_filter, title):
    decision = rio_filter.evaluate(make(title))
    assert not decision.accepted and decision.stage == "area"


def test_pl_sql_is_not_pleno(rio_filter):
    # "pl" na blacklist não pode casar em "PL/SQL"
    decision = rio_filter.evaluate(make("Analista de Infraestrutura PL/SQL Júnior"))
    assert decision.stage != "seniority_title"


# --------------------------------------------------------------------------
# Modalidade
# --------------------------------------------------------------------------
def test_rejects_onsite_and_remote_from_source_field(rio_filter):
    for wp in ("on-site", "remote"):
        d = rio_filter.evaluate(make("Analista de Infraestrutura Júnior", workplace=wp))
        assert not d.accepted and d.stage == "workplace"


@pytest.mark.parametrize("title,description,expected", [
    ("Analista de Infra Jr (Híbrido)", "", "hybrid"),
    ("Analista de Infra Jr", "Modelo de trabalho híbrido.", "hybrid"),
    ("Analista de Infra Jr", "Regime híbrido: 3x por semana no escritório.", "hybrid"),
    ("Analista de Infra Jr", "Atuação 2 dias na semana no escritório da Barra.", "hybrid"),
    ("Analista de Infra Jr", "Vaga 100% presencial no Centro.", "onsite"),
    ("Analista de Infra Jr", "Modelo de trabalho remoto.", "remote"),
    # tecnologia, não regime de trabalho:
    ("Analista Cloud Jr", "Experiência com nuvem híbrida e ambientes híbridos.", ""),
    ("Engenheiro de Nuvem Híbrida Júnior", "", ""),
    ("Analista de Suporte Jr", "Suporte e acesso remoto aos usuários.", ""),
])
def test_detect_workplace_from_text(title, description, expected):
    job = make(title, workplace="", description=description)
    assert detect_workplace(job)[0] == expected


def test_unknown_workplace_is_kept_with_note(rio_filter):
    job = make("Analista de Infraestrutura Júnior", workplace="")
    assert rio_filter.apply(job).accepted
    assert "Modalidade não informada" in job.note


def test_search_hint_is_accepted_with_warning(rio_filter):
    job = make("Analista DevOps Júnior", workplace="", hint="hybrid")
    assert rio_filter.apply(job).accepted
    assert job.workplace == "hybrid" and "nem sempre acerta" in job.note


def test_text_beats_search_hint(rio_filter):
    # o LinkedIn disse "híbrido", mas a descrição diz presencial
    job = make("Analista DevOps Júnior", workplace="", hint="hybrid",
               description="Vaga 100% presencial.")
    assert not rio_filter.evaluate(job).accepted


# --------------------------------------------------------------------------
# Localização
# --------------------------------------------------------------------------
@pytest.fixture()
def matcher(rio_config_dict):
    f = rio_config_dict["filters"]
    return CityMatcher(f["target_cities"], f["metro_cities"], f["include_metro"],
                       f["target_state"]["names"], f["target_state"]["label"])


@pytest.mark.parametrize("location,expected", [
    ("Rio de Janeiro, Rio de Janeiro", ("city", "Rio de Janeiro")),
    ("Rio de Janeiro - RJ", ("city", "Rio de Janeiro")),
    ("Rio de Janeiro, Rio de Janeiro, Brasil", ("city", "Rio de Janeiro")),
    ("Rio de Janeiro e Região", ("city", "Rio de Janeiro")),
    ("Barra da Tijuca, Rio de Janeiro", ("city", "Rio de Janeiro")),
    ("Niterói, RJ", ("city", "Niterói")),
    ("Duque de Caxias, Rio de Janeiro, Brasil", ("city", "Duque de Caxias")),
    ("Híbrido - RJ", ("state", "RJ")),
    ("Estado do Rio de Janeiro", ("state", "RJ")),
    ("Volta Redonda, Rio de Janeiro", ("other", "Volta Redonda")),
    ("São Paulo, São Paulo", ("other", "Sao Paulo")),
    ("Brasil", ("unknown", "")),
    ("", ("unknown", "")),
])
def test_city_matcher(matcher, location, expected):
    assert matcher.match(location) == expected


def test_metro_can_be_excluded(rio_config_dict):
    filters = dict(rio_config_dict["filters"], include_metro=False)
    strict = JobFilter(FilterConfig.from_dict(filters))
    assert not strict.evaluate(make("Analista de Infraestrutura Júnior", "Niterói, RJ")).accepted
    assert strict.evaluate(make("Analista de Infraestrutura Júnior")).accepted


def test_state_only_is_kept_with_note(rio_filter):
    job = make("Analista de Infraestrutura Júnior", location="Estado do Rio de Janeiro")
    assert rio_filter.apply(job).accepted
    assert job.regions == ["RJ (cidade não informada)"] and "confira a cidade" in job.note


def test_no_location_is_rejected(rio_filter):
    d = rio_filter.evaluate(make("Analista de Infraestrutura Júnior", location=""))
    assert not d.accepted and d.stage == "region"


# --------------------------------------------------------------------------
# Senioridade pela fonte e anos de experiência em português
# --------------------------------------------------------------------------
@pytest.mark.parametrize("level", ["Estágio", "Trainee", "Jovem aprendiz", "Banco de talentos", "Pleno"])
def test_source_level_rejects(rio_filter, level):
    d = rio_filter.evaluate(make("Analista de Infraestrutura Júnior", level=level))
    assert not d.accepted and d.stage == "seniority_source"


def test_source_level_junior_marks_untitled_job(rio_filter):
    assert rio_filter.evaluate(make("Analista de Infraestrutura", level="Júnior")).accepted


@pytest.mark.parametrize("text,expected", [
    ("experiência mínima de 3 anos com linux", 3),
    ("experiência comprovada de 2 anos", 2),
    ("3 anos de vivência em redes", 3),
    ("pelo menos 4 anos de experiência", 4),
    ("de 1 a 2 anos de experiência", 1),
])
def test_required_years_pt(text, expected):
    from jobcrawler.text import fold
    assert required_years(fold(text)) == expected


def test_optional_unlabeled_level(rio_config_dict):
    filters = dict(rio_config_dict["filters"], require_junior_marker=False)
    loose = JobFilter(FilterConfig.from_dict(filters))
    job = make("Analista de Infraestrutura")
    assert loose.apply(job).accepted and "Nível não informado" in job.note
    # a blacklist continua valendo
    assert not loose.evaluate(make("Analista de Infraestrutura Pleno")).accepted


def test_no_timezone_extraction_in_portuguese(rio_filter):
    job = make("Analista de Infraestrutura Júnior", description="Idiomas: PT/EN. Horário ET, 9h.")
    assert rio_filter.apply(job).accepted and job.timezone == ""
