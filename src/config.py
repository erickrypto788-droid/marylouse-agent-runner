from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # permite rodar sem instalar python-dotenv
    def load_dotenv(*args, **kwargs):
        return False


ROOT = Path(__file__).resolve().parents[1]


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(config_path: str | None = None) -> Dict[str, Any]:
    load_dotenv(ROOT / ".env")

    default_config = load_yaml(ROOT / "config.example.yaml")
    user_config_path = Path(config_path) if config_path else ROOT / "config.yaml"
    if not user_config_path.is_absolute():
        user_config_path = ROOT / user_config_path
    user_config = load_yaml(user_config_path)
    cfg = deep_merge(default_config, user_config)

    # Overrides por env
    dry_run_env = os.getenv("DRY_RUN")
    if dry_run_env is not None:
        cfg.setdefault("agent", {})["dry_run"] = dry_run_env.strip().lower() in {"1", "true", "yes", "sim"}

    post_limit_env = os.getenv("POST_LIMIT_PER_RUN")
    if post_limit_env:
        cfg.setdefault("agent", {})["post_limit_per_run"] = int(post_limit_env)

    max_candidates_env = os.getenv("MAX_CANDIDATES_PER_RUN")
    if max_candidates_env:
        cfg.setdefault("agent", {})["max_candidates_per_run"] = int(max_candidates_env)

    recent_days_env = os.getenv("RECENT_DUPLICATE_DAYS")
    if recent_days_env:
        cfg.setdefault("agent", {})["recent_duplicate_days"] = int(recent_days_env)

    return cfg


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def root_path(*parts: str) -> Path:
    return ROOT.joinpath(*parts)
