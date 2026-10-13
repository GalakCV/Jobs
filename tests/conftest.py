import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobcrawler.filters import FilterConfig, JobFilter  # noqa: E402


@pytest.fixture(scope="session")
def config_dict():
    """Perfil remoto (config.remoto.yaml): EUA/Canadá/Austrália/Global."""
    return yaml.safe_load((ROOT / "config.remoto.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def rio_config_dict():
    """Perfil padrão (config.yaml): híbrido no Rio de Janeiro."""
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


@pytest.fixture()
def job_filter(config_dict):
    return JobFilter(FilterConfig.from_dict(config_dict["filters"]))


@pytest.fixture()
def rio_filter(rio_config_dict):
    return JobFilter(FilterConfig.from_dict(rio_config_dict["filters"]))
