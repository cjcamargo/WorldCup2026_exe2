from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)


def config_path(name: str) -> Path:
    return ROOT / "config" / name


def data_path(*parts: str) -> Path:
    return ROOT / "data" / Path(*parts)


def output_path(*parts: str) -> Path:
    return ROOT / "outputs" / Path(*parts)


def log_path(*parts: str) -> Path:
    return ROOT / "logs" / Path(*parts)
