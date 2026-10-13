"""Os dois perfis (rio + remoto) rodando juntos, num banco e num relatório só."""

import copy
import json
import sqlite3

import pytest

from jobcrawler import pipeline
from jobcrawler.models import Job
from jobcrawler.profiles import build_profiles, deep_merge, evaluate_any
from jobcrawler.sources import REGISTRY
from jobcrawler.sources.base import Source, SourceResult
from jobcrawler.storage import JobStore


def _job(source, title, location, workplace="", company="Acme"):
    return Job(source=source, title=title, company=company, location=location, workplace=workplace,
               url=f"https://example.com/{source}/{abs(hash(title + location + company))}")


class FakeBR(Source):
    name = "fake_br"

    def fetch(self):
        return SourceResult(self.name, jobs=[
            _job("gupy", "Analista de Infraestrutura Júnior", "Rio de Janeiro, Rio de Janeiro", "hybrid"),
            _job("gupy", "Analista de SOC Jr", "Niterói, Rio de Janeiro", "hybrid"),
            _job("gupy", "Analista DevOps Júnior", "Rio de Janeiro, Rio de Janeiro", "on-site"),
            # remota no Brasil: não é do perfil Rio (híbrido) nem do remoto (exterior)
            _job("gupy", "Analista Cloud Júnior", "Rio de Janeiro, Rio de Janeiro", "remote"),
        ])


class FakeIntl(Source):
    name = "fake_intl"

    def fetch(self):
        return SourceResult(self.name, jobs=[
            _job("himalayas", "Junior DevOps Engineer", "United States"),
            _job("remotive", "Junior Security Analyst", "Worldwide"),
            _job("remotive", "Senior SRE", "USA"),
            # híbrida em Sydney: o perfil remoto descarta, e o Rio nem vê (fonte de fora)
            _job("weworkremotely", "Junior Cloud Engineer (Hybrid)", "Sydney, Australia"),
        ])


@pytest.fixture()
def cfg(full_config, tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "fake_br", FakeBR)
    monkeypatch.setitem(REGISTRY, "fake_intl", FakeIntl)
    c = copy.deepcopy(full_config)
    c["sources"] = {"fake_br": {"enabled": True}, "fake_intl": {"enabled": True}}
    c["profiles"]["rio"]["sources"] = ["fake_br"]
    c["profiles"]["remoto"]["sources"] = ["fake_intl"]
    c["storage"] = {"database": str(tmp_path / "jobs.db"), "output_dir": str(tmp_path / "out"),
                    "export_formats": ["html", "json", "csv"]}
    c["http"]["cache_dir"] = str(tmp_path / "cache")
    return c


def test_both_profiles_in_one_run(cfg, tmp_path):
    summary = pipeline.run(cfg, notify=False, explain=True)
    by_profile = {}
    for job in summary.accepted:
        by_profile.setdefault(job.profile, set()).add(job.title)
    assert by_profile == {
        "rio": {"Analista de Infraestrutura Júnior", "Analista de SOC Jr"},
        "remoto": {"Junior DevOps Engineer", "Junior Security Analyst"},
    }
    assert summary.per_profile == {"rio": 2, "remoto": 2}

    out = tmp_path / "out"
    html = (out / "jobs_latest.html").read_text(encoding="utf-8")
    assert 'role="radiogroup"' in html                       # seletor de perfil
    assert "Híbridas no Rio <span class=\"n\">2</span>" in html
    assert "Remotas no exterior <span class=\"n\">2</span>" in html
    assert 'data-profile="rio"' in html and 'data-profile="remoto"' in html
    assert "Aceitas por perfil: Híbridas no Rio: 2, Remotas no exterior: 2." in html
    # chips de local sabem a que perfil pertencem
    assert 'data-region="Niterói" data-profiles="rio"' in html
    assert 'data-region="US" data-profiles="remoto"' in html

    data = json.loads((out / "jobs_latest.json").read_text(encoding="utf-8"))
    assert {j["profile"] for j in data["jobs"]} == {"rio", "remoto"}
    rejections = (out / "rejections.csv").read_text(encoding="utf-8-sig")
    assert "procurando híbrido" in rejections and "procurando remoto" in rejections


