from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from polla.config import ROOT, config_path, load_json
from polla.google_auth import run_local_oauth


def main() -> int:
    cfg = load_json(config_path("google_drive.json"))
    credentials_path = ROOT / cfg["credentials_path"]
    token_path = ROOT / cfg["token_path"]
    run_local_oauth(credentials_path, token_path, cfg["scopes"])
    print(f"Token guardado en: {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
