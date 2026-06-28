"""
app.py — Streamlit-приложение для интерактивного просмотра
генеалогического древа рода Дымковых.

Запуск:
    streamlit run app.py
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from db.family_graph import FamilyGraph, Person

_FE_HTML = Path(__file__).parent / "data_created_from_famecho" / "Family-Echo-28-Jun-2026-104542749.html"

# ── Конфигурация ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Древо рода Дымковых",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

PALETTE = [
    "#C0392B", "#E74C3C", "#E67E22",
    "#F39C12", "#27AE60", "#16A085",
    "#2980B9", "#8E44AD", "#D35400",
]

# ── Загрузка данных ───────────────────────────────────────────────────────────

@st.cache_resource
def load_graph() -> FamilyGraph:
    return FamilyGraph()


def graph_to_df(g: FamilyGraph, gens: dict[str, int]) -> pd.DataFrame:
    """Преобразует граф в DataFrame с одним «основным» родителем на персону
    (нужно для sunburst-диаграммы, которая требует дерево, а не граф)."""
    rows = []
    for p in g.all_persons():
        parents = g.get_parents(p.id)
        # Основной родитель: предпочитаем отца (мужского пола)
        fathers = [par for par in parents if par.gender == "M"]
        par = fathers[0].id if fathers else (parents[0].id if parents else "")

        spouses   = g.get_spouses(p.id)
        sp_names  = ", ".join(sp.display_name for sp, _ in spouses)
        sp_dates  = ", ".join(
            rel.marriage_date[:4] if rel.marriage_date else "?"
            for _, rel in spouses
        )

        rows.append({
            "id":         p.id,
            "name":       p.display_name,
            "parent_id":  par,
            "birth_year": p.birth_year,
            "death_year": p.death_year,
            "gender":     p.gender,
            "location":   p.birth_place or p.death_place,
            "notes":      p.bio,
            "nickname":   p.nickname,
            "occupation": p.occupation,
            "spouses":    sp_names,
            "sp_years":   sp_dates,
            "generation": gens.get(p.id, 0),
        })

    df = pd.DataFrame(rows)
    df["birth_year"] = pd.to_numeric(df["birth_year"], errors="coerce")
    df["death_year"] = pd.to_numeric(df["death_year"], errors="coerce")
    return df


# ── Вспомогательные функции ───────────────────────────────────────────────────

def compute_desc_counts_df(df: pd.DataFrame) -> dict[str, int]:
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


def get_ancestors_df(df: pd.DataFrame, node_id: str) -> set[str]:
    id_to_parent = dict(zip(df["id"], df["parent_id"]))
    ancestors: set[str] = set()
    cur = id_to_parent.get(node_id, "")
    while cur:
        ancestors.add(cur)
        cur = id_to_parent.get(cur, "")
    return ancestors


def get_subtree_ids_df(df: pd.DataFrame, root_id: str) -> set[str]:
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


# ── Sunburst ──────────────────────────────────────────────────────────────────

def build_sunburst(df: pd.DataFrame, max_depth: int) -> go.Figure:
    desc_counts = compute_desc_counts_df(df)
    has_children = set(df.loc[df["parent_id"] != "", "parent_id"])

    ids, labels, parents, values, colors, hover = [], [], [], [], [], []

    for _, row in df.iterrows():
        nid  = row["id"]
        gen  = int(row["generation"])
        if gen > max_depth:
            continue

        dc   = desc_counts.get(nid, 0)
        name = row["name"]

        # Метка сегмента
        parts = [name]
        by, dy = row["birth_year"], row["death_year"]
        if pd.notna(by):
            yr = f"{int(by)}–{int(dy)}" if pd.notna(dy) else f"р.{int(by)}"
            parts.append(yr)
        if dc > 0:
            parts.append(f"↓{dc}")
        label = "<br>".join(parts)

        # Hover
        h = [f"<b>{name}</b>"]
        if row.get("nickname"):
            h.append(f"Прозвище: {row['nickname']}")
        if pd.notna(by):
            h.append(f"Рождение: {int(by)}")
        if pd.notna(dy):
            h.append(f"Смерть: {int(dy)}")
        if row.get("location"):
            h.append(f"Место: {row['location']}")
        if row.get("spouses"):
            pairs = row["spouses"].split(", ")
            years = row.get("sp_years", "").split(", ") if row.get("sp_years") else []
            for i, sp in enumerate(pairs):
                yr_part = f" ({years[i]})" if i < len(years) and years[i] != "?" else ""
                h.append(f"Супруг(а): {sp}{yr_part}")
        if row.get("occupation"):
            h.append(f"Профессия: {row['occupation']}")
        if row.get("notes"):
            h.append(f"Примечание: {row['notes']}")
        h.append(f"Потомков: {dc}")

        par = row["parent_id"]
        if par:
            par_gen = df.loc[df["id"] == par, "generation"]
            if par_gen.empty or int(par_gen.values[0]) > max_depth:
                par = ""

        ids.append(nid)
        labels.append(label)
        parents.append(par)
        values.append(1 if nid not in has_children else 0)
        colors.append(PALETTE[min(gen, len(PALETTE) - 1)])
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


# ── Таблица ───────────────────────────────────────────────────────────────────

def build_table(df: pd.DataFrame, g: FamilyGraph) -> pd.DataFrame:
    desc_counts = compute_desc_counts_df(df)
    rows = []
    for _, row in df.iterrows():
        by = row["birth_year"]
        dy = row["death_year"]

        parents = g.get_parents(row["id"])
        par_names = " & ".join(p.display_name for p in parents) or "—"

        spouses  = g.get_spouses(row["id"])
        sp_str   = "; ".join(
            f"{sp.display_name}" + (f" ({rel.marriage_date[:4]})" if rel.marriage_date else "")
            for sp, rel in spouses
        ) or "—"

        children = g.get_children(row["id"])

        rows.append({
            "Имя":         row["name"],
            "Прозвище":    row.get("nickname") or "—",
            "Пол":         "М" if row["gender"] == "M" else "Ж" if row["gender"] == "F" else "—",
            "Поколение":   int(row["generation"]),
            "Рождение":    int(by) if pd.notna(by) else "—",
            "Смерть":      int(dy) if pd.notna(dy) else "—",
            "Место":       row.get("location") or "—",
            "Профессия":   row.get("occupation") or "—",
            "Родители":    par_names,
            "Супруг(а)":   sp_str,
            "Детей":       len(children),
            "Потомков":    desc_counts.get(row["id"], 0),
        })
    return pd.DataFrame(rows)


# ── Главная страница ──────────────────────────────────────────────────────────

def main() -> None:
    g    = load_graph()
    gens = g.all_generations()
    df_all = graph_to_df(g, gens)

    max_gen = int(df_all["generation"].max()) if not df_all.empty else 5

    # ── Боковая панель ────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("🌳 Фильтры")
        st.markdown("---")

        gender_mode = st.radio(
            "Линия",
            ["Только мужская (Дымковы)", "Все (включая женщин)"],
            index=0,
        )
        male_only = gender_mode.startswith("Только")

        st.markdown("---")

        search = st.text_input("🔍 Поиск по имени", placeholder="Михаил, Раиса, ...")

        st.markdown("---")

        max_depth = st.slider(
            "Глубина поколений",
            min_value=1, max_value=max_gen, value=max_gen,
        )

        st.markdown("---")

        candidates = df_all.sort_values("generation")
        branch_options = ["Всё древо (от корня)"] + [
            f"{row['name']}  [пок.{int(row['generation'])}]"
            for _, row in candidates.iterrows()
        ]
        branch_label = st.selectbox("🌿 Ветка / предок", branch_options)

        st.markdown("---")

        years_avail = sorted(int(y) for y in df_all["birth_year"].dropna().unique())
        if len(years_avail) >= 2:
            year_range = st.slider(
                "Год рождения",
                min_value=years_avail[0], max_value=years_avail[-1],
                value=(years_avail[0], years_avail[-1]),
            )
        else:
            year_range = None

        st.markdown("---")

        locs = ["Все"] + sorted(loc for loc in df_all["location"].unique() if loc)
        location_filter = st.selectbox("📍 Место", locs)

    # ── Применяем фильтры ─────────────────────────────────────────────────────
    df = df_all.copy()

    if male_only:
        df = df[df["gender"] == "M"]

    if search.strip():
        mask = df["name"].str.contains(search.strip(), case=False, na=False)
        found_ids = set(df.loc[mask, "id"])
        ancestor_ids: set[str] = set()
        for fid in found_ids:
            ancestor_ids |= get_ancestors_df(df_all, fid)
        df = df[mask | df["id"].isin(ancestor_ids)]

    if branch_label != "Всё древо (от корня)":
        branch_name = branch_label.split("  [пок.")[0].strip()
        match = df_all[df_all["name"] == branch_name]
        if not match.empty:
            root_id = match.iloc[0]["id"]
            subtree = get_subtree_ids_df(df_all, root_id)
            df = df[df["id"].isin(subtree)]

    if year_range is not None:
        df = df[df["birth_year"].isna() | df["birth_year"].between(*year_range)]

    if location_filter != "Все":
        df = df[(df["location"] == "") | (df["location"] == location_filter)]

    # ── Заголовок ─────────────────────────────────────────────────────────────
    st.title("🌳 Генеалогическое древо рода Дымковых")
    st.caption("Корень: Тимофеев Дымков (1800) → Терентий Дымков → …")

    stats = g.stats()
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Персон в фильтре", len(df))
    col2.metric("Поколений", int(df["generation"].max()) if not df.empty else 0)
    col3.metric("Мужчин",   int((df["gender"] == "M").sum()))
    col4.metric("Женщин",   int((df["gender"] == "F").sum()))
    col5.metric("Всего в БД", stats["total"])

    st.markdown("---")

    tab_sunburst, tab_table, tab_stats, tab_fe = st.tabs(
        ["☀️ Sunburst", "📋 Таблица", "📊 Статистика", "🌐 FamilyEcho"]
    )

    with tab_sunburst:
        if df.empty:
            st.warning("Нет данных для отображения. Измените фильтры.")
        else:
            fig = build_sunburst(df, max_depth)
            st.plotly_chart(fig, use_container_width=True)
            html_bytes = fig.to_html(include_plotlyjs=True).encode("utf-8")
            st.download_button(
                "⬇️ Скачать диаграмму (HTML)",
                data=html_bytes,
                file_name="family_tree_filtered.html",
                mime="text/html",
            )

    with tab_table:
        tbl = build_table(df, g)
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
        gen_df = df[["generation", "gender"]].copy()
        gen_df.columns = ["Поколение", "Пол"]
        if not gen_df.empty:
            gc = (
                gen_df.groupby(["Поколение", "Пол"])
                .size().reset_index(name="Кол-во")
            )
            st.bar_chart(
                gc.pivot(index="Поколение", columns="Пол", values="Кол-во").fillna(0)
            )

        st.subheader("Топ по количеству потомков")
        desc_counts = compute_desc_counts_df(df)
        desc_rows = [
            {"Имя": row["name"], "Поколение": int(row["generation"]),
             "Потомков": desc_counts.get(row["id"], 0)}
            for _, row in df.iterrows()
            if desc_counts.get(row["id"], 0) > 0
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

        st.subheader("Брачные союзы с датами")
        marriage_rows = []
        for p in g.all_persons():
            for sp, rel in g.get_spouses(p.id):
                if rel.marriage_date and p.id < sp.id:
                    marriage_rows.append({
                        "Супруг 1":   p.display_name,
                        "Супруг 2":   sp.display_name,
                        "Дата брака": rel.marriage_date,
                        "Место":      rel.marriage_place or "—",
                    })
        if marriage_rows:
            st.dataframe(
                pd.DataFrame(marriage_rows).sort_values("Дата брака"),
                use_container_width=True,
                hide_index=True,
            )

    with tab_fe:
        if _FE_HTML.exists():
            html_src = _FE_HTML.read_text(encoding="utf-8")
            # FamilyEcho использует height:100% на всей DOM-цепочке до #treebg,
            # но <body> не имеет явной высоты — цепочка рвётся и дерево невидимо.
            # Решение: вставляем CSS с height:100vh (не зависит от родителей)
            # и вызываем EPR() в несколько заходов после загрузки страницы.
            css_fix = (
                "<style>"
                "html,body,#main,#treediv,#treemargin,#treebg"
                "{height:100vh!important}"
                "</style>"
            )
            # В srcdoc-iframe браузер не добавляет "px" к числовым значениям
            # style.left/top автоматически, поэтому TSD() — функция прокрутки
            # дерева — молча игнорируется и дерево остаётся вне зоны видимости.
            # Патчим TSD чтобы явно добавлять "px", затем перерисовываем.
            js_fix = (
                "<script>"
                "(function(){"
                "function patchAndDraw(){"
                "if(typeof TSD==='function'){"
                "TSD=function(x,y){"
                "var e=document.getElementById('treebg');"
                "if(e){e.style.left=(-x)+'px';e.style.top=(-y)+'px';}"
                "};"
                "}"
                "if(typeof EPR==='function'){EPR();}"
                "}"
                "[50,300,700,1500].forEach(function(t){setTimeout(patchAndDraw,t);});"
                "window.addEventListener('resize',patchAndDraw);"
                "})();"
                "</script>"
            )
            html_src = html_src.replace("</HEAD>", css_fix + "</HEAD>", 1)
            html_src = html_src.replace("</BODY>", js_fix + "</BODY>", 1)
            components.html(html_src, height=1000, scrolling=True)
        else:
            st.error(f"Файл не найден: {_FE_HTML}")


if __name__ == "__main__":
    main()
