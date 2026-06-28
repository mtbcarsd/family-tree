"""
db/schema.py — инициализация SQLite-базы семейного древа.

Запуск напрямую для создания/пересоздания пустой БД:
    python -m db.schema
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "output" / "family_tree.db"

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = """
-- Персоны
CREATE TABLE IF NOT EXISTS persons (
    id              TEXT PRIMARY KEY,

    -- Имя
    first_name      TEXT NOT NULL DEFAULT '',
    last_name       TEXT NOT NULL DEFAULT '',
    maiden_name     TEXT NOT NULL DEFAULT '',  -- фамилия при рождении
    nickname        TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',  -- Пр, Д-р, ...

    -- Пол: 'M' | 'F' | ''
    gender          TEXT NOT NULL DEFAULT '',

    -- Рождение
    birth_date      TEXT NOT NULL DEFAULT '',  -- ISO-8601 или частичная: '1902', '1902-05'
    birth_place     TEXT NOT NULL DEFAULT '',

    -- Смерть
    death_date      TEXT NOT NULL DEFAULT '',
    death_place     TEXT NOT NULL DEFAULT '',
    death_cause     TEXT NOT NULL DEFAULT '',

    -- Погребение
    burial_date     TEXT NOT NULL DEFAULT '',
    burial_place    TEXT NOT NULL DEFAULT '',

    -- Контакты (актуально для живых)
    email           TEXT NOT NULL DEFAULT '',
    phone_home      TEXT NOT NULL DEFAULT '',
    phone_work      TEXT NOT NULL DEFAULT '',
    phone_mobile    TEXT NOT NULL DEFAULT '',
    address         TEXT NOT NULL DEFAULT '',

    -- Профессия
    occupation      TEXT NOT NULL DEFAULT '',
    company         TEXT NOT NULL DEFAULT '',
    interests       TEXT NOT NULL DEFAULT '',

    -- Биография / заметки
    bio             TEXT NOT NULL DEFAULT '',

    -- Фото (путь относительно корня проекта)
    photo_path      TEXT NOT NULL DEFAULT '',

    -- До 9 пользовательских полей (как в FamilyEcho)
    custom_1        TEXT NOT NULL DEFAULT '',
    custom_2        TEXT NOT NULL DEFAULT '',
    custom_3        TEXT NOT NULL DEFAULT '',
    custom_4        TEXT NOT NULL DEFAULT '',
    custom_5        TEXT NOT NULL DEFAULT '',
    custom_6        TEXT NOT NULL DEFAULT '',
    custom_7        TEXT NOT NULL DEFAULT '',
    custom_8        TEXT NOT NULL DEFAULT '',
    custom_9        TEXT NOT NULL DEFAULT '',

    -- Служебные
    source_ref      TEXT NOT NULL DEFAULT '',  -- ссылка на источник
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Связи между людьми
CREATE TABLE IF NOT EXISTS relationships (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    person1_id      TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    person2_id      TEXT NOT NULL REFERENCES persons(id) ON DELETE CASCADE,

    -- Тип: 'parent-child' | 'spouse' | 'sibling'
    rel_type        TEXT NOT NULL,

    -- Направление для parent-child: person1 — родитель, person2 — ребёнок
    -- Для spouse и sibling — направление не важно

    is_biological   INTEGER NOT NULL DEFAULT 1,  -- 1=да, 0=нет (усыновление, сводные и т.д.)

    -- Только для супругов
    marriage_date   TEXT NOT NULL DEFAULT '',
    marriage_place  TEXT NOT NULL DEFAULT '',
    divorce_date    TEXT NOT NULL DEFAULT '',

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- Исключаем дубликаты пар одного типа
    UNIQUE (person1_id, person2_id, rel_type)
);

-- Быстрый поиск по имени
CREATE INDEX IF NOT EXISTS idx_persons_last_name  ON persons (last_name);
CREATE INDEX IF NOT EXISTS idx_persons_first_name ON persons (first_name);

-- Быстрый обход графа
CREATE INDEX IF NOT EXISTS idx_rel_p1 ON relationships (person1_id, rel_type);
CREATE INDEX IF NOT EXISTS idx_rel_p2 ON relationships (person2_id, rel_type);

-- Триггер обновления updated_at
CREATE TRIGGER IF NOT EXISTS trg_persons_updated
AFTER UPDATE ON persons
BEGIN
    UPDATE persons SET updated_at = datetime('now') WHERE id = NEW.id;
END;
"""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.executescript(_DDL)
    print(f"База данных инициализирована: {db_path}")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
