"""
app.py — Streamlit-приложение для интерактивного просмотра
генеалогического древа рода Дымковых.

Запуск:
    streamlit run app.py
"""

from __future__ import annotations

from pathlib import Path
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── Конфигурация ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Древо рода Дымковых",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSV_PATH = Path(__file__).parent / "output" / "family_data.csv"

PALETTE = [
    "#C0392B", "#E74C3C", "#E67E22",
    "#F39C12", "#27AE60", "#16A085",
    "#2980B9", "#8E44AD", "#D35400",
]

# ── Загрузка данных ───────────────────────────────────────────────────────────

@st.cache_data
def load_data() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    df["id"]         = df["id"].str.strip()
    df["parent_id"]  = df["parent_id"].str.strip()
    df["gender"]     = df["gender"].str.strip().str.upper()
    df["birth_year"] = pd.to_numeric(df["birth_year"], errors="coerce")
    df["death_year"] = pd.to_numeric(df["death_year"], errors="coerce")
    return df


def compute_depths(df: pd.DataFrame) -> dict[str, int]:
    id_to_parent = dict(zip(df["id"], df["parent_id"]))
    cache: dict[str, int] = {}

    def depth(nid: str) -> int:
        if nid in cache:
            return cache[nid]
        p = id_to_parent.get(nid, "")
        d = 0 if not p else depth(p) + 1
        cache[nid] = d
        return d

    return {nid: depth(nid) for nid in df["id"]}


def compute_desc_counts(df: pd.DataFrame) -> dict[str, int]:
    children: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        if row["parent_id"]:
            children[row["parent_id"]].append(row["id"])

    cache: dict[str, int] = {}

    def count(nid: str) -> int:
        if nid in cache:
            return cache[nid]
        total = sum(1 + count(c) for c in children[nid])
        cache[nid] = total
        return total

    return {nid: count(nid) for nid in df["id"]}


def get_subtree_ids(df: pd.DataFrame, root_id: str) -> set[str]:
    """Возвращает root_id и всех его потомков."""
    children: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        if row["parent_id"]:
            children[row["parent_id"]].append(row["id"])

    result: set[str] = set()

    def collect(nid: str) -> None:
        result.add(nid)
        for c in children[nid]:
            collect(c)

    collect(root_id)
    return result


def get_ancestors(df: pd.DataFrame, node_id: str) -> set[str]:
    """Возвращает всех предков node_id (для отображения пути к корню)."""
    id_to_parent = dict(zip(df["id"], df["parent_id"]))
    ancestors: set[str] = set()
    current = id_to_parent.get(node_id, "")
    while current:
        ancestors.add(current)
        current = id_to_parent.get(current, "")
    return ancestors


# ── Построение диаграммы ──────────────────────────────────────────────────────

def build_treemap(df: pd.DataFrame, max_depth: int) -> go.Figure:
    depths    = compute_depths(df)
    desc_counts = compute_desc_counts(df)
    has_children = set(df.loc[df["parent_id"] != "", "parent_id"])

    # "has_children" только среди отображаемых узлов (глубина <= max_depth)
    shown_ids = {row["id"] for _, row in df.iterrows() if depths.get(row["id"], 0) <= max_depth}
    has_children = {
        row["parent_id"] for _, row in df.iterrows()
        if row["id"] in shown_ids and row["parent_id"] in shown_ids
    }

    ids, labels, parents, values, colors, hover = [], [], [], [], [], []

    for _, row in df.iterrows():
        nid = row["id"]
        d = depths.get(nid, 0)
        if d > max_depth:
            continue

        dc = desc_counts.get(nid, 0)
        name = row["name"]

        # Метка в прямоугольнике
        label_parts = [name]
        by = row["birth_year"]
        dy = row["death_year"]
        if pd.notna(by):
            yr = f"{int(by)}–{int(dy)}" if pd.notna(dy) else f"р.{int(by)}"
            label_parts.append(yr)
        if dc > 0:
            label_parts.append(f"↓{dc}")

        # Hover
        h = [f"<b>{name}</b>", f"Поколение: {d}"]
        if pd.notna(by):
            h.append(f"Рождение: {int(by)}")
        if pd.notna(dy):
            h.append(f"Смерть: {int(dy)}")
        loc = row.get("location", "")
        if loc:
            h.append(f"Место: {loc}")
        src = row.get("source_part", "")
        if src:
            h.append(f"Источник: {src}")
        notes = row.get("notes", "")
        if notes:
            h.append(f"Примечание: {notes}")
        h.append(f"Потомков: {dc}")

        par = row["parent_id"]
        if par and depths.get(par, 0) > max_depth:
            par = ""

        ids.append(nid)
        labels.append("<br>".join(label_parts))
        parents.append(par)
        # Листья = 1, ветви = 0 (размер = сумма потомков-листьев)
        values.append(1 if nid not in has_children else 0)
        colors.append(PALETTE[min(d, len(PALETTE) - 1)])
        hover.append("<br>".join(h))

    if not ids:
        return go.Figure()

    fig = go.Figure(go.Treemap(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        hovertext=hover,
        hoverinfo="text",
        marker=dict(
            colors=colors,
            line=dict(width=2, color="white"),
            pad=dict(t=20, l=4, r=4, b=4),
        ),
        textfont=dict(size=12, family="Arial"),
        textposition="middle center",
        branchvalues="remainder",
    ))
    fig.update_layout(
        margin=dict(t=10, l=0, r=0, b=0),
        paper_bgcolor="#0f0f1a",
        font=dict(color="white"),
        height=720,
    )
    return fig


