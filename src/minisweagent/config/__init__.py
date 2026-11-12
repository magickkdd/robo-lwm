"""Bundled configuration files."""

from pathlib import Path

import yaml

builtin_config_dir = Path(__file__).parent


def load_default_config() -> dict:
    """Load the bundled default.yaml (agent prompts and model templates)."""
    return yaml.safe_load((builtin_config_dir / "default.yaml").read_text(encoding="utf-8"))
