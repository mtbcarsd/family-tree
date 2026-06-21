"""
app_v2.py — Генеалогическое дерево v2
Формат CSV: id, name, birth_year, gender, father_id, mother_id, spouse_id
Запуск:  streamlit run app_v2.py
"""

from __future__ import annotations

import io
from collections import defaultdict, deque

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Генеалогическое дерево",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

BG = "#0f0f1a"
C_M = "#4a9eda"        # мужчины
C_F = "#e87a9a"        # женщины
C_ROOT = "#ffd700"     # корень
C_SPOUSE = "#ff9f43"   # линия супругов

# ──────────────────────────────────────────────────────────────────────────────
# DEMO DATA
# ──────────────────────────────────────────────────────────────────────────────

DEMO_CSV = """\
id,name,birth_year,gender,father_id,mother_id,spouse_id
t01,Тимофеев Иван,1800,M,,,t02
t02,Тимофеева Прасковья,1803,F,,,t01
t03,Тимофеев Пётр,1825,M,t01,t02,t04
t04,Мария (жена Петра),1828,F,,,t03
t05,Тимофеев Николай,1828,M,t01,t02,t06
t06,Ольга (жена Николая),1831,F,,,t05
t07,Тимофеев Сергей,1832,M,t01,t02,t08
t08,Елена (жена Сергея),1835,F,,,t07
t09,Тимофеев Алексей,1850,M,t03,t04,t10
t10,Вера (жена Алексея),1853,F,,,t09
t11,Тимофеев Василий,1852,M,t03,t04,t12
t12,Екатерина (жена Василия),1856,F,,,t11
t13,Тимофеева Наталья,1855,F,t03,t04,
t14,Тимофеев Михаил,1854,M,t05,t06,t15
t15,Зоя (жена Михаила),1857,F,,,t14
t16,Тимофеева Анна,1858,F,t05,t06,
t17,Тимофеев Дмитрий,1857,M,t07,t08,t18
t18,Любовь (жена Дмитрия),1860,F,,,t17
t19,Тимофеев Сергей-мл.,1860,M,t07,t08,
t20,Тимофеев Иван-мл.,1875,M,t09,t10,t21
t21,Лида (жена Ивана-мл.),1878,F,,,t20
t22,Тимофеева Надежда,1877,F,t09,t10,
t23,Тимофеев Борис,1878,M,t11,t12,t24
t24,Нина (жена Бориса),1880,F,,,t23
t25,Тимофеев Степан,1880,M,t14,t15,
t26,Тимофеева Зинаида,1882,F,t14,t15,
t27,Тимофеев Андрей,1882,M,t17,t18,t28
t28,Тамара (жена Андрея),1885,F,,,t27
t29,Тимофеев Максим,1905,M,t23,t24,
t30,Тимофеева Соня,1907,F,t23,t24,
t31,Тимофеев Пётр-мл.,1908,M,t27,t28,
t32,Тимофеева Вера-мл.,1910,F,t27,t28,
t33,Тимофеев Кирилл,1930,M,t29,,
"""