def build_sunburst(df: pd.DataFrame, max_depth: int) -> go.Figure:
    depths    = compute_depths(df)
    desc_counts = compute_desc_counts(df)
    has_children = set(df.loc[df["parent_id"] != "", "parent_id"])

    ids, labels, parents, values, colors, hover = [], [], [], [], [], []

    for _, row in df.iterrows():
        nid = row["id"]
        if depths.get(nid, 0) > max_depth:
            continue

        dc = desc_counts.get(nid, 0)

        # Метка сегмента
        name = row["name"]
        parts = [name]
        by = row["birth_year"]
        dy = row["death_year"]
        if pd.notna(by):
            yr = f"{int(by)}–{int(dy)}" if pd.notna(dy) else f"р.{int(by)}"
            parts.append(yr)
        if dc > 0:
            parts.append(f"↓{dc}")
        label = "<br>".join(parts)

        # Hover
        h = [f"<b>{name}</b>"]
        if pd.notna(by):
            h.append(f"Рождение: {int(by)}")
        if pd.notna(dy):
            h.append(f"Смерть: {int(dy)}")
        loc = row.get("location", "")
        if loc:
            h.append(f"Место: {loc}")
        notes = row.get("notes", "")
        if notes:
            h.append(f"Примечание: {notes}")
        h.append(f"Потомков: {dc}")

        # Родитель: если родитель обрезан глубиной — показываем как корень
        par = row["parent_id"]
        if par and depths.get(par, 0) > max_depth:
            par = ""

        ids.append(nid)
        labels.append(label)
        parents.append(par)
        values.append(1 if nid not in has_children else 0)
        colors.append(PALETTE[min(depths.get(nid, 0), len(PALETTE) - 1)])
        hover.append("<br>".join(h))

    if not ids:
        return go.Figure()

    fig = go.Figure(go.Sunburst(
        ids=ids,
        labels=labels,
        parents=parents,
        values=values,
        hovertext=hover,
        hoverinfo="text",
        marker=dict(colors=colors, line=dict(width=1, color="white")),
        textfont=dict(size=11, family="Arial"),
        insidetextorientation="radial",
        branchvalues="remainder",
    ))
    fig.update_layout(
        margin=dict(t=20, l=0, r=0, b=0),
        paper_bgcolor="#0f0f1a",
        font=dict(color="white"),
        height=680,
    )
    return fig


def build_table(df: pd.DataFrame) -> pd.DataFrame:
    depths = compute_depths(df)
    desc_counts = compute_desc_counts(df)
    id_to_name = dict(zip(df["id"], df["name"]))

    rows = []
    for _, row in df.iterrows():
        by = row["birth_year"]
        dy = row["death_year"]
        rows.append({
            "Имя": row["name"],
            "Поколение": depths.get(row["id"], 0),
            "Рождение": int(by) if pd.notna(by) else "—",
            "Смерть": int(dy) if pd.notna(dy) else "—",
            "Пол": "М" if row["gender"] == "M" else "Ж",
            "Место": row.get("location", "") or "—",
            "Родитель": id_to_name.get(row["parent_id"], "—") if row["parent_id"] else "—",
            "Потомков": desc_counts.get(row["id"], 0),
            "Источник": row.get("source_part", "") or "—",
        })
    return pd.DataFrame(rows)


# ── Главная страница ──────────────────────────────────────────────────────────

