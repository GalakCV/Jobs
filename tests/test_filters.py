"""Testes do motor de filtragem (regras de área, senioridade e localização)."""

from datetime import datetime, timedelta, timezone

import pytest

from jobcrawler.filters import FilterConfig, JobFilter, classify_regions, required_years
from jobcrawler.models import Job
from jobcrawler.text import extract_timezones, utc_offsets_to_label


def make(title, location="USA", description="", level="", published=None):
    return Job(source="test", title=title, company="Acme", url="https://example.com/job",
               location=location, description=description, source_level=level,
               published_at=published)


# --------------------------------------------------------------------------
# Vagas que DEVEM passar
# --------------------------------------------------------------------------
@pytest.mark.parametrize("title,location,area", [
    ("Junior DevOps Engineer", "USA", "devops_sre_platform"),
    ("Jr. Site Reliability Engineer", "Remote - Canada", "devops_sre_platform"),
    ("Junior Platform Engineer", "Australia", "devops_sre_platform"),
    ("Junior Security Analyst", "Worldwide", "security"),
    ("Entry-Level SOC Analyst", "United States", "security"),
    ("SOC Analyst Tier 1", "Austin, TX", "security"),
    ("Junior AppSec Engineer", "North America", "security"),
    ("Entry Level Cloud Support Engineer", "Anywhere", "infra_cloud_sysadmin"),
    ("Junior Linux System Administrator", "USA, Canada", "infra_cloud_sysadmin"),
    ("Cloud Engineer I", "Denver, CO", "infra_cloud_sysadmin"),
    ("Associate Cloud Security Engineer", "APAC", "security"),
    ("Analista de Segurança Júnior", "Canada", "security"),
])
def test_accepts_explicit_junior(job_filter, title, location, area):
    decision = job_filter.evaluate(make(title, location))
    assert decision.accepted, decision.reason
    assert decision.area == area


# --------------------------------------------------------------------------
# Blacklist de senioridade (CRÍTICO)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("title", [
    "Senior DevOps Engineer", "Sr. SRE", "Sr DevOps", "Lead Security Engineer",
    "Principal Cloud Architect", "Staff Platform Engineer", "DevOps Manager",
    "Head of Security", "Junior DevOps Engineer II", "Security Analyst III",
    "Mid-Level DevOps Engineer", "Intermediate Cloud Engineer",
    "DevOps Intern", "Security Internship", "Cloud Trainee", "Estagiário DevOps",
    "Estágio em Infraestrutura", "DevOps Pleno", "Analista de Segurança Sênior",
    "Junior/Mid DevOps Engineer", "SOC Analyst Tier 2", "Experienced Junior SysAdmin",
    "Junior Security Engineer 2",
])
def test_blacklist_rejects(job_filter, title):
    decision = job_filter.evaluate(make(title))
    assert not decision.accepted
    assert decision.stage in {"seniority_title", "area"}, decision


def test_word_boundaries_do_not_overmatch(job_filter):
    # "sr" não pode casar em "SRE"; "intern" não pode casar em "internal"
    assert job_filter.evaluate(make("Junior SRE")).accepted
    assert job_filter.evaluate(make("Junior Internal IT Support Engineer")).accepted


def test_requires_explicit_junior(job_filter):
    decision = job_filter.evaluate(make("DevOps Engineer"))
    assert not decision.accepted and decision.stage == "junior_marker"


def test_source_level_can_mark_junior(job_filter):
    assert job_filter.evaluate(make("Cloud Support Engineer", level="Entry-level")).accepted
    rejected = job_filter.evaluate(make("Junior Cloud Engineer", level="Mid-level"))
    assert not rejected.accepted and rejected.stage == "seniority_source"


# --------------------------------------------------------------------------
# Descrição: anos de experiência e frases de nível
# --------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Requires 5+ years of experience with AWS", 5),
    ("3-5 years of hands-on experience", 3),
    ("3 to 5 years of professional experience", 3),
    ("minimum of 4 years in IT", 4),
    ("at least three years of experience", 3),
    ("1+ year of Linux experience and 5+ years overall experience", 5),
    ("5 anos de experiencia em seguranca", 5),
    ("We were founded 10 years ago and grew fast", None),
    ("0-2 years of experience", 0),
])
def test_required_years(text, expected):
    assert required_years(text.lower()) == expected


def test_rejects_too_much_experience(job_filter):
    d = job_filter.evaluate(make("Junior DevOps Engineer", description="Need 4+ years of experience."))
    assert not d.accepted and d.stage == "experience"
    ok = job_filter.evaluate(make("Junior DevOps Engineer", description="1-2 years of experience."))
    assert ok.accepted


