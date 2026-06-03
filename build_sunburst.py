"""
build_sunburst.py — построение интерактивной Sunburst-диаграммы
                    генеалогического древа по мужской линии.

Читает данные из output/family_data.csv (или файл, указанный аргументом),
фильтрует по мужской линии, вычисляет количество потомков,
строит интерактивный HTML-файл через Plotly.

Использование:
    python build_sunburst.py                        # стандартный CSV
    python build_sunburst.py output/my_data.csv    # свой файл
    python build_sunburst.py --all                 # включить женщин тоже
"""

import sys
from pathlib import Path

try:
    import pandas as pd
    import plotly.graph_objects as go
except ImportError as e:
    print(f"[ОШИБКА] Не установлена библиотека: {e}")
    print("Запустите: pip install pandas plotly")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
DEFAULT_CSV = BASE_DIR / "output" / "family_data.csv"
OUTPUT_HTML = BASE_DIR / "output" / "final_sunburst.html"


# ── Загрузка и валидация данных ───────────────────────────────────────────────

def load_data(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        print(f"[ОШИБКА] Файл не найден: {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path, dtype=str).fillna("")
    required = {"id", "name", "parent_id", "gender"}
    missing = required - set(df.columns)
    if missing:
        print(f"[ОШИБКА] В CSV отсутствуют колонки: {missing}")
        sys.exit(1)

    df["id"] = df["id"].str.strip()
    df["parent_id"] = df["parent_id"].str.strip()
    df["gender"] = df["gender"].str.strip().str.upper()

    print(f"  Загружено записей: {len(df)}")
    return df


def filter_male_line(df: pd.DataFrame) -> pd.DataFrame:
    """
    Оставляет только персон мужского пола (gender=M),
    плюс их прямых предков-мужчин (чтобы не потерять промежуточные уровни).
    Строится рекурсивно по цепочке parent_id.
    """
    males = set(df.loc[df["gender"] == "M", "id"])

    # Собираем все IDs, которые нужно оставить (мужчины + их предки-мужчины)
    keep: set[str] = set()
    id_to_row = df.set_index("id").to_dict("index")

    def add_with_ancestors(node_id: str) -> None:
        if node_id in keep or node_id not in id_to_row:
            return
        keep.add(node_id)
        parent = id_to_row[node_id]["parent_id"]
        if parent and parent in id_to_row and id_to_row[parent]["gender"] == "M":
            add_with_ancestors(parent)

    for mid in males:
        add_with_ancestors(mid)

    filtered = df[df["id"].isin(keep) & (df["gender"] == "M")].copy()
    print(f"  После фильтра (только мужская линия): {len(filtered)} персон")
    return filtered


def count_descendants(df: pd.DataFrame) -> dict[str, int]:
    """Считает количество прямых потомков по мужской линии для каждого узла."""
    children: dict[str, list[str]] = {row["id"]: [] for _, row in df.iterrows()}
    for _, row in df.iterrows():
        pid = row["parent_id"]
        if pid and pid in children:
            children[pid].append(row["id"])

    cache: dict[str, int] = {}

    def desc_count(node_id: str) -> int:
        if node_id in cache:
            return cache[node_id]
        total = len(children[node_id])
        for child_id in children[node_id]:
            total += desc_count(child_id)
        cache[node_id] = total
        return total

    return {nid: desc_count(nid) for nid in children}


# ── Построение Sunburst ───────────────────────────────────────────────────────

def build_label(row: pd.Series, desc_count: int) -> str:
    """Формирует текст для сегмента: имя + годы + количество потомков."""
    name = row["name"]
    parts: list[str] = [name]

    birth = str(row.get("birth_year", "")).strip()
    death = str(row.get("death_year", "")).strip()
    if birth or death:
        years = f"{birth}–{death}" if death else (f"р. {birth}" if birth else "")
        if years:
            parts.append(years)

    if desc_count > 0:
        parts.append(f"↓{desc_count}")

    return "<br>".join(parts)


def build_hover(row: pd.Series, desc_count: int) -> str:
    """Полный текст всплывающей подсказки."""
    lines: list[str] = [f"<b>{row['name']}</b>"]

    birth = str(row.get("birth_year", "")).strip()
    death = str(row.get("death_year", "")).strip()
    if birth:
        lines.append(f"Рождение: {birth}")
    if death:
        lines.append(f"Смерть: {death}")

    location = str(row.get("location", "")).strip()
    if location:
        lines.append(f"Место: {location}")

    source = str(row.get("source_part", "")).strip()
    if source:
        lines.append(f"Источник: {source}")

    notes = str(row.get("notes", "")).strip()
    if notes:
        lines.append(f"Примечание: {notes}")

    lines.append(f"<br>Потомков (муж. линия): {desc_count}")
    return "<br>".join(lines)


def assign_colors(df: pd.DataFrame) -> list[str]:
    """Назначает цвета по поколениям (глубине в дереве)."""
    id_to_parent: dict[str, str] = dict(zip(df["id"], df["parent_id"]))
    palette = [
        "#8B0000",   # gen 0 — тёмно-красный (корень)
        "#C0392B",   # gen 1
        "#E74C3C",   # gen 2
        "#E67E22",   # gen 3
        "#F39C12",   # gen 4
        "#27AE60",   # gen 5
        "#16A085",   # gen 6
        "#2980B9",   # gen 7
        "#8E44AD",   # gen 8+
    ]

    depth_cache: dict[str, int] = {}

    def get_depth(node_id: str) -> int:
        if node_id in depth_cache:
            return depth_cache[node_id]
        parent = id_to_parent.get(node_id, "")
        depth = 0 if not parent else get_depth(parent) + 1
        depth_cache[node_id] = depth
        return depth

    colors = []
    for _, row in df.iterrows():
        d = get_depth(row["id"])
        colors.append(palette[min(d, len(palette) - 1)])
    return colors


def build_sunburst(df: pd.DataFrame, desc_counts: dict[str, int]) -> go.Figure:
    ids: list[str] = []
    labels: list[str] = []
    parents: list[str] = []
    hover: list[str] = []
    values: list[int] = []

    # Определяем листья (нет детей в мужской линии)
    has_children = set(df["parent_id"].str.strip())

    for _, row in df.iterrows():
        node_id = row["id"]
        dc = desc_counts.get(node_id, 0)

        ids.append(node_id)
        labels.append(build_label(row, dc))
        parents.append(row["parent_id"])
        hover.append(build_hover(row, dc))
        # branchvalues="remainder": значение = вклад самого узла.
        # Листья = 1, внутренние = 0 (их размер = сумма потомков-листьев).
        values.append(1 if node_id not in has_children else 0)

    colors = assign_colors(df)

    fig = go.Figure(go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        hovertext=hover,
        hoverinfo="text",
        marker=dict(colors=colors, line=dict(width=1, color="white")),
        textfont=dict(size=10, family="Arial"),
        insidetextorientation="radial",
        maxdepth=6,
        branchvalues="remainder",
    ))

    fig.update_layout(
        title=dict(
            text="Генеалогическое древо рода Дымковых (мужская линия)<br>"
                 "<sup>Корень: Тимофеев (1800) → Дымков Терентий → ...</sup>",
            x=0.5,
            font=dict(size=18),
        ),
        margin=dict(t=80, l=10, r=10, b=10),
        width=1200,
        height=900,
        paper_bgcolor="#1a1a2e",
        font=dict(color="white"),
    )

    return fig


# ── Точка входа ───────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  Построение Sunburst-диаграммы генеалогического древа")
    print("=" * 60)

    male_only = True
    csv_path = DEFAULT_CSV

    for arg in sys.argv[1:]:
        if arg == "--all":
            male_only = False
        elif not arg.startswith("--"):
            csv_path = Path(arg)

    print(f"\nИсточник данных: {csv_path}")
    print(f"Режим: {'только мужская линия' if male_only else 'все персоны'}\n")

    df = load_data(csv_path)

    if male_only:
        df = filter_male_line(df)

    if df.empty:
        print("[ОШИБКА] После фильтрации данных нет. Проверьте CSV.")
        sys.exit(1)

    print("\n  Подсчёт потомков ...")
    desc_counts = count_descendants(df)

    root_id = df[df["parent_id"] == ""]["id"].values
    if len(root_id) == 0:
        print("[ОШИБКА] Не найден корневой узел (без parent_id). Проверьте CSV.")
        sys.exit(1)

    total_desc = desc_counts.get(root_id[0], 0)
    print(f"  Корень: {df[df['id'] == root_id[0]]['name'].values[0]}")
    print(f"  Всего потомков по мужской линии: {total_desc}")

    print("\n  Строю диаграмму ...")
    fig = build_sunburst(df, desc_counts)

    OUTPUT_HTML.parent.mkdir(exist_ok=True)
    # include_plotlyjs=True встраивает JS в файл (~3 MB) — работает без интернета
    fig.write_html(str(OUTPUT_HTML), include_plotlyjs=True)

    print(f"\n[OK] Диаграмма сохранена: {OUTPUT_HTML}")
    print(f"     Откройте в браузере: file://{OUTPUT_HTML.resolve()}")

    # Статистика по поколениям
    print("\n  Статистика:")
    id_to_parent = dict(zip(df["id"], df["parent_id"]))
    depth_map: dict[str, int] = {}

    def get_depth(nid: str) -> int:
        if nid in depth_map:
            return depth_map[nid]
        p = id_to_parent.get(nid, "")
        d = 0 if not p else get_depth(p) + 1
        depth_map[nid] = d
        return d

    for _, row in df.iterrows():
        get_depth(row["id"])

    from collections import Counter
    gen_counts = Counter(depth_map.values())
    for gen in sorted(gen_counts):
        label = "Корень" if gen == 0 else f"Поколение {gen}"
        print(f"    {label}: {gen_counts[gen]} чел.")


if __name__ == "__main__":
    main()