def main() -> None:
    df_all = load_data()
    depths_all = compute_depths(df_all)
    max_gen = max(depths_all.values()) if depths_all else 5

    # ── Боковая панель фильтров ───────────────────────────────────────────────
    with st.sidebar:
        st.title("🌳 Фильтры")
        st.markdown("---")

        # 1. Мужская / вся линия
        gender_mode = st.radio(
            "Линия",
            ["Только мужская (Дымковы)", "Все (включая женщин)"],
            index=1,
        )
        male_only = gender_mode.startswith("Только")

        st.markdown("---")

        # 2. Поиск по имени
        search = st.text_input("🔍 Поиск по имени", placeholder="Никита, Пахом, ...")

        st.markdown("---")

        # 3. Глубина поколений
        max_depth = st.slider(
            "Глубина поколений",
            min_value=1,
            max_value=max_gen,
            value=max_gen,
            help="0 = только корень, 5 = все поколения",
        )

        st.markdown("---")

        # 4. Выбор ветки (начальный предок)
        males_df = df_all[df_all["gender"] == "M"] if male_only else df_all
        males_sorted = males_df.copy()
        males_sorted["_depth"] = males_sorted["id"].map(depths_all)
        males_sorted = males_sorted.sort_values("_depth")
        branch_options = ["Всё древо (от корня)"] + [
            f"{row['name']}  [поколение {int(row['_depth'])}]"
            for _, row in males_sorted.iterrows()
            if row["id"] != "root_T"
        ]
        branch_label = st.selectbox("🌿 Ветка / предок", branch_options)

        st.markdown("---")

        # 5. Фильтр по году рождения
        years_available = sorted(
            int(y) for y in df_all["birth_year"].dropna().unique()
        )
        if len(years_available) >= 2:
            year_range = st.slider(
                "Год рождения",
                min_value=years_available[0],
                max_value=years_available[-1],
                value=(years_available[0], years_available[-1]),
            )
        else:
            year_range = None

        st.markdown("---")

        # 6. Место
        locations = ["Все"] + sorted(
            loc for loc in df_all["location"].unique() if loc
        )
        location_filter = st.selectbox("📍 Место", locations)

    # ── Применяем фильтры ─────────────────────────────────────────────────────
    df = df_all.copy()

    # Пол
    if male_only:
        df = df[df["gender"] == "M"]

    # Поиск по имени
    if search.strip():
        mask = df["name"].str.contains(search.strip(), case=False, na=False)
        # Добавляем предков найденных, чтобы дерево не обрывалось
        found_ids = set(df.loc[mask, "id"])
        ancestor_ids: set[str] = set()
        for fid in found_ids:
            ancestor_ids |= get_ancestors(df_all, fid)
        df = df[mask | df["id"].isin(ancestor_ids)]

    # Ветка
    if branch_label != "Всё древо (от корня)":
        branch_name = branch_label.split("  [поколение")[0].strip()
        match = df_all[df_all["name"] == branch_name]
        if not match.empty:
            root_id = match.iloc[0]["id"]
            subtree = get_subtree_ids(df_all, root_id)
            df = df[df["id"].isin(subtree)]

    # Год рождения (только по тем, у кого год указан)
    if year_range is not None:
        mask_year = (
            df["birth_year"].isna()  # без года — не фильтруем
            | df["birth_year"].between(year_range[0], year_range[1])
        )
        df = df[mask_year]

    # Место
    if location_filter != "Все":
        mask_loc = (df["location"] == "") | (df["location"] == location_filter)
        df = df[mask_loc]

    # ── Заголовок и метрики ───────────────────────────────────────────────────
    st.title("🌳 Генеалогическое древо рода Дымковых")
    st.caption("Корень: Тимофеев (1800) → Дымков Терентий → …")

    col1, col2, col3, col4 = st.columns(4)
    depths_cur  = compute_depths(df)
    desc_cur    = compute_desc_counts(df)
    root_row    = df[df["parent_id"] == ""]
    total_desc  = desc_cur.get(root_row["id"].values[0], 0) if not root_row.empty else len(df) - 1

    col1.metric("Персон в фильтре", len(df))
    col2.metric("Поколений", max(depths_cur.values()) if depths_cur else 0)
    col3.metric("Мужчин", int((df["gender"] == "M").sum()))
    col4.metric("Женщин", int((df["gender"] == "F").sum()))

    st.markdown("---")

    # ── Вкладки ───────────────────────────────────────────────────────────────
    tab_sunburst, tab_treemap, tab_table, tab_stats = st.tabs(
        ["☀️ Sunburst диаграмма", "🗺️ Treemap (проверка)", "📋 Таблица", "📊 Статистика"]
    )

    with tab_sunburst:
        if df.empty:
            st.warning("Нет данных для отображения. Измените фильтры.")
        else:
            fig = build_sunburst(df, max_depth)
            st.plotly_chart(fig, use_container_width=True)

            # Кнопка скачать HTML
            html_bytes = fig.to_html(include_plotlyjs=True).encode("utf-8")
            st.download_button(
                label="⬇️ Скачать диаграмму (HTML)",
                data=html_bytes,
                file_name="family_tree_filtered.html",
                mime="text/html",
            )

    with tab_treemap:
        st.markdown("#### Пошаговая проверка структуры дерева")
        st.caption(
            "Управляй глубиной ниже — проверяй поколение за поколением. "
            "Отображаются только мужчины, если выбран режим «Только мужская линия»."
        )

        tm_col1, tm_col2 = st.columns([2, 1])
        with tm_col1:
            tm_depth = st.slider(
                "Глубина (поколения от корня)",
                min_value=0,
                max_value=max_gen,
                value=1,
                key="tm_depth",
                help="0 = только корень, 1 = корень + его дети, 2 = +внуки, …",
            )
        with tm_col2:
            st.metric("Показано поколений", f"0 → {tm_depth}")

        # Применяем те же фильтры, что и в sidebar, но с собственной глубиной
        df_tm = df.copy()
        tm_depths = compute_depths(df_tm)
        df_tm_filtered = df_tm[df_tm["id"].map(lambda i: tm_depths.get(i, 0)) <= tm_depth]

        if df_tm_filtered.empty:
            st.warning("Нет данных. Измените фильтры или глубину.")
        else:
            fig_tm = build_treemap(df_tm_filtered, tm_depth)
            st.plotly_chart(fig_tm, use_container_width=True)

        # Таблица текущего поколения для проверки
        st.markdown(f"---\n**Персоны на уровне {tm_depth}** (только выбранная глубина):")
        id_to_name = dict(zip(df_all["id"], df_all["name"]))
        cur_gen_rows = []
        for _, row in df_all.iterrows():
            if tm_depths.get(row["id"], -1) == tm_depth:
                if male_only and row["gender"] != "M":
                    continue
                cur_gen_rows.append({
                    "Имя": row["name"],
                    "Пол": "М" if row["gender"] == "M" else "Ж",
                    "Родитель": id_to_name.get(row["parent_id"], "—"),
                    "Рождение": int(row["birth_year"]) if pd.notna(row["birth_year"]) else "—",
                    "Место": row.get("location", "") or "—",
                    "Источник": row.get("source_part", "") or "—",
                    "Примечание": row.get("notes", "") or "",
                })
        if cur_gen_rows:
            st.dataframe(
                pd.DataFrame(cur_gen_rows),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"Всего на уровне {tm_depth}: {len(cur_gen_rows)} чел.")
        else:
            st.info("На этом уровне нет персон в текущем фильтре.")

    with tab_table:
        tbl = build_table(df)
        search_tbl = st.text_input("Поиск в таблице", key="tbl_search",
                                   placeholder="любое поле...")
        if search_tbl:
            mask = tbl.apply(
                lambda col: col.astype(str).str.contains(search_tbl, case=False)
            ).any(axis=1)
            tbl = tbl[mask]

        st.dataframe(
            tbl.sort_values(["Поколение", "Имя"]),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Показано строк: {len(tbl)}")

    with tab_stats:
        st.subheader("Распределение по поколениям")
        depths_df = pd.DataFrame([
            {"Поколение": d, "Имя": row["name"], "Пол": row["gender"]}
            for _, row in df.iterrows()
            for d in [depths_cur.get(row["id"], 0)]
        ])
        if not depths_df.empty:
            gen_counts = (
                depths_df.groupby(["Поколение", "Пол"])
                .size()
                .reset_index(name="Кол-во")
            )
            st.bar_chart(
                gen_counts.pivot(index="Поколение", columns="Пол", values="Кол-во").fillna(0)
            )

            st.subheader("Топ по количеству потомков")
            desc_rows = [
                {"Имя": row["name"],
                 "Поколение": depths_cur.get(row["id"], 0),
                 "Потомков": desc_cur.get(row["id"], 0)}
                for _, row in df.iterrows()
                if desc_cur.get(row["id"], 0) > 0
            ]
            if desc_rows:
                top_df = (
                    pd.DataFrame(desc_rows)
                    .sort_values("Потомков", ascending=False)
                    .head(15)
                )
                st.dataframe(top_df, use_container_width=True, hide_index=True)

        st.subheader("Хронология рождений")
        birth_df = df[df["birth_year"].notna()][["name", "birth_year", "gender"]].copy()
        birth_df["birth_year"] = birth_df["birth_year"].astype(int)
        if not birth_df.empty:
            st.dataframe(
                birth_df.sort_values("birth_year")
                .rename(columns={"name": "Имя", "birth_year": "Год рождения", "gender": "Пол"}),
                use_container_width=True,
                hide_index=True,
            )


if __name__ == "__main__":
    main()
