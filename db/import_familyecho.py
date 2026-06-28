"""
db/import_familyecho.py — импорт данных из FamilyEcho в SQLite.

Поддерживаемые форматы:
  1. FamilyEcho CSV (.csv)  — прямой экспорт «Download → CSV»
  2. GEDCOM (.ged)          — стандартный экспорт FamilyEcho

Запуск:
    python -m db.import_familyecho data.csv
    python -m db.import_familyecho data.ged
    python -m db.import_familyecho data.csv --probe    # показать колонки без импорта
    python -m db.import_familyecho data.csv --replace  # удалить старые данные перед импортом
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from db.schema import DB_PATH, get_connection, init_db


# ---------------------------------------------------------------------------
# Утилиты дат
# ---------------------------------------------------------------------------

def _build_iso_date(year: str, month: str = "", day: str = "") -> str:
    """'1978', '5', '7' → '1978-05-07'; '1978', '5', '' → '1978-05'; '1978' → '1978'"""
    y = year.strip()
    m = month.strip()
    d = day.strip()
    if not y:
        return ""
    try:
        if d and m:
            return f"{y}-{int(m):02d}-{int(d):02d}"
        if m:
            return f"{y}-{int(m):02d}"
        return y
    except (ValueError, TypeError):
        return y


_MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}


def _parse_gedcom_date(raw: str) -> str:
    """'15 MAR 1902' → '1902-03-15'; '1902' → '1902'"""
    raw = raw.strip()
    if not raw:
        return ""
    parts = raw.split()
    if len(parts) == 3:
        day, mon, year = parts
        m = _MONTH_MAP.get(mon.upper(), "")
        if m:
            return f"{year}-{m}-{day.zfill(2)}"
    if len(parts) == 2:
        mon, year = parts
        m = _MONTH_MAP.get(mon.upper(), "")
        if m:
            return f"{year}-{m}"
    if re.fullmatch(r"\d{4}", parts[0]):
        return parts[0]
    return raw


# ---------------------------------------------------------------------------
# FamilyEcho CSV-парсер (специализированный)
# ---------------------------------------------------------------------------

_FE_CSV_MARKER = {"Mother ID", "Father ID", "Partner ID", "Given names now"}


def _is_familyecho_csv(header: list[str]) -> bool:
    return bool(_FE_CSV_MARKER & set(header))


def _parse_familyecho_csv(path: Path) -> tuple[list[dict], list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r.get("ID", "").strip()]

    persons: list[dict] = []
    rels: list[dict] = []
    seen_spouse_pairs: set[frozenset] = set()

    for row in rows:
        pid = row["ID"].strip()

        gender_raw = row.get("Gender", "").strip()
        gender = ("M" if gender_raw == "Male"
                  else "F" if gender_raw == "Female"
                  else "")

        birth_date  = _build_iso_date(row.get("Birth year",""),  row.get("Birth month",""),  row.get("Birth day",""))
        death_date  = _build_iso_date(row.get("Death year",""),  row.get("Death month",""),  row.get("Death day",""))
        burial_date = _build_iso_date(row.get("Burial year",""), row.get("Burial month",""), row.get("Burial day",""))

        surname_now   = row.get("Surname now", "").strip()
        surname_birth = row.get("Surname at birth", "").strip()
        maiden = surname_birth if (surname_birth and surname_birth != surname_now) else ""

        activities = row.get("Activities", "").strip()
        interests  = row.get("Interests",  "").strip()
        interests_combined = " / ".join(x for x in [interests, activities] if x)

        persons.append({
            "id":          pid,
            "first_name":  row.get("Given names now", "").strip(),
            "last_name":   surname_now,
            "maiden_name": maiden,
            "nickname":    row.get("Nickname", "").strip(),
            "title":       row.get("Title",    "").strip(),
            "gender":      gender,
            "birth_date":  birth_date,
            "birth_place": row.get("Birth place",   "").strip(),
            "death_date":  death_date,
            "death_place": row.get("Death place",   "").strip(),
            "death_cause": row.get("Cause of death","").strip(),
            "burial_date":  burial_date,
            "burial_place": row.get("Burial place",  "").strip(),
            "email":        row.get("Email",    "").strip(),
            "phone_home":   row.get("Home tel", "").strip(),
            "phone_work":   row.get("Work tel", "").strip(),
            "phone_mobile": row.get("Mobile",   "").strip(),
            "address":      row.get("Address",  "").strip(),
            "occupation":   row.get("Profession","").strip(),
            "company":      row.get("Company",   "").strip(),
            "interests":    interests_combined,
            "bio":          row.get("Bio notes", "").strip(),
            "photo_path":   "",
            "source_ref":   "",
            **{f"custom_{i}": "" for i in range(1, 10)},
        })

        # ── Родительские связи ────────────────────────────────────────────
        parent_cols = [
            ("Father ID", 1), ("Mother ID", 1),
            ("Second father ID", 0), ("Second mother ID", 0),
            ("Third father ID", 0),  ("Third mother ID", 0),
        ]
        for col, bio in parent_cols:
            par_id = row.get(col, "").strip()
            if par_id:
                rels.append({
                    "person1_id":    par_id,
                    "person2_id":    pid,
                    "rel_type":      "parent-child",
                    "is_biological": bio,
                    "marriage_date":  "",
                    "marriage_place": "",
                    "divorce_date":   "",
                })

        # ── Текущий партнёр ───────────────────────────────────────────────
        partner_id = row.get("Partner ID", "").strip()
        if partner_id:
            pair_key = frozenset((pid, partner_id))
            if pair_key not in seen_spouse_pairs:
                seen_spouse_pairs.add(pair_key)
                m_date = _build_iso_date(
                    row.get("Partnership year",  ""),
                    row.get("Partnership month", ""),
                    row.get("Partnership day",   ""),
                )
                rels.append({
                    "person1_id":    pid,
                    "person2_id":    partner_id,
                    "rel_type":      "spouse",
                    "is_biological": 0,
                    "marriage_date":  m_date,
                    "marriage_place": "",
                    "divorce_date":   "",
                })

        # ── Бывшие партнёры ───────────────────────────────────────────────
        for ex_raw in [row.get("Ex-partner IDs",""), row.get("Extra partner IDs","")]:
            for ex_id in ex_raw.split(","):
                ex_id = ex_id.strip()
                if not ex_id:
                    continue
                pair_key = frozenset((pid, ex_id))
                if pair_key not in seen_spouse_pairs:
                    seen_spouse_pairs.add(pair_key)
                    rels.append({
                        "person1_id":    pid,
                        "person2_id":    ex_id,
                        "rel_type":      "spouse",
                        "is_biological": 0,
                        "marriage_date":  "",
                        "marriage_place": "",
                        "divorce_date":   "?",
                    })

    return persons, rels


# ---------------------------------------------------------------------------
# GEDCOM-парсер
# ---------------------------------------------------------------------------

def _parse_gedcom(text: str) -> tuple[list[dict], list[dict]]:
    persons:  dict[str, dict] = {}
    families: dict[str, dict] = {}

    cur_indi: dict | None = None
    cur_fam:  dict | None = None
    cur_indi_id = ""
    cur_fam_id  = ""
    cur_tag = ""

    def _empty_person(pid: str) -> dict:
        return {
            "id": pid,
            "first_name": "", "last_name": "", "maiden_name": "",
            "nickname": "", "title": "", "gender": "",
            "birth_date": "", "birth_place": "",
            "death_date": "", "death_place": "", "death_cause": "",
            "burial_date": "", "burial_place": "",
            "email": "", "phone_home": "", "phone_work": "",
            "phone_mobile": "", "address": "",
            "occupation": "", "company": "", "interests": "",
            "bio": "", "photo_path": "", "source_ref": "",
            **{f"custom_{i}": "" for i in range(1, 10)},
        }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            level = int(parts[0])
        except ValueError:
            continue
        tag   = parts[1] if len(parts) > 1 else ""
        value = parts[2] if len(parts) > 2 else ""

        # ── Уровень 0 ────────────────────────────────────────────────────
        if level == 0:
            cur_tag = ""
            if tag.startswith("@I") and value == "INDI":
                cur_indi_id = tag.strip("@")
                cur_indi = _empty_person(cur_indi_id)
                persons[cur_indi_id] = cur_indi
                cur_fam = None
            elif tag.startswith("@F") and value == "FAM":
                cur_fam_id = tag.strip("@")
                cur_fam = {
                    "id": cur_fam_id, "husb": "", "wife": "",
                    "children": [],
                    "marriage_date": "", "marriage_place": "",
                    "divorce_date": "",
                }
                families[cur_fam_id] = cur_fam
                cur_indi = None
            else:
                cur_indi = None
                cur_fam  = None
            continue

        # ── Уровень 1 ────────────────────────────────────────────────────
        if level == 1:
            cur_tag = tag

            if cur_indi is not None:
                if tag == "NAME":
                    m = re.match(r"(.*?)/([^/]*)/\s*(.*)", value)
                    if m:
                        cur_indi["first_name"] = (m.group(1) + " " + m.group(3)).strip()
                        cur_indi["last_name"]  = m.group(2).strip()
                    else:
                        pts = value.strip().split()
                        cur_indi["last_name"]  = pts[0] if pts else ""
                        cur_indi["first_name"] = " ".join(pts[1:])
                elif tag == "SEX":
                    cur_indi["gender"] = value.strip().upper()
                elif tag == "NOTE":
                    cur_indi["bio"] = value.strip()
                elif tag == "OCCU":
                    cur_indi["occupation"] = value.strip()
                elif tag == "EMAIL":
                    cur_indi["email"] = value.strip()
                elif tag == "PHON":
                    cur_indi["phone_home"] = value.strip()

            if cur_fam is not None:
                if tag == "HUSB":
                    cur_fam["husb"] = value.strip("@")
                elif tag == "WIFE":
                    cur_fam["wife"] = value.strip("@")
                elif tag == "CHIL":
                    cur_fam["children"].append(value.strip("@"))
                elif tag == "DIV":
                    cur_fam["divorce_date"] = "?"
            continue

        # ── Уровень 2 ────────────────────────────────────────────────────
        if level == 2:
            if cur_indi is not None:
                if cur_tag == "NAME":
                    if tag == "NICK":
                        cur_indi["nickname"] = value.strip()
                    elif tag == "GIVN":
                        if not cur_indi["first_name"]:
                            cur_indi["first_name"] = value.strip()
                    elif tag == "SURN":
                        if not cur_indi["last_name"]:
                            cur_indi["last_name"] = value.strip()
                    elif tag == "_MARNM":
                        cur_indi["maiden_name"] = value.strip()
                elif cur_tag == "BIRT":
                    if tag == "DATE":
                        cur_indi["birth_date"] = _parse_gedcom_date(value)
                    elif tag == "PLAC":
                        cur_indi["birth_place"] = value.strip()
                elif cur_tag == "DEAT":
                    if tag == "DATE":
                        cur_indi["death_date"] = _parse_gedcom_date(value)
                    elif tag == "PLAC":
                        cur_indi["death_place"] = value.strip()
                    elif tag == "CAUS":
                        cur_indi["death_cause"] = value.strip()
                elif cur_tag == "BURI":
                    if tag == "DATE":
                        cur_indi["burial_date"] = _parse_gedcom_date(value)
                    elif tag == "PLAC":
                        cur_indi["burial_place"] = value.strip()
                elif cur_tag == "RESI":
                    if tag == "ADDR":
                        cur_indi["address"] = value.strip()
                elif cur_tag == "NOTE":
                    cur_indi["bio"] += " " + value.strip()

            if cur_fam is not None:
                if cur_tag == "MARR":
                    if tag == "DATE":
                        cur_fam["marriage_date"] = _parse_gedcom_date(value)
                    elif tag == "PLAC":
                        cur_fam["marriage_place"] = value.strip()

    # Конвертируем family → relationships
    rels: list[dict] = []
    for fam in families.values():
        husb = fam.get("husb")
        wife = fam.get("wife")
        if husb and wife:
            rels.append({
                "person1_id": husb, "person2_id": wife,
                "rel_type": "spouse", "is_biological": 0,
                "marriage_date":  fam.get("marriage_date", ""),
                "marriage_place": fam.get("marriage_place", ""),
                "divorce_date":   fam.get("divorce_date", ""),
            })
        for child in fam.get("children", []):
            for parent in [husb, wife]:
                if parent:
                    rels.append({
                        "person1_id": parent, "person2_id": child,
                        "rel_type": "parent-child", "is_biological": 1,
                        "marriage_date": "", "marriage_place": "", "divorce_date": "",
                    })

    return list(persons.values()), rels


# ---------------------------------------------------------------------------
# Сохранение в БД
# ---------------------------------------------------------------------------

_PERSON_FIELDS = [
    "id", "first_name", "last_name", "maiden_name", "nickname", "title",
    "gender", "birth_date", "birth_place", "death_date", "death_place",
    "death_cause", "burial_date", "burial_place", "email", "phone_home",
    "phone_work", "phone_mobile", "address", "occupation", "company",
    "interests", "bio", "photo_path", "source_ref",
    *[f"custom_{i}" for i in range(1, 10)],
]


def _save(persons: list[dict], rels: list[dict],
          db_path: Path, replace: bool = False) -> None:
    init_db(db_path)

    with get_connection(db_path) as conn:
        if replace:
            conn.execute("DELETE FROM relationships")
            conn.execute("DELETE FROM persons")
            print("Старые данные удалены.")

        for p in persons:
            cols = ", ".join(_PERSON_FIELDS)
            ph   = ", ".join("?" * len(_PERSON_FIELDS))
            upd  = ", ".join(f"{f} = excluded.{f}" for f in _PERSON_FIELDS if f != "id")
            vals = tuple(p.get(f, "") for f in _PERSON_FIELDS)
            conn.execute(
                f"INSERT INTO persons ({cols}) VALUES ({ph}) "
                f"ON CONFLICT(id) DO UPDATE SET {upd}",
                vals,
            )

        # Кешируем существующие ID для проверки целостности
        existing_ids = {row[0] for row in conn.execute("SELECT id FROM persons")}

        inserted = skipped = 0
        for r in rels:
            if r["person1_id"] not in existing_ids or r["person2_id"] not in existing_ids:
                skipped += 1
                continue
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO relationships
                        (person1_id, person2_id, rel_type, is_biological,
                         marriage_date, marriage_place, divorce_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (r["person1_id"], r["person2_id"], r["rel_type"],
                     r.get("is_biological", 1),
                     r.get("marriage_date", ""), r.get("marriage_place", ""),
                     r.get("divorce_date", "")),
                )
                inserted += 1
            except Exception as exc:
                print(f"  Ошибка связи {r['person1_id']}→{r['person2_id']}: {exc}")
                skipped += 1

    print(f"Сохранено персон: {len(persons)}, связей: {inserted} (пропущено: {skipped})")


# ---------------------------------------------------------------------------
# Probe (диагностика колонок CSV)
# ---------------------------------------------------------------------------

def _probe_csv(path: Path) -> None:
    with open(path, newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f))
    print(f"Колонок: {len(header)}")
    for i, col in enumerate(header):
        print(f"  [{i:2d}] {col!r}")
    if _is_familyecho_csv(header):
        print("\n✓ Формат определён как FamilyEcho CSV")
    else:
        print("\n! Формат НЕ распознан как FamilyEcho CSV")


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def import_file(path: Path, db_path: Path = DB_PATH,
                probe: bool = False, replace: bool = False) -> None:
    suffix = path.suffix.lower()

    if probe and suffix == ".csv":
        _probe_csv(path)
        return

    if suffix == ".ged":
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        persons, rels = _parse_gedcom(text)
    elif suffix == ".csv":
        with open(path, newline="", encoding="utf-8-sig") as f:
            header = next(csv.reader(f))
        if _is_familyecho_csv(header):
            persons, rels = _parse_familyecho_csv(path)
        else:
            sys.exit("Неизвестный CSV-формат. Запустите с --probe чтобы увидеть колонки.")
    else:
        sys.exit(f"Неподдерживаемый формат: {suffix}. Ожидается .ged или .csv")

    print(f"Найдено персон: {len(persons)}, связей: {len(rels)}")
    _save(persons, rels, db_path, replace=replace)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Импорт FamilyEcho → SQLite")
    parser.add_argument("file", help="Путь к .csv или .ged файлу")
    parser.add_argument("--db",      default=str(DB_PATH))
    parser.add_argument("--probe",   action="store_true",
                        help="Показать колонки CSV без импорта")
    parser.add_argument("--replace", action="store_true",
                        help="Удалить старые данные перед импортом")
    args = parser.parse_args()
    import_file(Path(args.file), Path(args.db), probe=args.probe, replace=args.replace)
