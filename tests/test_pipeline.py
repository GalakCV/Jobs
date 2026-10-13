"""Teste ponta a ponta do pipeline com uma fonte falsa (sem rede)."""

import copy
import json

import pytest

from jobcrawler import pipeline
from jobcrawler.models import Job
from jobcrawler.sources import REGISTRY
from jobcrawler.sources.base import Source, SourceResult


def _job(title, company, location="USA", source="fake"):
    return Job(source=source, title=title, company=company, location=location,
               url=f"https://example.com/{title.replace(' ', '-')}-{company}",
               description="1+ year of experience with Linux.")


class FakeSource(Source):
    name = "fake"
    batch: list[Job] = []

    def fetch(self):
        return SourceResult(self.name, jobs=[copy.copy(j) for j in self.batch])


class BrokenSource(Source):
    name = "broken"

    def fetch(self):
        raise RuntimeError("explodiu")


@pytest.fixture()
def cfg(config_dict, tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "fake", FakeSource)
    monkeypatch.setitem(REGISTRY, "broken", BrokenSource)
    c = copy.deepcopy(config_dict)
    c["sources"] = {"fake": {"enabled": True}, "broken": {"enabled": True}}
    c["storage"] = {"database": str(tmp_path / "jobs.db"), "output_dir": str(tmp_path / "out"),
                    "export_formats": ["html", "json", "csv"]}
    c["http"]["cache_dir"] = str(tmp_path / "cache")
    return c


def test_full_run_filters_dedupes_and_tracks_new(cfg, tmp_path):
    FakeSource.batch = [
        _job("Junior DevOps Engineer", "Acme"),
        _job("Junior DevOps Engineer", "Acme", source="fake"),     # duplicada
        _job("Senior DevOps Engineer", "Acme"),                    # blacklist
        _job("Junior Security Analyst", "Beta", location="Germany"),  # região
        _job("Entry-Level Cloud Support Engineer", "Gamma", location="Australia"),
    ]
    s1 = pipeline.run(cfg, explain=True)
    assert s1.fetched == 5 and s1.unique == 4
    assert {j.title for j in s1.accepted} == {"Junior DevOps Engineer",
                                              "Entry-Level Cloud Support Engineer"}
    assert len(s1.new) == 2
    assert "broken" in s1.errors  # uma fonte quebrada não derruba a execução

    out = tmp_path / "out"
    data = json.loads((out / "jobs_latest.json").read_text(encoding="utf-8"))
    assert data["total"] == 2 and data["new"] == 2
    report = (out / "jobs_latest.html").read_text(encoding="utf-8")
    assert "Entry-Level Cloud Support Engineer" in report and "Detalhes da execução" in report
    assert (out / "jobs_latest.csv").read_text(encoding="utf-8-sig").startswith("Publicada em")
    assert "região fora do escopo" in (out / "rejections.csv").read_text(encoding="utf-8-sig")

    # Segunda execução: mesmas vagas => nada novo
    s2 = pipeline.run(cfg)
    assert len(s2.accepted) == 2 and len(s2.new) == 0


def test_dry_run_does_not_create_database(cfg, tmp_path):
    FakeSource.batch = [_job("Junior SRE", "Acme")]
    summary = pipeline.run(cfg, dry_run=True)
    assert len(summary.accepted) == 1
    assert not (tmp_path / "jobs.db").exists()


def test_notifications_marked_only_on_success(cfg, monkeypatch):
    from jobcrawler.notifiers import Notifier

    sent = []

    class OkNotifier(Notifier):
        name = "ok"

        def send(self, jobs):
            sent.extend(jobs)
            return True

    monkeypatch.setattr(pipeline, "build_notifiers", lambda _cfg: [OkNotifier()])
    FakeSource.batch = [_job("Junior SRE", "Acme")]
    s1 = pipeline.run(cfg)
    assert s1.notified == 1 and len(sent) == 1
    s2 = pipeline.run(cfg)           # já notificada: não reenvia
    assert s2.notified == 0 and len(sent) == 1


