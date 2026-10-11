"""Carregamento do config.yaml + .env, com caminhos relativos ao arquivo de config."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


def load_config(path: str | Path) -> dict:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {path}")
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido em {path}: {exc}") from exc

    # .env ao lado do config.yaml (credenciais de notificação, contato)
    load_dotenv(path.parent / ".env")

    # Caminhos relativos passam a ser relativos à pasta do config, não ao cwd,
    # para o script funcionar igual via cron, Agendador do Windows etc.
    base = path.parent
    storage = cfg.setdefault("storage", {})
    for key, default in (("database", "data/jobs.db"), ("output_dir", "output")):
        storage[key] = str((base / storage.get(key, default)).resolve())
    http = cfg.setdefault("http", {})
    http["cache_dir"] = str((base / http.get("cache_dir", ".cache/http")).resolve())
    log_cfg = cfg.setdefault("logging", {})
    if log_cfg.get("file"):
        log_cfg["file"] = str((base / log_cfg["file"]).resolve())

    if not cfg.get("filters"):
        raise ConfigError("Seção 'filters' ausente no config.yaml")
    if not any((s or {}).get("enabled") for s in (cfg.get("sources") or {}).values()):
        raise ConfigError("Nenhuma fonte habilitada em 'sources'")
    return cfg


def setup_logging(cfg: dict, verbose: bool = False) -> None:
    level_name = "DEBUG" if verbose else str(cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    if cfg.get("file"):
        log_path = Path(cfg["file"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    # bibliotecas de terceiros muito verbosas
    logging.getLogger("urllib3").setLevel(logging.WARNING)