def test_single_profile_run(cfg):
    summary = pipeline.run(cfg, notify=False, profiles_only=["rio"])
    assert {j.profile for j in summary.accepted} == {"rio"}
    assert "fake_intl" not in summary.per_source        # fonte do outro perfil nem é coletada


def test_unknown_profile_is_a_clear_error(cfg):
    with pytest.raises(ValueError, match="Perfil inexistente: lisboa"):
        pipeline.run(cfg, notify=False, profiles_only=["lisboa"])


def test_profile_overrides_are_merged(full_config):
    profiles = {p.key: p for p in build_profiles(full_config)}
    rio, remoto = profiles["rio"].job_filter.cfg, profiles["remoto"].job_filter.cfg
    assert rio.workplace_types == ["hybrid"] and remoto.workplace_types == ["remote"]
    assert rio.location_mode == "cities" and remoto.location_mode == "regions"
    # áreas e blacklist vêm da seção comum
    assert rio.seniority_blacklist == remoto.seniority_blacklist
    assert "pleno" in rio.seniority_blacklist and "senior" in remoto.seniority_blacklist


def test_invalid_profile_filter_names_the_profile(full_config):
    bad = copy.deepcopy(full_config)
    bad["profiles"]["rio"]["filters"]["workplace_types"] = ["teletrabalho"]
    with pytest.raises(ValueError, match="profiles.rio"):
        build_profiles(bad)


def test_deep_merge_replaces_lists_and_merges_dicts():
    base = {"a": [1, 2], "b": {"x": 1, "y": 2}, "c": 1}
    assert deep_merge(base, {"a": [3], "b": {"y": 9}}) == {"a": [3], "b": {"x": 1, "y": 9}, "c": 1}
    assert base == {"a": [1, 2], "b": {"x": 1, "y": 2}, "c": 1}   # não altera o original


def test_evaluate_any_picks_the_matching_profile(full_config):
    profiles = build_profiles(full_config)
    profile, decision = evaluate_any(profiles, _job("x", "Analista de Redes Júnior",
                                                    "Rio de Janeiro", "hybrid"))
    assert profile.key == "rio" and decision.accepted
    profile, decision = evaluate_any(profiles, _job("x", "Junior SRE", "Canada"))
    assert profile.key == "remoto" and decision.accepted
    profile, decision = evaluate_any(profiles, _job("x", "Senior SRE", "Canada"))
    assert profile is None and not decision.accepted


def test_old_remote_only_database_gets_profile_backfill(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE jobs (fingerprint TEXT PRIMARY KEY, title TEXT NOT NULL, "
                     "company TEXT NOT NULL, url TEXT NOT NULL, source TEXT NOT NULL, "
                     "sources TEXT NOT NULL, location TEXT, regions TEXT, timezone TEXT, area TEXT, "
                     "junior_signal TEXT, source_level TEXT, tags TEXT, salary TEXT, "
                     "published_at TEXT, description TEXT, first_seen TEXT NOT NULL, "
                     "last_seen TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0)")
        conn.execute("INSERT INTO jobs VALUES ('fp1','Junior SRE','Acme','https://x.com/1','remotive',"
                     "'[\"remotive\"]','USA','US','','devops_sre_platform','','','','','',''," 
                     "strftime('%Y-%m-%dT%H:%M:%S','now'),strftime('%Y-%m-%dT%H:%M:%S','now'),0)")
    rows = JobStore(db).recent(1)
    assert rows[0]["profile"] == "remoto"


def test_report_command_shows_both_profiles(cfg, tmp_path):
    import yaml

    from jobcrawler.cli import main

    pipeline.run(cfg, notify=False)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert main(["-c", str(cfg_path), "report", "--output", str(tmp_path / "r.html")]) == 0
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Híbridas no Rio" in html and "Remotas no exterior" in html
