"""Testes dos parsers das fontes com amostras no formato real de cada API (sem rede)."""

import pytest

from jobcrawler.sources import himalayas, jobicy, linkedin, remoteok, remotive, weworkremotely
from jobcrawler.sources.base import SchemaChangedError, parse_many

HIMALAYAS_ITEM = {
    "title": "Junior Cloud Engineer", "companyName": "Acme", "companySlug": "acme",
    "employmentType": "Full Time", "minSalary": 70000, "maxSalary": 90000,
    "salaryPeriod": "annual", "currency": "USD", "seniority": ["Entry-level"],
    "locationRestrictions": ["United States"],
    "timezoneRestrictions": [-10, -9, -8, -7, -6, -5, 14],
    "categories": ["Cloud-Engineer"], "parentCategories": ["Developer"],
    "description": "<p>Help run our <b>AWS</b> stack. 1-2 years of experience.</p>",
    "pubDate": 1791651021, "applicationLink": "https://himalayas.app/companies/acme/jobs/junior-cloud",
    "guid": "https://himalayas.app/companies/acme/jobs/junior-cloud",
}

JOBICY_ITEM = {
    "id": 123456, "url": "https://jobicy.com/jobs/123456-junior-devops", "jobTitle": "Junior DevOps Engineer",
    "companyName": "Example", "jobIndustry": ["DevOps &amp; Infrastructure"], "jobType": ["Full-Time"],
    "jobGeo": "USA", "jobLevel": "Junior", "jobExcerpt": "Short",
    "jobDescription": "<p>Kubernetes, Terraform</p>", "pubDate": "2026-10-10T12:11:28+00:00",
    "salaryMin": 60000, "salaryMax": 80000, "salaryCurrency": "USD", "salaryPeriod": "yearly",
}

REMOTIVE_ITEM = {
    "id": 1, "url": "https://remotive.com/remote-jobs/devops/junior-sre-1", "title": "Junior SRE",
    "company_name": "Beta", "category": "DevOps / Sysadmin", "tags": ["aws", "linux"],
    "job_type": "full_time", "publication_date": "2026-10-08T10:00:00",
    "candidate_required_location": "USA, Canada", "salary": "$70k", "description": "<p>On-call</p>",
}

REMOTEOK_DATA = [
    {"last_updated": 1791619208, "legal": "API Terms of Service: Please link back..."},
    {"slug": "x", "id": "1137460", "epoch": 1790945581, "date": "2026-10-02T12:53:01+00:00",
     "company": "Gamma", "position": "Junior Security Analyst", "tags": ["security", "junior"],
     "description": "<p>SOC work</p>", "location": "Worldwide", "salary_min": 60000,
     "salary_max": 80000, "url": "https://remoteOK.com/remote-jobs/remote-junior-security-analyst-1137460"},
]

WWR_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>WWR</title>
<item>
  <title>BeyondTrust: Junior Cloud Engineer</title>
  <region>Anywhere in the World</region>
  <country>🇨🇦 Canada and 🇺🇸 United States of America</country>
  <state></state><skills>AWS, Terraform</skills>
  <category>DevOps and Sysadmin</category><type>Full-Time</type>
  <description>&lt;p&gt;2+ years of experience.&lt;/p&gt;</description>
  <pubDate>Wed, 07 Oct 2026 07:30:53 +0000</pubDate>
  <guid>https://weworkremotely.com/remote-jobs/beyondtrust-junior-cloud-engineer</guid>
  <link>https://weworkremotely.com/remote-jobs/beyondtrust-junior-cloud-engineer</link>
</item>
<item>
  <title>Datadog: Developer Advocate</title>
  <region>Anywhere in the World</region>
  <country>🇫🇷 France, 🇵🇹 Portugal</country><state></state>
  <description>x</description><pubDate>Sun, 20 Sep 2026 07:31:09 +0000</pubDate>
  <link>https://weworkremotely.com/remote-jobs/datadog-dev-advocate</link>
