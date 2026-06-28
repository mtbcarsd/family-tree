"""
db/migrate_csv.py — переносит данные из старого family_data.csv в SQLite.

Старая схема CSV:
    id, name, parent_id, birth_year, death_year, gender,
    location, source_part, notes

Запуск:
    python -m db.migrate_csv
    python -m db.migrate_csv --csv output/family_data.csv --db output/family_tree.db
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from db.schema import DB_PATH, get_connection, init_db


_CSV_PATH = Path(__file__).parent.parent / "output" / "family_data.csv"


def _split_name(full_name: str) -> tuple[str, str]:
    """'Дымков Михаил Пахомович' → ('Михаил Пахомович', 'Дымков')"""
    parts = full_name.strip().split()
    if not parts:
        return ("", "")
    # Эвристика: первое слово с заглавной буквы и оканчивающееся на -ов/-ев/-ин/-их — фамилия
    last, first = parts[0], " ".join(parts[1:])
    return first, last


def _year_to_date(year_val: str) -> str:
    """'1902' → '1902', '' → ''"""
    year_val = (year_val or "").strip()
    if re.fullmatch(r"\d{4}", year_val):
        return year_val
    return ""


def migrate(csv_path: Path = _CSV_PATH, db_path: Path = DB_PATH) -> None:
    init_db(db_path)

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    with get_connection(db_path) as conn:
        inserted_persons = 0
        inserted_rels = 0

        for row in rows:
            pid      = row["id"].strip()
            name     = row["name"].strip()
            gender   = row.get("gender", "").strip().upper()
            b_year   = _year_to_date(row.get("birth_year", ""))
            d_year   = _year_to_date(row.get("death_year", ""))
            location = row.get("location", "").strip()
            source   = row.get("source_part", "").strip()
            notes    = row.get("notes", "").strip()

            first_name, last_name = _split_name(name)

            conn.execute(
                """
                INSERT INTO persons (
                    id, first_name, last_name,
                    gender, birth_date, death_date,
                    birth_place, bio, source_ref
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    first_name  = excluded.first_name,
                    last_name   = excluded.last_name,
                    gender      = excluded.gender,
                    birth_date  = excluded.birth_date,
                    death_date  = excluded.death_date,
                    birth_place = excluded.birth_place,
                    bio         = excluded.bio,
                    source_ref  = excluded.source_ref
                """,
                (pid, first_name, last_name, gender,
                 b_year, d_year, location, notes, source),
            )
            inserted_persons += 1

        # Связи parent-child
        for row in rows:
            pid    = row["id"].strip()
            par_id = row.get("parent_id", "").strip()
            if not par_id:
                continue
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO relationships
                        (person1_id, person2_id, rel_type, is_biological)
                    VALUES (?, ?, 'parent-child', 1)
                    """,
                    (par_id, pid),
                )
                inserted_rels += 1
            except Exception as exc:
                print(f"  Пропущена связь {par_id}→{pid}: {exc}")

    print(f"Мигрировано персон: {inserted_persons}, связей: {inserted_rels}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Миграция CSV → SQLite")
    parser.add_argument("--csv", default=str(_CSV_PATH))
    parser.add_argument("--db",  default=str(DB_PATH))
    args = parser.parse_args()
    migrate(Path(args.csv), Path(args.db))
