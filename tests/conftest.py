import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jobcrawler.filters import FilterConfig, JobFilter  # noqa: E402
from jobcrawler.profiles import deep_merge  # noqa: E402


@pytest.fixture(scope="session")
def full_config():
    """config.yaml como está no repositório (dois perfis: rio e remoto)."""
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _single_profile(cfg: dict, key: str) -> dict:
    """Config de perfil único (sem `profiles`), com os filtros já mesclados.
    Também exercita o caminho de compatibilidade com configs antigos."""
    single = copy.deepcopy(cfg)
    profile = single.pop("profiles")[key]
    single["filters"] = deep_merge(cfg["filters"], profile.get("filters") or {})
    return single


@pytest.fixture(scope="session")
def config_dict(full_config):
    """Perfil remoto: EUA/Canadá/Austrália/Global."""
    return _single_profile(full_config, "remoto")


@pytest.fixture(scope="session")
def rio_config_dict(full_config):
    """Perfil Rio: híbrido no Rio de Janeiro e região metropolitana."""
    return _single_profile(full_config, "rio")


@pytest.fixture()
def job_filter(config_dict):
    return JobFilter(FilterConfig.from_dict(config_dict["filters"]))


@pytest.fixture()
def rio_filter(rio_config_dict):
    return JobFilter(FilterConfig.from_dict(rio_config_dict["filters"]))