</item>
</channel></rss>"""

LINKEDIN_HTML = """
<li><div class="base-card job-search-card">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/junior-devops-123?refId=abc"></a>
  <h3 class="base-search-card__title"> Junior DevOps Engineer </h3>
  <h4 class="base-search-card__subtitle"><a class="hidden-nested-link">Delta Inc</a></h4>
  <span class="job-search-card__location">United States</span>
  <time class="job-search-card__listdate" datetime="2026-10-09">1 day ago</time>
</div></li>"""


def test_himalayas_parser():
    job = himalayas.parse_job(HIMALAYAS_ITEM)
    assert job.title == "Junior Cloud Engineer" and job.company == "Acme"
    assert job.location == "United States" and job.source_level == "Entry-level"
    assert job.timezone == "UTC-10 a UTC-5, UTC+14"
    assert job.salary.startswith("USD 70,000")
    assert "AWS" in job.description and "<" not in job.description
    assert job.published_at.startswith("2026-10-")


def test_himalayas_empty_restrictions_means_worldwide():
    job = himalayas.parse_job({**HIMALAYAS_ITEM, "locationRestrictions": []})
    assert job.location == "Worldwide"


def test_himalayas_extract_items_handles_shapes():
    assert himalayas.extract_items({"jobs": [1]}) == [1]
    assert himalayas.extract_items([1, 2]) == [1, 2]
    with pytest.raises(SchemaChangedError):
        himalayas.extract_items({"unexpected": True})


def test_jobicy_parser():
    job = jobicy.parse_job(JOBICY_ITEM)
    assert job.title == "Junior DevOps Engineer" and job.location == "USA"
    assert job.source_level == "Junior" and job.url.startswith("https://jobicy.com")
    assert jobicy.parse_job({**JOBICY_ITEM, "jobLevel": "Any"}).source_level == ""


def test_remotive_parser():
    job = remotive.parse_job(REMOTIVE_ITEM)
    assert job.location == "USA, Canada" and job.company == "Beta"
    assert job.published_at == "2026-10-08T10:00:00+00:00"


def test_remoteok_skips_legal_notice():
    items = remoteok.extract_items(REMOTEOK_DATA)
    jobs = parse_many(items, remoteok.parse_job, "remoteok")
    assert len(jobs) == 1 and jobs[0].title == "Junior Security Analyst"
    assert jobs[0].salary == "USD 60,000–80,000"


def test_wwr_parser_splits_title_and_uses_country():
    items = weworkremotely.parse_feed(WWR_FEED)
    jobs = [weworkremotely.parse_item(i) for i in items]
    assert jobs[0].company == "BeyondTrust" and jobs[0].title == "Junior Cloud Engineer"
    assert jobs[0].location == "Canada, United States of America"
    assert jobs[0].tags == ["AWS", "Terraform"]
    # o país real (França/Portugal) prevalece sobre "Anywhere in the World"
    assert jobs[1].location == "France, Portugal"


def test_wwr_invalid_xml_is_reported():
    with pytest.raises(SchemaChangedError):
        weworkremotely.parse_feed("<html>blocked</html")


def test_linkedin_cards():
    jobs = linkedin.parse_cards(LINKEDIN_HTML)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Junior DevOps Engineer" and job.company == "Delta Inc"
    assert job.url == "https://www.linkedin.com/jobs/view/junior-devops-123"
    assert job.location == "United States" and job.published_at.startswith("2026-10-09")


def test_schema_drift_detection():
    broken = [{"name": "x"}, {"name": "y"}, {"name": "z"}]
    with pytest.raises(SchemaChangedError) as exc:
        parse_many(broken, remotive.parse_job, "remotive")
    assert "campos recebidos" in str(exc.value)


def test_partial_failures_are_tolerated():
    items = [REMOTIVE_ITEM, REMOTIVE_ITEM, {"broken": True}]
    assert len(parse_many(items, remotive.parse_job, "remotive")) == 2


# --------------------------------------------------------------------------
# Fontes brasileiras
# --------------------------------------------------------------------------
from jobcrawler.sources import github_issues, gupy  # noqa: E402

GUPY_ITEM = {
    "id": 9876543, "companyId": 123, "name": "Analista de Infraestrutura Júnior",
    "description": "<p>Atuar com <b>Linux</b> e redes. Modelo híbrido.</p>",
    "careerPageId": 55, "careerPageName": "Empresa Carioca", "careerPageLogo": None,
    "type": "vacancy_type_effective", "publishedDate": "2026-10-08T13:00:00.000Z",
    "applicationDeadline": None, "isRemoteWork": False, "city": "Rio de Janeiro",
    "state": "Rio de Janeiro", "country": "Brasil", "careerPageUrl": "https://carioca.gupy.io",
    "jobUrl": "https://carioca.gupy.io/jobs/9876543?jobBoardSource=gupy_portal",
    "workplaceType": "hybrid", "skills": ["Linux", "Redes"],
}


def test_gupy_parser():
    job = gupy.parse_job(GUPY_ITEM)
    assert job.title == "Analista de Infraestrutura Júnior" and job.company == "Empresa Carioca"
    assert job.location == "Rio de Janeiro, Rio de Janeiro" and job.workplace == "hybrid"
    assert job.url.startswith("https://carioca.gupy.io/jobs/9876543")
    assert job.published_at == "2026-10-08T13:00:00+00:00"
    assert job.source_level == "" and "Linux" in job.description and "<" not in job.description


@pytest.mark.parametrize("raw,expected", [("on-site", "onsite"), ("remote", "remote"),
                                          ("hybrid", "hybrid"), (None, "")])
def test_gupy_workplace(raw, expected):
    assert gupy.parse_job({**GUPY_ITEM, "workplaceType": raw}).workplace == expected


def test_gupy_remote_flag_fallback():
    job = gupy.parse_job({**GUPY_ITEM, "workplaceType": None, "isRemoteWork": True})
    assert job.workplace == "remote"


def test_gupy_vacancy_types_become_levels():
    assert gupy.parse_job({**GUPY_ITEM, "type": "vacancy_type_internship"}).source_level == "Estágio"
    assert gupy.parse_job({**GUPY_ITEM, "type": "vacancy_type_talent_pool"}).source_level == "Banco de talentos"


def test_gupy_state_without_city_is_not_read_as_city():
    job = gupy.parse_job({**GUPY_ITEM, "city": ""})
    assert job.location == "Estado do Rio de Janeiro"


def test_gupy_extract_page_and_schema_drift():
    items, total = gupy.extract_page({"data": [GUPY_ITEM], "pagination": {"total": 1}})
    assert len(items) == 1 and total == 1
    with pytest.raises(SchemaChangedError):
        gupy.extract_page({"jobs": []})


GITHUB_ISSUE = {
    "html_url": "https://github.com/backend-br/vagas/issues/12345",
    "repository_url": "https://api.github.com/repos/backend-br/vagas",
    "title": "[Rio de Janeiro] Analista DevOps Júnior na Acme Tech",
    "labels": [{"name": "Híbrido"}, {"name": "Júnior"}, {"name": "CLT"}, {"name": "AWS"}],
    "body": "## Descrição\nVaga para o time de plataforma.\n\n## Local\nLocal: Centro, Rio de Janeiro",
    "created_at": "2026-10-09T12:00:00Z",
}


def test_github_issue_parser():
    job = github_issues.parse_issue(GITHUB_ISSUE)
    assert job.title == "Analista DevOps Júnior" and job.company == "Acme Tech"
    assert job.workplace == "hybrid" and job.source_level == "Júnior"
    assert job.location.startswith("Rio de Janeiro")
    assert "CLT" in job.tags and job.url.endswith("/issues/12345")


def test_github_issue_brackets_with_modality():
    job = github_issues.parse_issue({**GITHUB_ISSUE, "labels": [], "body": "",
                                     "title": "[Híbrido] [Niterói] SRE Jr @ Empresa"})
    assert job.location == "Niterói" and "Híbrido" in job.tags and job.company == "Empresa"


def test_github_skips_pull_requests():
    assert github_issues.parse_issue({**GITHUB_ISSUE, "pull_request": {}}) is None


def test_linkedin_search_hint():
    jobs = linkedin.parse_cards(LINKEDIN_HTML, workplace_hint="hybrid")
    assert jobs[0].workplace_hint == "hybrid" and jobs[0].workplace == ""
