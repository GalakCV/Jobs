"""Testes do relatório HTML: conteúdo, escape de dados externos e estado vazio."""

from jobcrawler.html_report import render_html


def rec(**kw):
    base = {"title": "Junior DevOps Engineer", "company": "Acme", "url": "https://example.com/1",
            "area": "devops_sre_platform", "location": "USA", "regions": "US",
            "timezone": "EST", "salary": "USD 70,000–90,000", "junior_signal": "título: 'junior'",
            "source": "himalayas", "published_at": "2026-10-09T12:00:00+00:00",
            "is_new": "sim", "description": "Kubernetes and Terraform."}
    base.update(kw)
    return base


def test_renders_jobs_and_summary():
    html = render_html([rec(), rec(title="Junior Security Analyst", area="security",
                                   regions="GLOBAL", is_new="não", url="https://example.com/2")])
    assert "2 vagas júnior remotas abertas, 1 nova desde a última execução." in html
    assert 'href="https://example.com/1"' in html and "Junior Security Analyst" in html
    assert 'data-area="security"' in html and 'data-regions="GLOBAL"' in html
    assert 'class="new">Nova<' in html and "Global" in html
    assert "<title>Vagas júnior remotas (1 novas)</title>" in html
    assert "“junior” no título" in html


def test_junior_label_variants():
    from jobcrawler.html_report import _junior_label
    assert _junior_label("fonte: 'Entry-level'") == "nível “Entry-level” na fonte"
    assert _junior_label("algo inesperado") == "algo inesperado"


def test_escapes_untrusted_content():
    evil = '<img src=x onerror="alert(1)">'
    html = render_html([rec(title=evil, company=evil, description=evil, location=evil)])
    assert evil not in html
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html


def test_only_http_urls_become_links():
    html = render_html([rec(url="javascript:alert(1)")])
    assert "javascript:" not in html
    assert '<span class="title">Junior DevOps Engineer</span>' in html


def test_search_index_is_accent_folded():
    html = render_html([rec(title="Analista de Segurança Júnior", area="security")])
    assert 'data-search="analista de seguranca junior' in html


def test_empty_state_explains_next_step():
    html = render_html([])
    assert "Nenhuma vaga passou nos filtros desta vez." in html
    assert "--explain" in html and 'id="queue"' not in html


def test_run_details_list_errors():
    html = render_html([rec()], {"fetched": 10, "unique": 8,
                                 "per_source": {"himalayas": {"fetched": 10, "accepted": 1, "errors": 1}},
                                 "errors": {"himalayas": ["HTTP 429 <script>"]},
                                 "rejection_stages": {"region": 4, "seniority_title": 3}})
    assert "Coletadas 10 vagas, 8 únicas" in html
    assert "região: 4" in html and "HTTP 429 &lt;script&gt;" in html