def test_smart_mode_tolerates_incidental_words(job_filter):
    desc = ("You will work alongside senior engineers, report to the engineering manager "
            "and help lead incident retrospectives.")
    assert job_filter.evaluate(make("Junior SRE", description=desc)).accepted


def test_smart_mode_catches_level_phrases(job_filter):
    d = job_filter.evaluate(make("Junior Cloud Engineer", description="This is a mid-level role."))
    assert not d.accepted and d.stage == "seniority_description"
    d = job_filter.evaluate(make("Junior Security Analyst", description="Summer internship program."))
    assert not d.accepted


def test_strict_mode_rejects_any_blacklisted_word(config_dict):
    filters = dict(config_dict["filters"], description_mode="strict")
    strict = JobFilter(FilterConfig.from_dict(filters))
    d = strict.evaluate(make("Junior SRE", description="Report to the engineering manager."))
    assert not d.accepted and d.reason.startswith("[strict]")


# --------------------------------------------------------------------------
# Remoto, área e região
# --------------------------------------------------------------------------
def test_rejects_hybrid_and_onsite(job_filter):
    assert not job_filter.evaluate(make("Junior DevOps Engineer (Hybrid)")).accepted
    assert not job_filter.evaluate(make("Junior SysAdmin", location="On-site, Dallas")).accepted


def test_area_exclusions(job_filter):
    d = job_filter.evaluate(make("Junior Cloud Sales Representative"))
    assert not d.accepted and d.stage == "area"
    assert not job_filter.evaluate(make("Junior Frontend Developer")).accepted


@pytest.mark.parametrize("location,expected", [
    ("USA", ["US"]),
    ("Remote - US", ["US"]),
    ("United States, Canada", ["US", "CA"]),
    ("North America", ["US", "CA"]),
    ("Sydney, Australia", ["AU"]),
    ("APAC", ["AU"]),
    ("Worldwide", ["GLOBAL"]),
    ("Anywhere in the World", ["GLOBAL"]),
    ("Seattle, WA", ["US"]),
    ("Estados Unidos", ["US"]),
    ("Chicago, Ilinóis, Estados Unidos", ["US"]),
    ("Nashville, Tenessi, Estados Unidos", ["US"]),
    ("Toronto, Ontário, Canadá", ["CA"]),
    ("Sydney, Nova Gales do Sul, Austrália", ["AU"]),
    ("Londres, Inglaterra, Reino Unido", ["OTHER"]),
    ("Germany", ["OTHER"]),
    ("Latin America", ["OTHER"]),
    ("Remote", ["UNKNOWN"]),
    ("", ["UNKNOWN"]),
])
def test_classify_regions(location, expected):
    assert classify_regions(location) == expected


def test_rejects_out_of_scope_region(job_filter):
    d = job_filter.evaluate(make("Junior DevOps Engineer", location="Europe only"))
    assert not d.accepted and d.stage == "region"


def test_unknown_location_is_flagged(job_filter):
    d = job_filter.evaluate(make("Junior DevOps Engineer", location=""))
    assert d.accepted and d.regions == ["NÃO INFORMADO"]


def test_rejects_old_jobs(job_filter):
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    d = job_filter.evaluate(make("Junior DevOps Engineer", published=old))
    assert not d.accepted and d.stage == "age"


def test_apply_enriches_job(job_filter):
    job = make("Junior DevOps Engineer", description="Must overlap with EST business hours.")
    assert job_filter.apply(job).accepted
    assert job.area == "devops_sre_platform" and job.regions == ["US"]
    assert "EST" in job.timezone


# --------------------------------------------------------------------------
# Fusos horários
# --------------------------------------------------------------------------
def test_extract_timezones():
    tz = extract_timezones("Work 9-5 Pacific Time, overlap with UTC-5 and AEST")
    assert "Pacific Time" in tz and "UTC-5" in tz and "AEST" in tz


def test_utc_offsets_label():
    assert utc_offsets_to_label([-10, -9, -8, -7, -6, -5, 14]) == "UTC-10 a UTC-5, UTC+14"
    assert utc_offsets_to_label([8, 9, 10]) == "UTC+8 a UTC+10"
    assert utc_offsets_to_label([]) == ""


def test_invalid_config_is_rejected(config_dict):
    with pytest.raises(ValueError):
        FilterConfig.from_dict(dict(config_dict["filters"], description_mode="loose"))
    with pytest.raises(ValueError):
        FilterConfig.from_dict(dict(config_dict["filters"], seniority_blacklist=[]))