def test_import_command_filters_and_merges(cfg, tmp_path, monkeypatch):
    """`import` passa o JSON pelo filtro, grava no banco e o `report` inclui as vagas."""
    import yaml

    from jobcrawler.cli import main

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    payload = [
        {"source": "linkedin", "title": "Junior Cloud Engineer", "company": "Koniag",
         "url": "https://www.linkedin.com/jobs/view/1", "location": "Washington, Estados Unidos",
         "note": "Remoto não confirmado"},
        {"source": "linkedin", "title": "Senior SRE", "company": "X",
         "url": "https://www.linkedin.com/jobs/view/2", "location": "USA"},
        {"source": "linkedin", "title": "", "company": "Y", "url": "not-a-url"},
    ]
    data_file = tmp_path / "li.json"
    data_file.write_text(json.dumps(payload), encoding="utf-8")

    assert main(["-c", str(cfg_path), "import", str(data_file)]) == 0
    assert main(["-c", str(cfg_path), "report", "--output", str(tmp_path / "r.html")]) == 0
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "Junior Cloud Engineer" in html and "Remoto não confirmado" in html
    assert "Senior SRE" not in html


def test_rio_profile_end_to_end(rio_config_dict, tmp_path, monkeypatch):
    """Perfil padrão: só entra híbrido júnior no Rio e região metropolitana."""
    monkeypatch.setitem(REGISTRY, "fake", FakeSource)
    cfg = copy.deepcopy(rio_config_dict)
    cfg["sources"] = {"fake": {"enabled": True}}
    cfg["storage"] = {"database": str(tmp_path / "rio.db"), "output_dir": str(tmp_path / "out"),
                      "export_formats": ["html", "csv"]}
    cfg["http"]["cache_dir"] = str(tmp_path / "cache")

    def rio(title, location="Rio de Janeiro, Rio de Janeiro", workplace="hybrid"):
        return Job(source="gupy", title=title, company="Acme", location=location,
                   workplace=workplace, url=f"https://acme.gupy.io/jobs/{abs(hash(title + location))}")

    FakeSource.batch = [
        rio("Analista de Infraestrutura Júnior"),
        rio("Analista de Segurança da Informação Jr", "Niterói, Rio de Janeiro"),
        rio("Analista DevOps Júnior", workplace="onsite"),
        rio("Analista de SOC Júnior", "São Paulo, São Paulo"),
        rio("Analista de Infraestrutura Pleno"),
    ]
    summary = pipeline.run(cfg, notify=False)
    assert {j.title for j in summary.accepted} == {"Analista de Infraestrutura Júnior",
                                                   "Analista de Segurança da Informação Jr"}
    out = tmp_path / "out"
    html = (out / "jobs_latest.html").read_text(encoding="utf-8")
    assert "<h1>Vagas híbridas no Rio</h1>" in html and 'data-region="Niterói"' in html
    csv_text = (out / "jobs_latest.csv").read_text(encoding="utf-8-sig")
    assert "Modalidade" in csv_text.splitlines()[0] and "Híbrido" in csv_text


def test_old_database_is_migrated(tmp_path):
    """Bancos criados antes das colunas note/workplace continuam funcionando."""
    import sqlite3

    from jobcrawler.storage import JobStore

    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE jobs (fingerprint TEXT PRIMARY KEY, title TEXT NOT NULL, "
                     "company TEXT NOT NULL, url TEXT NOT NULL, source TEXT NOT NULL, "
                     "sources TEXT NOT NULL, location TEXT, regions TEXT, timezone TEXT, area TEXT, "
                     "junior_signal TEXT, source_level TEXT, tags TEXT, salary TEXT, "
                     "published_at TEXT, description TEXT, first_seen TEXT NOT NULL, "
                     "last_seen TEXT NOT NULL, notified INTEGER NOT NULL DEFAULT 0)")
    store = JobStore(db)
    new = store.upsert([Job(source="gupy", title="Analista de Infra Jr", company="Acme",
                            url="https://acme.gupy.io/jobs/1", workplace="hybrid")])
    assert len(new) == 1 and store.recent(1)[0]["workplace"] == "hybrid"
