"""
db/family_graph.py — движок отношений семейного графа.

Загружает данные из SQLite и предоставляет API для обхода дерева/графа
без зависимости от конкретного UI-фреймворка.

Использование:
    from db.family_graph import FamilyGraph
    g = FamilyGraph()
    parents   = g.get_parents("I1")
    children  = g.get_children("I1")
    spouses   = g.get_spouses("I1")
    ancestors = g.get_ancestors("I1", depth=3)
    desc      = g.get_descendants("I1", depth=2)
    path      = g.find_relationship("I1", "I5")
    gen       = g.get_generation("I1")
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from db.schema import DB_PATH, get_connection


# ---------------------------------------------------------------------------
# Структуры данных
# ---------------------------------------------------------------------------

@dataclass
class Person:
    id: str
    first_name: str = ""
    last_name: str  = ""
    maiden_name: str = ""
    nickname: str   = ""
    gender: str     = ""       # 'M' | 'F' | ''
    birth_date: str = ""
    birth_place: str = ""
    death_date: str  = ""
    death_place: str = ""
    occupation: str  = ""
    bio: str         = ""
    photo_path: str  = ""
    source_ref: str  = ""

    @property
    def display_name(self) -> str:
        parts = [self.last_name, self.first_name]
        name = " ".join(p for p in parts if p)
        if self.maiden_name:
            name += f" (урожд. {self.maiden_name})"
        return name or self.id

    @property
    def birth_year(self) -> Optional[int]:
        return _extract_year(self.birth_date)

    @property
    def death_year(self) -> Optional[int]:
        return _extract_year(self.death_date)


@dataclass
class Relationship:
    person1_id: str
    person2_id: str
    rel_type: str          # 'parent-child' | 'spouse' | 'sibling'
    is_biological: bool = True
    marriage_date: str  = ""
    marriage_place: str = ""
    divorce_date: str   = ""


def _extract_year(date_str: str) -> Optional[int]:
    if not date_str:
        return None
    import re
    m = re.search(r"\d{4}", date_str)
    return int(m.group()) if m else None


# ---------------------------------------------------------------------------
# Граф
# ---------------------------------------------------------------------------

class FamilyGraph:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._persons:    dict[str, Person]           = {}
        self._rels:       list[Relationship]          = []
        # Вспомогательные индексы
        self._parents:    dict[str, list[str]]        = defaultdict(list)  # child → parents
        self._children:   dict[str, list[str]]        = defaultdict(list)  # parent → children
        self._spouses:    dict[str, list[str]]        = defaultdict(list)
        self._siblings:   dict[str, list[str]]        = defaultdict(list)

        self._load(db_path)
        self._build_indexes()

    # ── Загрузка ─────────────────────────────────────────────────────────────

    def _load(self, db_path: Path) -> None:
        with get_connection(db_path) as conn:
            for row in conn.execute("SELECT * FROM persons"):
                p = Person(
                    id          = row["id"],
                    first_name  = row["first_name"],
                    last_name   = row["last_name"],
                    maiden_name = row["maiden_name"],
                    nickname    = row["nickname"],
                    gender      = row["gender"],
                    birth_date  = row["birth_date"],
                    birth_place = row["birth_place"],
                    death_date  = row["death_date"],
                    death_place = row["death_place"],
                    occupation  = row["occupation"],
                    bio         = row["bio"],
                    photo_path  = row["photo_path"],
                    source_ref  = row["source_ref"],
                )
                self._persons[p.id] = p

            for row in conn.execute("SELECT * FROM relationships"):
                r = Relationship(
                    person1_id    = row["person1_id"],
                    person2_id    = row["person2_id"],
                    rel_type      = row["rel_type"],
                    is_biological = bool(row["is_biological"]),
                    marriage_date = row["marriage_date"],
                    marriage_place= row["marriage_place"],
                    divorce_date  = row["divorce_date"],
                )
                self._rels.append(r)

    def _build_indexes(self) -> None:
        for r in self._rels:
            if r.rel_type == "parent-child":
                self._children[r.person1_id].append(r.person2_id)
                self._parents[r.person2_id].append(r.person1_id)
            elif r.rel_type == "spouse":
                self._spouses[r.person1_id].append(r.person2_id)
                self._spouses[r.person2_id].append(r.person1_id)
            elif r.rel_type == "sibling":
                self._siblings[r.person1_id].append(r.person2_id)
                self._siblings[r.person2_id].append(r.person1_id)

    # ── Базовые запросы ──────────────────────────────────────────────────────

    def get_person(self, pid: str) -> Optional[Person]:
        return self._persons.get(pid)

    def all_persons(self) -> list[Person]:
        return list(self._persons.values())

    def get_parents(self, pid: str, biological_only: bool = False) -> list[Person]:
        ids = self._parents.get(pid, [])
        if biological_only:
            # Проверяем флаг в relationships
            bio_ids = {
                r.person1_id for r in self._rels
                if r.rel_type == "parent-child"
                and r.person2_id == pid
                and r.is_biological
            }
            ids = [i for i in ids if i in bio_ids]
        return [self._persons[i] for i in ids if i in self._persons]

    def get_children(self, pid: str, biological_only: bool = False) -> list[Person]:
        ids = self._children.get(pid, [])
        if biological_only:
            bio_ids = {
                r.person2_id for r in self._rels
                if r.rel_type == "parent-child"
                and r.person1_id == pid
                and r.is_biological
            }
            ids = [i for i in ids if i in bio_ids]
        return [self._persons[i] for i in ids if i in self._persons]

    def get_spouses(self, pid: str) -> list[tuple[Person, Relationship]]:
        """Возвращает [(Person, Relationship), ...] — с деталями брака."""
        result = []
        for r in self._rels:
            if r.rel_type != "spouse":
                continue
            other_id = None
            if r.person1_id == pid:
                other_id = r.person2_id
            elif r.person2_id == pid:
                other_id = r.person1_id
            if other_id and other_id in self._persons:
                result.append((self._persons[other_id], r))
        return result

    def get_siblings(self, pid: str) -> list[Person]:
        # Явные sibling-связи
        explicit = set(self._siblings.get(pid, []))
        # Выводим через общих родителей
        via_parents: set[str] = set()
        for parent in self._parents.get(pid, []):
            for sib_id in self._children.get(parent, []):
                if sib_id != pid:
                    via_parents.add(sib_id)
        all_sibs = explicit | via_parents
        return [self._persons[i] for i in all_sibs if i in self._persons]

    # ── Обход в глубину ──────────────────────────────────────────────────────

    def get_ancestors(self, pid: str, depth: int = 99) -> dict[str, int]:
        """Возвращает {person_id: уровень_вверх} для всех предков до depth."""
        result: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque([(pid, 0)])
        while queue:
            cur, level = queue.popleft()
            if level >= depth:
                continue
            for par_id in self._parents.get(cur, []):
                if par_id not in result:
                    result[par_id] = level + 1
                    queue.append((par_id, level + 1))
        return result

    def get_descendants(self, pid: str, depth: int = 99) -> dict[str, int]:
        """Возвращает {person_id: уровень_вниз} для всех потомков до depth."""
        result: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque([(pid, 0)])
        while queue:
            cur, level = queue.popleft()
            if level >= depth:
                continue
            for child_id in self._children.get(cur, []):
                if child_id not in result:
                    result[child_id] = level + 1
                    queue.append((child_id, level + 1))
        return result

    def get_subtree_ids(self, pid: str) -> set[str]:
        """pid + все потомки."""
        return {pid} | set(self.get_descendants(pid).keys())

    # ── Поколения ────────────────────────────────────────────────────────────

    def get_generation(self, pid: str) -> int:
        """Глубина от корня (узел без родителей = 0)."""
        if not self._parents.get(pid):
            return 0
        return 1 + max(self.get_generation(p) for p in self._parents[pid])

    def all_generations(self) -> dict[str, int]:
        cache: dict[str, int] = {}

        def _gen(pid: str) -> int:
            if pid in cache:
                return cache[pid]
            parents = self._parents.get(pid, [])
            result = 0 if not parents else 1 + max(_gen(p) for p in parents)
            cache[pid] = result
            return result

        return {pid: _gen(pid) for pid in self._persons}

    # ── Поиск пути ───────────────────────────────────────────────────────────

    def find_relationship(self, id1: str, id2: str) -> Optional[list[str]]:
        """
        BFS: кратчайший путь через граф всех связей между id1 и id2.
        Возвращает список person_id от id1 до id2, или None если путь не найден.
        """
        # Строим неориентированный граф соседей
        neighbors: dict[str, set[str]] = defaultdict(set)
        for r in self._rels:
            neighbors[r.person1_id].add(r.person2_id)
            neighbors[r.person2_id].add(r.person1_id)

        visited = {id1}
        queue: deque[list[str]] = deque([[id1]])
        while queue:
            path = queue.popleft()
            cur  = path[-1]
            if cur == id2:
                return path
            for nxt in neighbors.get(cur, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(path + [nxt])
        return None

    # ── Поиск персон ────────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        gender: str = "",
        birth_year_range: Optional[tuple[int, int]] = None,
        location: str = "",
    ) -> list[Person]:
        results = list(self._persons.values())
        q = query.strip().lower()
        if q:
            results = [
                p for p in results
                if q in p.display_name.lower()
                or q in p.bio.lower()
                or q in p.occupation.lower()
                or q in p.birth_place.lower()
            ]
        if gender:
            results = [p for p in results if p.gender == gender.upper()]
        if birth_year_range:
            lo, hi = birth_year_range
            results = [
                p for p in results
                if p.birth_year is None or lo <= p.birth_year <= hi
            ]
        if location:
            loc = location.lower()
            results = [
                p for p in results
                if loc in p.birth_place.lower() or loc in p.death_place.lower()
            ]
        return results

    # ── Статистика ───────────────────────────────────────────────────────────

    def stats(self) -> dict:
        persons = list(self._persons.values())
        alive   = [p for p in persons if not p.death_date]
        males   = [p for p in persons if p.gender == "M"]
        females = [p for p in persons if p.gender == "F"]
        gens    = self.all_generations()
        return {
            "total":     len(persons),
            "alive":     len(alive),
            "males":     len(males),
            "females":   len(females),
            "max_gen":   max(gens.values(), default=0),
            "rel_count": len(self._rels),
        }