# ──────────────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_df(raw: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(raw), dtype=str).fillna("")
    df["birth_year"] = pd.to_numeric(df["birth_year"], errors="coerce")
    for col in ("father_id", "mother_id", "spouse_id"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["id"] = df["id"].str.strip()
    df["name"] = df["name"].str.strip()
    return df


def index_family(df: pd.DataFrame):
    """Return lookup dicts: father_of, mother_of, spouse_of, children_of."""
    valid = set(df["id"])
    father_of  = {r["id"]: r["father_id"] for _, r in df.iterrows()}
    mother_of  = {r["id"]: r["mother_id"] for _, r in df.iterrows()}
    spouse_of  = {r["id"]: r["spouse_id"] for _, r in df.iterrows()}

    children_of: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        for pid in (row["father_id"], row["mother_id"]):
            if pid and pid in valid:
                if row["id"] not in children_of[pid]:
                    children_of[pid].append(row["id"])
    return father_of, mother_of, spouse_of, children_of


@st.cache_data
def compute_desc_count(raw: str) -> dict[str, int]:
    df = load_df(raw)
    _, _, _, children_of = index_family(df)
    cache: dict[str, int] = {}

    def count(nid: str) -> int:
        if nid in cache:
            return cache[nid]
        total = sum(1 + count(c) for c in children_of.get(nid, []))
        cache[nid] = total
        return total

    for pid in df["id"]:
        count(pid)
    return cache


# ──────────────────────────────────────────────────────────────────────────────
# SUBTREE TRAVERSAL
# ──────────────────────────────────────────────────────────────────────────────

def get_subtree(
    root_id: str,
    children_of: dict,
    spouse_of: dict,
    valid: set,
    max_depth: int,
) -> dict[str, int]:
    """BFS от root_id. Возвращает {id: generation}. Супруги идут на том же уровне."""
    gen: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque()

    def enqueue(nid: str, depth: int) -> None:
        if nid in gen or nid not in valid:
            return
        gen[nid] = depth
        queue.append((nid, depth))
        sp = spouse_of.get(nid, "")
        if sp and sp not in gen and sp in valid:
            gen[sp] = depth
            queue.append((sp, depth))

    enqueue(root_id, 0)

    while queue:
        nid, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for child in children_of.get(nid, []):
            enqueue(child, depth + 1)

    return gen


# ──────────────────────────────────────────────────────────────────────────────
# TAB 1 — SUNBURST
# ──────────────────────────────────────────────────────────────────────────────

def build_sunburst(
    df: pd.DataFrame,
    root_id: str,
    children_of: dict,
    spouse_of: dict,
    desc_count: dict,
    max_depth: int,
) -> go.Figure:
    """
    Plotly Sunburst: корень → потомки по поколениям.
    Супруги добавляются как жёлтые листья (ограничение подхода).
    """
    valid = set(df["id"])
    row_by = df.set_index("id").to_dict("index")

    ids, labels, parents, values, colors, hovers = [], [], [], [], [], []

    def add(nid: str, par: str, depth: int) -> None:
        if depth > max_depth or nid not in valid:
            return
        r = row_by[nid]
        name = r["name"]
        by = r["birth_year"]
        dc = desc_count.get(nid, 0)
        g = r["gender"]

        lbl = name
        if pd.notna(by):
            lbl += f"<br>р.{int(by)}"
        if dc:
            lbl += f"<br>↓{dc}"

        tip = [f"<b>{name}</b>"]
        if pd.notna(by):
            tip.append(f"Рождение: {int(by)}")
        tip.append(f"Потомков: {dc}")
        tip.append(f"Пол: {'М' if g == 'M' else 'Ж'}")

        ids.append(nid)
        labels.append(lbl)
        parents.append(par)
        values.append(1 if not children_of.get(nid) else 0)
        colors.append(C_M if g == "M" else C_F if g == "F" else "#aaaaaa")
        hovers.append("<br>".join(tip))

        # Супруг как жёлтый лист
        sp = spouse_of.get(nid, "")
        if sp and sp in valid and depth < max_depth:
            sp_r = row_by[sp]
            sp_name = sp_r["name"]
            sp_by = sp_r["birth_year"]
            sp_lbl = f"💍 {sp_name}"
            if pd.notna(sp_by):
                sp_lbl += f"<br>р.{int(sp_by)}"
            ids.append(f"_sp_{nid}")
            labels.append(sp_lbl)
            parents.append(nid)
            values.append(1)
            colors.append(C_SPOUSE)
            hovers.append(f"<b>{sp_name}</b> (супруг/а)<br>⚠️ Ветка не развёрнута — выберите как корень")

        for child in children_of.get(nid, []):
            add(child, nid, depth + 1)

    add(root_id, "", 0)

    if not ids:
        return go.Figure()

    fig = go.Figure(go.Sunburst(
        ids=ids, labels=labels, parents=parents, values=values,
        hovertext=hovers, hoverinfo="text",
        marker=dict(colors=colors, line=dict(width=1, color="white")),
        textfont=dict(size=11, family="Arial"),
        branchvalues="remainder",
        insidetextorientation="radial",
        maxdepth=max_depth + 1,
    ))
    fig.update_layout(
        margin=dict(t=10, l=0, r=0, b=0),
        paper_bgcolor=BG, font=dict(color="white"), height=680,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# TAB 2 — NETWORK GRAPH
# ──────────────────────────────────────────────────────────────────────────────

def _sort_couples(people: list[str], spouse_of: dict) -> list[str]:
    """Расставить список так, чтобы супруги стояли рядом."""
    result, seen = [], set()
    for p in people:
        if p in seen:
            continue
        result.append(p)
        seen.add(p)
        sp = spouse_of.get(p, "")
        if sp and sp in people and sp not in seen:
            result.append(sp)
            seen.add(sp)
    return result


def _genealogical_layout(
    node_gens: dict[str, int],
    spouse_of: dict,
    father_of: dict,
    mother_of: dict,
    children_of: dict,
) -> dict[str, tuple[float, float]]:
    """
    Кастомный layout:
    - Y = поколение (сверху вниз)
    - X = позиция в поколении; супруги рядом
    - Центровка родителей над детьми (два прохода)
    """
    by_gen: dict[int, list[str]] = defaultdict(list)
    for nid, g in node_gens.items():
        by_gen[g].append(nid)

    pos: dict[str, tuple[float, float]] = {}
    X_STEP = 3.0
    Y_STEP = 4.5

    # Первый проход: равномерное расположение с супругами рядом
    for g in sorted(by_gen):
        ordered = _sort_couples(by_gen[g], spouse_of)
        n = len(ordered)
        for i, nid in enumerate(ordered):
            pos[nid] = ((i - (n - 1) / 2) * X_STEP, -g * Y_STEP)

    # Второй проход: сдвигаем пару над центром их детей (снизу вверх)
    for g in sorted(by_gen, reverse=True):
        for nid in by_gen[g]:
            if nid not in pos:
                continue
            ch = [c for c in children_of.get(nid, []) if c in pos]
            if not ch:
                continue
            cx = sum(pos[c][0] for c in ch) / len(ch)
            sp = spouse_of.get(nid, "")
            x0, y0 = pos[nid]
            if sp and sp in pos:
                sx, sy = pos[sp]
                mid = (x0 + sx) / 2
                shift = (cx - mid) * 0.4
                pos[nid] = (x0 + shift, y0)
                pos[sp]  = (sx + shift, sy)
            else:
                pos[nid] = (x0 * 0.6 + cx * 0.4, y0)

    return pos


def build_network_figure(
    df: pd.DataFrame,
    root_id: str,
    father_of: dict,
    mother_of: dict,
    spouse_of: dict,
    children_of: dict,
    desc_count: dict,
    max_depth: int,
) -> go.Figure:
    """
    Интерактивный граф на networkx + plotly.
    Рёбра: родитель→ребёнок (серый), супруги (оранжевый пунктир).
    Узлы: цвет по полу, размер по числу потомков.
    """
    valid = set(df["id"])
    node_gens = get_subtree(root_id, children_of, spouse_of, valid, max_depth)
    if not node_gens:
        return go.Figure()

    pos = _genealogical_layout(node_gens, spouse_of, father_of, mother_of, children_of)
    row_by = df.set_index("id").to_dict("index")
    vis = set(pos.keys())

    # Построим граф networkx (для аналитики, не для layout)
    G = nx.DiGraph()
    for nid in vis:
        G.add_node(nid)
        fid = father_of.get(nid, "")
        mid = mother_of.get(nid, "")
        if fid and fid in vis:
            G.add_edge(fid, nid, etype="parent")
        if mid and mid in vis:
            G.add_edge(mid, nid, etype="parent")
    sp_pairs: set[frozenset] = set()
    for nid in vis:
        sp = spouse_of.get(nid, "")
        if sp and sp in vis:
            p = frozenset({nid, sp})
            if p not in sp_pairs:
                sp_pairs.add(p)
                G.add_edge(nid, sp, etype="spouse")

    # ── Рёбра родитель→ребёнок ──
    ex_pc, ey_pc = [], []
    for u, v, d in G.edges(data=True):
        if d["etype"] == "parent" and u in pos and v in pos:
            x0, y0 = pos[u]; x1, y1 = pos[v]
            ex_pc += [x0, x1, None]; ey_pc += [y0, y1, None]

    trace_pc = go.Scatter(
        x=ex_pc, y=ey_pc, mode="lines",
        line=dict(width=1.5, color="#6666aa"),
        hoverinfo="none", showlegend=False,
    )

    # ── Рёбра супругов ──
    ex_sp, ey_sp = [], []
    for nid, sp in ((a, b) for a, b in [list(p) for p in sp_pairs]):
        if nid in pos and sp in pos:
            x0, y0 = pos[nid]; x1, y1 = pos[sp]
            ex_sp += [x0, x1, None]; ey_sp += [y0, y1, None]

    trace_sp = go.Scatter(
        x=ex_sp, y=ey_sp, mode="lines",
        line=dict(width=2.5, color=C_SPOUSE, dash="dot"),
        hoverinfo="none", showlegend=False,
    )

    # ── Узлы ──
    xs, ys, node_clr, sizes, texts, hovers, cdata = [], [], [], [], [], [], []
    for nid in vis:
        x, y = pos[nid]
        xs.append(x); ys.append(y)
        r = row_by.get(nid, {})
        name = r.get("name", nid)
        gender = r.get("gender", "")
        by = r.get("birth_year", "")
        dc = desc_count.get(nid, 0)
        g_lv = node_gens.get(nid, 0)
        sp = spouse_of.get(nid, "")

        short = name.split()[0] if name else nid
        texts.append(short)

        tip = [f"<b>{name}</b>", f"Поколение: {g_lv}"]
        if pd.notna(by) and by != "":
            tip.append(f"Рождение: {int(float(by))}")
        tip.append(f"Потомков: {dc}")
        if sp and sp in row_by:
            tip.append(f"Супруг/а: {row_by[sp].get('name', sp)}")
        tip.append("<i>Клик → сделать корнем</i>")
        hovers.append("<br>".join(tip))

        if nid == root_id:
            node_clr.append(C_ROOT)
        elif gender == "M":
            node_clr.append(C_M)
        elif gender == "F":
            node_clr.append(C_F)
        else:
            node_clr.append("#aaaaaa")

        sizes.append(max(14, min(40, 14 + dc * 2)))
        cdata.append(nid)

    trace_nodes = go.Scatter(
        x=xs, y=ys, mode="markers+text",
        marker=dict(size=sizes, color=node_clr, line=dict(width=2, color="white")),
        text=texts, textposition="top center",
        textfont=dict(size=10, color="white"),
        hovertext=hovers, hoverinfo="text",
        customdata=cdata,
    )

    # Подписи поколений
    max_g = max(node_gens.values()) if node_gens else 0
    annotations = [
        dict(x=-18, y=-g * 4.5, text=f"Пок. {g}",
             showarrow=False, font=dict(color="#666688", size=11), xanchor="right")
        for g in range(max_g + 1)
    ]

    fig = go.Figure(data=[trace_pc, trace_sp, trace_nodes])
    fig.update_layout(
        showlegend=False,
        plot_bgcolor=BG, paper_bgcolor=BG, font=dict(color="white"),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-19, None]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=680,
        margin=dict(t=20, l=90, r=20, b=20),
        hovermode="closest",
        clickmode="event+select",
        annotations=annotations,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3 — GRAPHVIZ
# ──────────────────────────────────────────────────────────────────────────────

def build_graphviz_dot(
    df: pd.DataFrame,
    root_id: str,
    father_of: dict,
    mother_of: dict,
    spouse_of: dict,
    children_of: dict,
    max_depth: int,
) -> str:
    """
    DOT-код для Graphviz.
    Паттерн: супруги на одном ранге, между ними невидимый узел-точка (junction).
    Дети подключаются к junction-узлу → классическое генеалогическое дерево.
    """
    valid = set(df["id"])
    node_gens = get_subtree(root_id, children_of, spouse_of, valid, max_depth)
    vis = set(node_gens.keys())
    row_by = df.set_index("id").to_dict("index")

    lines = [
        "digraph family {",
        f'  bgcolor="{BG}";',
        "  rankdir=TB;",
        '  node [fontname="Arial", fontsize=10, style="rounded,filled", margin="0.12,0.06"];',
        '  edge [color="#888888"];',
        "",
    ]

    # ── Объявление узлов ──
    for nid in vis:
        r = row_by.get(nid, {})
        name = r.get("name", nid).replace('"', '\\"')
        by = r.get("birth_year", "")
        gender = r.get("gender", "")

        lbl = name
        if pd.notna(by) and by not in ("", None):
            try:
                lbl += f"\\nр.{int(float(by))}"
            except (ValueError, TypeError):
                pass

        if nid == root_id:
            fc, fn = "#4a3a00", C_ROOT
        elif gender == "M":
            fc, fn = "#0d2a47", "#aad4ff"
        elif gender == "F":
            fc, fn = "#47100d", "#ffaad4"
        else:
            fc, fn = "#1e1e3a", "#cccccc"

        border = ', penwidth=3, color="#ffd700"' if nid == root_id else ""
        lines.append(
            f'  "{nid}" [label="{lbl}", fillcolor="{fc}", fontcolor="{fn}"{border}];'
        )

    lines.append("")

    # ── Семейные блоки: пара + дети через junction ──
    processed: set[frozenset] = set()
    jcount = 0

    for nid in vis:
        sp = spouse_of.get(nid, "")
        ch_all = [c for c in children_of.get(nid, []) if c in vis]
        if not ch_all:
            continue

        if sp and sp in vis:
            pair_key = frozenset({nid, sp})
            if pair_key in processed:
                continue
            processed.add(pair_key)

            # Дети обоих родителей
            ch_sp = [c for c in children_of.get(sp, []) if c in vis]
            ch_common = [c for c in ch_all if c in ch_sp or father_of.get(c) == nid or mother_of.get(c) == nid]
            if not ch_common:
                ch_common = ch_all

            jid = f"_j{jcount}"
            jcount += 1

            lines.append(f'  "{jid}" [shape=point, width=0.01, height=0.01, label=""];')
            lines.append(f'  {{ rank=same; "{nid}"; "{jid}"; "{sp}"; }}')
            # Невидимые рёбра для позиционирования junction между родителями
            lines.append(f'  "{nid}" -> "{jid}" [style=invis, weight=10];')
            lines.append(f'  "{jid}" -> "{sp}" [style=invis, weight=10];')
            # Видимое ребро супругов (без влияния на rank)
            lines.append(
                f'  "{nid}" -> "{sp}" [dir=none, style=dashed, '
                f'color="{C_SPOUSE}", constraint=false, penwidth=2];'
            )
            # Дети от junction
            for c in ch_common:
                lines.append(f'  "{jid}" -> "{c}" [arrowhead=vee, arrowsize=0.7];')

        else:
            # Одиночный родитель → дети
            jid = f"_j{jcount}"
            jcount += 1
            lines.append(f'  "{jid}" [shape=point, width=0.01, height=0.01, label=""];')
            lines.append(f'  "{nid}" -> "{jid}" [arrowhead=none];')
            for c in ch_all:
                lines.append(f'  "{jid}" -> "{c}" [arrowhead=vee, arrowsize=0.7];')

        lines.append("")

    lines.append("}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# MAIN APP
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Session state ──
    if "root_id" not in st.session_state:
        st.session_state.root_id = None
    if "raw_csv" not in st.session_state:
        st.session_state.raw_csv = DEMO_CSV

    # ── Sidebar ────────────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("🌳 Настройки")
        st.markdown("---")

        src = st.radio("Источник данных", ["Демо (Тимофеевы)", "Загрузить CSV"])
        if src == "Загрузить CSV":
            f = st.file_uploader("CSV файл", type="csv")
            if f:
                new_csv = f.read().decode("utf-8")
                if new_csv != st.session_state.raw_csv:
                    st.session_state.raw_csv = new_csv
                    st.session_state.root_id = None
                st.success("Загружено!")
        else:
            if st.session_state.raw_csv != DEMO_CSV:
                st.session_state.raw_csv = DEMO_CSV
                st.session_state.root_id = None

        st.markdown("---")
        st.markdown("**Формат CSV**")
        st.code(
            "id, name, birth_year, gender\nfather_id, mother_id, spouse_id",
            language="text",
        )
        st.download_button(
            "⬇️ Скачать шаблон",
            data=DEMO_CSV, file_name="family_template.csv", mime="text/csv",
        )

    # ── Load data ──────────────────────────────────────────────────────────────
    raw = st.session_state.raw_csv
    df = load_df(raw)
    father_of, mother_of, spouse_of, children_of = index_family(df)
    desc_count = compute_desc_count(raw)

    id_list = df["id"].tolist()
    if st.session_state.root_id not in set(id_list):
        st.session_state.root_id = id_list[0]

    # ── Header ─────────────────────────────────────────────────────────────────
    st.title("🌳 Генеалогическое дерево")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Персон", len(df))
    c2.metric("Мужчин", int((df["gender"] == "M").sum()))
    c3.metric("Женщин", int((df["gender"] == "F").sum()))
    c4.metric("Пар", int(df["spouse_id"].ne("").sum()) // 2)
    st.markdown("---")

    # ── Глобальный выбор корня ─────────────────────────────────────────────────
    name_to_id = dict(zip(df["name"], df["id"]))
    id_to_name = dict(zip(df["id"], df["name"]))
    name_list = df["name"].tolist()
    cur_name = id_to_name.get(st.session_state.root_id, name_list[0])
    cur_idx = name_list.index(cur_name) if cur_name in name_list else 0

    chosen_name = st.selectbox(
        "🔍 Корень / центральная персона (выбрать из списка или кликнуть на узел в «Сетевом графе»)",
        options=name_list, index=cur_idx, key="root_select",
    )
    root_id = name_to_id[chosen_name]
    st.session_state.root_id = root_id

    # ── Вкладки ────────────────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        "☀️ Sunburst (иерархия)",
        "🔗 Сетевой граф",
        "📐 Graphviz",
    ])

    # ════════════════════════════════════════════════════════════════════════════
    # TAB 1: SUNBURST
    # ════════════════════════════════════════════════════════════════════════════
    with tab1:
        st.caption(
            "Иерархия потомков выбранного человека. "
            "Жёлтые сегменты 💍 — супруги (показаны как листья, ветка не раскрыта). "
            "**Кликните** на сегмент для zoom-in."
        )
        depth_sb = st.slider("Глубина поколений", 1, 8, 4, key="sb_d")

        fig_sb = build_sunburst(df, root_id, children_of, spouse_of, desc_count, depth_sb)
        st.plotly_chart(fig_sb, use_container_width=True)

        st.info(
            "💡 **Ограничение Sunburst:** Plotly Sunburst требует строгой иерархии "
            "«один родитель → дети». Супруги по природе не вписываются в эту модель "
            "(у них независимая ветка). Поэтому они показаны жёлтыми листьями рядом "
            "с человеком. Для корректного отображения супругов используйте вкладки 2 и 3."
        )

    # ════════════════════════════════════════════════════════════════════════════
    # TAB 2: NETWORK
    # ════════════════════════════════════════════════════════════════════════════
    with tab2:
        col_graph, col_info = st.columns([3, 1])

        with col_info:
            depth_net = st.slider("Глубина", 1, 6, 3, key="net_d")
            st.markdown("---")
            st.markdown("**Легенда**")
            st.markdown(f"<span style='color:{C_M}'>■</span> Мужчина", unsafe_allow_html=True)
            st.markdown(f"<span style='color:{C_F}'>■</span> Женщина", unsafe_allow_html=True)
            st.markdown(f"<span style='color:{C_ROOT}'>■</span> Корень", unsafe_allow_html=True)
            st.markdown("─── Родитель → ребёнок")
            st.markdown(f"<span style='color:{C_SPOUSE}'>╌╌╌</span> Супруги", unsafe_allow_html=True)
            st.markdown("*Размер = потомки*")
            st.markdown("---")

            # Карточка текущей персоны
            r_root = df[df["id"] == root_id]
            if not r_root.empty:
                r = r_root.iloc[0]
                st.markdown(f"**{r['name']}**")
                by = r["birth_year"]
                if pd.notna(by):
                    st.markdown(f"Рождение: {int(by)}")
                st.markdown(f"Потомков: {desc_count.get(root_id, 0)}")

                sp_id = spouse_of.get(root_id, "")
                sp_row = df[df["id"] == sp_id] if sp_id else pd.DataFrame()
                if not sp_row.empty:
                    sp_name = sp_row.iloc[0]["name"]
                    if st.button(f"💍 {sp_name}", key="goto_sp", help="Перейти в ветку супруга"):
                        st.session_state.root_id = sp_id
                        st.rerun()

                # Родители
                fid = father_of.get(root_id, "")
                mid = mother_of.get(root_id, "")
                if fid and fid in set(df["id"]):
                    fn = id_to_name.get(fid, fid)
                    if st.button(f"👨 {fn}", key="goto_f"):
                        st.session_state.root_id = fid
                        st.rerun()
                if mid and mid in set(df["id"]):
                    mn = id_to_name.get(mid, mid)
                    if st.button(f"👩 {mn}", key="goto_m"):
                        st.session_state.root_id = mid
                        st.rerun()

                # Дети
                ch = [c for c in children_of.get(root_id, []) if c in set(df["id"])]
                if sp_id:
                    ch += [c for c in children_of.get(sp_id, []) if c in set(df["id"]) and c not in ch]
                if ch:
                    st.markdown(f"**Дети ({len(ch)}):**")
                    for cid in ch[:6]:
                        if st.button(id_to_name.get(cid, cid), key=f"goto_{cid}"):
                            st.session_state.root_id = cid
                            st.rerun()

        with col_graph:
            st.caption(
                "Кликните на узел → он становится новым корнем. "
                "Используйте 🔍 Корень выше или кнопки справа для навигации."
            )
            fig_net = build_network_figure(
                df, root_id,
                father_of, mother_of, spouse_of, children_of,
                desc_count, depth_net,
            )
            event = st.plotly_chart(
                fig_net, use_container_width=True,
                on_select="rerun", key="net_chart",
            )

        # Обработка клика по узлу
        if event and hasattr(event, "selection"):
            pts = getattr(event.selection, "points", [])
            if pts:
                clicked = pts[0].get("customdata") if isinstance(pts[0], dict) else None
                if clicked and clicked in set(df["id"]) and clicked != root_id:
                    st.session_state.root_id = clicked
                    st.rerun()

    # ════════════════════════════════════════════════════════════════════════════
    # TAB 3: GRAPHVIZ
    # ════════════════════════════════════════════════════════════════════════════
    with tab3:
        st.caption(
            "Классическая диаграмма: супруги на одном уровне, "
            "дети подключены через невидимый узел-точку (junction node)."
        )
        depth_gv = st.slider("Глубина поколений", 1, 5, 3, key="gv_d")

        dot_code = build_graphviz_dot(
            df, root_id,
            father_of, mother_of, spouse_of, children_of,
            depth_gv,
        )

        try:
            st.graphviz_chart(dot_code, use_container_width=True)
        except Exception as e:
            st.error(f"Graphviz недоступен: {e}")
            st.info("Установите: `sudo apt-get install graphviz`")

        with st.expander("🔎 DOT-код"):
            st.code(dot_code, language="dot")

        with st.expander("ℹ️ Как работает junction node"):
            st.markdown(
                "Для корректного отображения двух родителей с общими детьми используется "
                "**невидимый узел-точка** (junction node, `shape=point`):\n\n"
                "```\n[Отец] ──●── [Мать]   ← один ранг\n"
                "          │\n"
                "       [Ребёнок]          ← следующий ранг\n```\n\n"
                "Атрибут `{rank=same}` фиксирует отца, точку и мать на одном уровне. "
                "Пунктирная оранжевая линия между супругами добавляется с `constraint=false` "
                "— она не влияет на ранжирование."
            )


if __name__ == "__main__":
    main()
