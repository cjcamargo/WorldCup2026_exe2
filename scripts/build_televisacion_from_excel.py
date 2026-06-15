from __future__ import annotations

import argparse
import json
from pathlib import Path

from openpyxl import load_workbook


CHANNEL_COLUMNS = [
    "Caracol TV",
    "RCN Televisión",
    "DSports",
    "Win+",
    "Paramount+",
    "Disney+",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build config/televisacion.json from the broadcast schedule Excel.")
    parser.add_argument("excel_path", type=Path)
    parser.add_argument("--output", type=Path, default=Path("config/televisacion.json"))
    args = parser.parse_args()

    workbook = load_workbook(args.excel_path, data_only=True)
    sheet = workbook["Partidos"]
    headers = [cell.value for cell in sheet[1]]
    indexes = {header: idx for idx, header in enumerate(headers)}

    missing = [column for column in ["No.", *CHANNEL_COLUMNS] if column not in indexes]
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    matches: dict[str, list[str]] = {}
    for row in sheet.iter_rows(min_row=2, values_only=True):
        match_number = row[indexes["No."]]
        if not match_number:
            continue
        match_id = f"M{int(match_number):03d}"
        matches[match_id] = [
            channel
            for channel in CHANNEL_COLUMNS
            if row[indexes[channel]] == "X"
        ]

    payload = {
        "source": {
            "name": "Calendario Mundial 2026 - canales por partido",
            "url": "https://www.jorgebarajas.com/wp-content/uploads/2026/04/Calendario-Copa-Mundial-de-la-FIFA-2026-Tabloide-4.pdf",
            "validated_with": args.excel_path.name,
            "retrieved_at": "2026-06-14",
        },
        "channels": CHANNEL_COLUMNS,
        "matches": matches,
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(matches)} matches to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
