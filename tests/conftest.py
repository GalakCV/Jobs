import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobcrawler.filters import FilterConfig, JobFilter  # noqa: E402


@pytest.fixture(scope="session")
def config_dict():
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture()
def job_filter(config_dict):
    return JobFilter(FilterConfig.from_dict(config_dict["filters"]))
