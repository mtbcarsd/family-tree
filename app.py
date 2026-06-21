"""
app.py — Генеалогическое дерево рода Дымковых (v2)
CSV: output/family_data_v2.csv
     id,name,birth_year,death_year,gender,father_id,mother_id,spouse_id,
     location,source_part,notes,family

Запуск:  streamlit run app.py
"""
from __future__ import annotations

import io
from collections import defaultdict, deque
from pathlib import Path

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from reportlab.lib import colors as rl_colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Древо рода Дымковых",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSV_PATH = Path(__file__).parent / "output" / "family_data_v2.csv"

BG       = "#0f0f1a"
C_M      = "#4a9eda"    # мужчины
C_F      = "#e87a9a"    # женщины
C_ROOT   = "#ffd700"    # выбранный корень
C_SPOUSE = "#ff9f43"    # линия / лист супруга

# Ярлыки для быстрого перехода к ветке
BRANCH_PRESETS = {
    "🌳 Дымковы (Тимофеев 1800)": "root_T",
    "🌿 Шуст (Тарас Шуст)":       "sh_root_Tar",
}

# ──────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА И ИНДЕКСИРОВАНИЕ
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_data
def load_df() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
    for col in ("id", "name", "gender", "father_id", "mother_id", "spouse_id",
                "location", "source_part", "notes", "family"):
        df[col] = df[col].str.strip()
    df["gender"] = df["gender"].str.upper()
    df["birth_year"] = pd.to_numeric(df["birth_year"], errors="coerce")
    df["death_year"] = pd.to_numeric(df["death_year"], errors="coerce")
    return df


def index_family(df: pd.DataFrame):
    """
    Строит четыре словаря:
    - father_of, mother_of, spouse_of: id → id
    - children_of: id → list[id]  (первичный родитель: отец; мать — fallback если отца нет)
    """
    valid = set(df["id"])
    father_of = {r["id"]: r["father_id"] for _, r in df.iterrows()}
    mother_of  = {r["id"]: r["mother_id"] for _, r in df.iterrows()}
    spouse_of  = {r["id"]: r["spouse_id"] for _, r in df.iterrows()}

    children_of: dict[str, list[str]] = defaultdict(list)
    for _, row in df.iterrows():
        cid = row["id"]
        fid = row["father_id"]
        mid = row["mother_id"]
        if fid and fid in valid:
            children_of[fid].append(cid)
        elif mid and mid in valid:        # нет отца — первичный родитель мать
            children_of[mid].append(cid)
    return father_of, mother_of, spouse_of, children_of


@st.cache_data
def compute_desc_count_cached() -> dict[str, int]:
    """Считает потомков от всех персон (кеш по всему дереву)."""
    df = load_df()
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


def compute_depth_from(root_id: str, children_of: dict) -> dict[str, int]:
    """BFS-глубина от root_id."""
    depths: dict[str, int] = {}
    q: deque[tuple[str, int]] = deque([(root_id, 0)])
    while q:
        nid, d = q.popleft()
        if nid in depths:
            continue
        depths[nid] = d
        for c in children_of.get(nid, []):
            q.append((c, d + 1))
    return depths


# ──────────────────────────────────────────────────────────────────────────────
# ПОДГРАФ ДЛЯ ВИЗУАЛИЗАЦИИ
# ──────────────────────────────────────────────────────────────────────────────

def get_subtree(
    root_id: str,
    children_of: dict,
    spouse_of: dict,
    valid: set,
    max_depth: int,
) -> dict[str, int]:
    """BFS потомков + супруги на том же уровне. Возвращает {id: поколение}."""
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
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ DRILL-DOWN ВЕТКИ СУПРУГА
# ──────────────────────────────────────────────────────────────────────────────

def find_ancestral_root(nid: str, father_of: dict, valid: set) -> str:
    """Поднимается по father_id до корня предков."""
    current, visited = nid, set()
    while True:
        fid = father_of.get(current, "")
        if fid and fid in valid and fid not in visited:
            visited.add(current)
            current = fid
        else:
            return current


def build_sunburst_spouse_view(
    df: pd.DataFrame,
    spouse_id: str,        # напр. gen3_RaiMiPah (Раиса)
    came_from_id: str,     # напр. gen3_MiPah (Михаил — точка входа из основного дерева)
    father_of: dict,
    mother_of: dict,
    children_of: dict,
    spouse_of: dict,
    desc_count: dict,
    max_depth: int = 5,
) -> tuple[go.Figure, str]:
    """
    Sunburst для ветки супруга.

    - Корень = самый дальний предок spouse_id по отцовской линии.
    - spouse_id подсвечен золотым (точка связи).
    - Совместные дети обоих (came_from + spouse) включены под spouse_id
      и окрашены бронзовым.
    - came_from НЕ показывается как 💍-лист (избегаем путаницы).
    """
    valid  = set(df["id"])
    row_by = df.set_index("id").to_dict("index")

    # Предковый корень супруга
    anc_root      = find_ancestral_root(spouse_id, father_of, valid)
    anc_root_name = row_by.get(anc_root, {}).get("name", anc_root)

    # Совместные дети: у кого (father=came_from AND mother=spouse) или наоборот
    joint: set[str] = {
        row["id"] for _, row in df.iterrows()
        if (
            (row["father_id"] == came_from_id and row["mother_id"] == spouse_id)
            or (row["father_id"] == spouse_id  and row["mother_id"] == came_from_id)
        )
    }

    # Расширенный children_of: добавляем joint-детей к spouse_id
    ext_ch: dict[str, list[str]] = defaultdict(list,
        {k: list(v) for k, v in children_of.items()}
    )
    for jc in joint:
        if jc not in ext_ch[spouse_id]:
            ext_ch[spouse_id].append(jc)

    depths = compute_depth_from(anc_root, ext_ch)

    ids, labels, parents, values, clrs, hovers = [], [], [], [], [], []

    def add(nid: str, par: str) -> None:
        d = depths.get(nid, 0)
        if d > max_depth or nid not in valid:
            return
        r    = row_by.get(nid, {})
        name = r.get("name", nid)
        by   = r.get("birth_year", "")
        dc   = desc_count.get(nid, 0)
        g    = r.get("gender", "")
        is_joint = nid in joint

        lbl = name
        if pd.notna(by) and by not in ("", None):
            try:
                lbl += f"<br>р.{int(float(by))}"
            except (ValueError, TypeError):
                pass
        if dc:
            lbl += f"<br>↓{dc}"

        tip = [f"<b>{name}</b>"]
        if nid == spouse_id:
            cf_name = row_by.get(came_from_id, {}).get("name", came_from_id)
            tip += [f"⭐ Точка связи с веткой Дымковых",
                    f"Супруг/а: {cf_name}"]
        elif is_joint:
            cf_name = row_by.get(came_from_id, {}).get("name", came_from_id)
            tip.append(f"Общий ребёнок двух семей ({cf_name})")
        if pd.notna(by) and by not in ("", None):
            try:
                tip.append(f"Рождение: {int(float(by))}")
            except (ValueError, TypeError):
                pass
        tip.append(f"Потомков: {dc}")

        ids.append(nid)
        labels.append(lbl)
        parents.append(par)
        values.append(1 if not ext_ch.get(nid) else 0)

        if nid == spouse_id:
            clrs.append(C_ROOT)          # золото — точка входа
        elif is_joint:
            clrs.append("#c87433")       # бронза — совместная линия
        elif g == "M":
            clrs.append(C_M)
        elif g == "F":
            clrs.append(C_F)
        else:
            clrs.append("#aaaaaa")

        hovers.append("<br>".join(tip))

        # 💍 супруги-листья (came_from не показываем — он из основного дерева)
        sp = spouse_of.get(nid, "")
        if sp and sp in valid and sp != came_from_id and d < max_depth:
            sp_r   = row_by.get(sp, {})
            sp_name = sp_r.get("name", sp)
            sp_by  = sp_r.get("birth_year", "")
            sp_lbl = f"💍 {sp_name}"
            if pd.notna(sp_by) and sp_by not in ("", None):
                try:
                    sp_lbl += f"<br>р.{int(float(sp_by))}"
                except (ValueError, TypeError):
                    pass
            ids.append(f"_sp2_{nid}")
            labels.append(sp_lbl)
            parents.append(nid)
            values.append(1)
            clrs.append(C_SPOUSE)
            hovers.append(f"<b>{sp_name}</b> (супруг/а)")

        for child in ext_ch.get(nid, []):
            add(child, nid)

    add(anc_root, "")

    if not ids:
        return go.Figure(), anc_root_name

    fig = go.Figure(go.Sunburst(
        ids=ids, labels=labels, parents=parents, values=values,
        hovertext=hovers, hoverinfo="text",
        marker=dict(colors=clrs, line=dict(width=1, color="white")),
        textfont=dict(size=11, family="Arial"),
        branchvalues="remainder",
        insidetextorientation="radial",
    ))
    fig.update_layout(
        margin=dict(t=10, l=0, r=0, b=0),
        paper_bgcolor=BG, font=dict(color="white"), height=560,
    )
    return fig, anc_root_name


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
    valid   = set(df["id"])
    row_by  = df.set_index("id").to_dict("index")
    depths  = compute_depth_from(root_id, children_of)

    ids, labels, parents, values, node_colors, hovers = [], [], [], [], [], []

    def add(nid: str, par: str) -> None:
        d = depths.get(nid, 0)
        if d > max_depth or nid not in valid:
            return
        r    = row_by[nid]
        name = r["name"]
        by   = r["birth_year"]
        dc   = desc_count.get(nid, 0)
        g    = r["gender"]

        lbl = name
        if pd.notna(by):
            lbl += f"<br>р.{int(by)}"
        if dc:
            lbl += f"<br>↓{dc}"

        tip = [f"<b>{name}</b>", f"Поколение: {d}"]
        if pd.notna(by):
            tip.append(f"Рождение: {int(by)}")
        dy = r["death_year"]
        if pd.notna(dy):
            tip.append(f"Смерть: {int(dy)}")
        loc = r.get("location", "")
        if loc:
            tip.append(f"Место: {loc}")
        tip.append(f"Потомков: {dc}")
        fam = r.get("family", "")
        if fam:
            tip.append(f"Ветка: {fam}")

        ids.append(nid)
        labels.append(lbl)
        parents.append(par)
        values.append(1 if not children_of.get(nid) else 0)
        node_colors.append(C_ROOT if nid == root_id
                           else C_M if g == "M" else C_F)
        hovers.append("<br>".join(tip))

        # Супруг — жёлтый лист
        sp = spouse_of.get(nid, "")
        if sp and sp in valid and d < max_depth:
            sp_r   = row_by[sp]
            sp_name = sp_r["name"]
            sp_by  = sp_r["birth_year"]
            sp_lbl = f"💍 {sp_name}"
            if pd.notna(sp_by):
                sp_lbl += f"<br>р.{int(sp_by)}"
            ids.append(f"_sp_{nid}")
            labels.append(sp_lbl)
            parents.append(nid)
            values.append(1)
            node_colors.append(C_SPOUSE)
            hovers.append(
                f"<b>{sp_name}</b> (супруг/а)<br>"
                f"⚠️ Ветка не развёрнута здесь — выберите как корень"
            )

        for child in children_of.get(nid, []):
            add(child, nid)

    add(root_id, "")

    if not ids:
        return go.Figure()

    fig = go.Figure(go.Sunburst(
        ids=ids, labels=labels, parents=parents, values=values,
        customdata=ids,            # нужно для on_select: получаем node-id по клику
        hovertext=hovers, hoverinfo="text",
        marker=dict(colors=node_colors, line=dict(width=1, color="white")),
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
# TAB 2 — TREEMAP (верификация структуры)
# ──────────────────────────────────────────────────────────────────────────────

def build_treemap(
    df: pd.DataFrame,
    root_id: str,
    children_of: dict,
    desc_count: dict,
    max_depth: int,
) -> go.Figure:
    depths  = compute_depth_from(root_id, children_of)
    valid   = set(df["id"])
    row_by  = df.set_index("id").to_dict("index")

    PALETTE = ["#C0392B","#E74C3C","#E67E22","#F39C12",
               "#27AE60","#16A085","#2980B9","#8E44AD","#D35400"]

    ids, labels, parents, values, node_colors, hovers = [], [], [], [], [], []

    def add(nid: str, par: str) -> None:
        d = depths.get(nid, 99)
        if d > max_depth or nid not in valid:
            return
        r    = row_by[nid]
        name = r["name"]
        by   = r["birth_year"]
        dc   = desc_count.get(nid, 0)

        lbl_parts = [name]
        if pd.notna(by):
            dy = r["death_year"]
            lbl_parts.append(
                f"{int(by)}–{int(dy)}" if pd.notna(dy) else f"р.{int(by)}"
            )
        if dc > 0:
            lbl_parts.append(f"↓{dc}")

        tip = [f"<b>{name}</b>", f"Поколение: {d}"]
        if pd.notna(by):
            tip.append(f"Рождение: {int(by)}")
        loc = r.get("location", "")
        if loc:
            tip.append(f"Место: {loc}")
        tip.append(f"Потомков: {dc}")

        ids.append(nid)
        labels.append("<br>".join(lbl_parts))
        parents.append(par)
        values.append(1 if not children_of.get(nid) else 0)
        node_colors.append(PALETTE[min(d, len(PALETTE) - 1)])
        hovers.append("<br>".join(tip))

        for child in children_of.get(nid, []):
            add(child, nid)

    add(root_id, "")

    if not ids:
        return go.Figure()

    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values,
        hovertext=hovers, hoverinfo="text",
        marker=dict(colors=node_colors, line=dict(width=2, color="white"),
                    pad=dict(t=20, l=4, r=4, b=4)),
        textfont=dict(size=12, family="Arial"),
        textposition="middle center",
        branchvalues="remainder",
    ))
    fig.update_layout(
        margin=dict(t=10, l=0, r=0, b=0),
        paper_bgcolor=BG, font=dict(color="white"), height=720,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# TAB 3 — СЕТЕВОЙ ГРАФ
# ──────────────────────────────────────────────────────────────────────────────

def _sort_couples(people: list[str], spouse_of: dict) -> list[str]:
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
    children_of: dict,
) -> dict[str, tuple[float, float]]:
    by_gen: dict[int, list[str]] = defaultdict(list)
    for nid, g in node_gens.items():
        by_gen[g].append(nid)

    pos: dict[str, tuple[float, float]] = {}
    X_STEP, Y_STEP = 3.0, 4.5

    for g in sorted(by_gen):
        ordered = _sort_couples(by_gen[g], spouse_of)
        n = len(ordered)
        for i, nid in enumerate(ordered):
            pos[nid] = ((i - (n - 1) / 2) * X_STEP, -g * Y_STEP)

    # Центровка пар над детьми (снизу вверх)
    for g in sorted(by_gen, reverse=True):
        for nid in by_gen[g]:
            if nid not in pos:
                continue
            ch = [c for c in children_of.get(nid, []) if c in pos]
            if not ch:
                continue
            cx   = sum(pos[c][0] for c in ch) / len(ch)
            sp   = spouse_of.get(nid, "")
            x0, y0 = pos[nid]
            if sp and sp in pos:
                sx, sy = pos[sp]
                mid    = (x0 + sx) / 2
                shift  = (cx - mid) * 0.4
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
    valid     = set(df["id"])
    node_gens = get_subtree(root_id, children_of, spouse_of, valid, max_depth)
    if not node_gens:
        return go.Figure()

    pos    = _genealogical_layout(node_gens, spouse_of, children_of)
    row_by = df.set_index("id").to_dict("index")
    vis    = set(pos.keys())

    # ── Рёбра родитель→ребёнок ──
    ex_pc, ey_pc = [], []
    for nid in vis:
        fid = father_of.get(nid, "")
        mid = mother_of.get(nid, "")
        for pid in (fid, mid):
            if pid and pid in vis:
                x0, y0 = pos[pid]; x1, y1 = pos[nid]
                ex_pc += [x0, x1, None]; ey_pc += [y0, y1, None]

    trace_pc = go.Scatter(
        x=ex_pc, y=ey_pc, mode="lines",
        line=dict(width=1.5, color="#6666aa"),
        hoverinfo="none", showlegend=False,
    )

    # ── Рёбра супругов ──
    sp_pairs: set[frozenset] = set()
    for nid in vis:
        sp = spouse_of.get(nid, "")
        if sp and sp in vis:
            sp_pairs.add(frozenset({nid, sp}))

    ex_sp, ey_sp = [], []
    for pair in sp_pairs:
        a, b = list(pair)
        if a in pos and b in pos:
            x0, y0 = pos[a]; x1, y1 = pos[b]
            ex_sp += [x0, x1, None]; ey_sp += [y0, y1, None]

    trace_sp = go.Scatter(
        x=ex_sp, y=ey_sp, mode="lines",
        line=dict(width=2.5, color=C_SPOUSE, dash="dot"),
        hoverinfo="none", showlegend=False,
    )

    # ── Узлы ──
    xs, ys, clrs, sizes, texts, hovers, cdata = [], [], [], [], [], [], []
    for nid in vis:
        x, y = pos[nid]
        xs.append(x); ys.append(y)
        r      = row_by.get(nid, {})
        name   = r.get("name", nid)
        gender = r.get("gender", "")
        by     = r.get("birth_year", "")
        dc     = desc_count.get(nid, 0)
        g_lv   = node_gens.get(nid, 0)
        sp     = spouse_of.get(nid, "")
        fam    = r.get("family", "")

        texts.append(name.split()[0] if name else nid)

        tip = [f"<b>{name}</b>", f"Поколение: {g_lv}"]
        if pd.notna(by) and by != "":
            tip.append(f"Рождение: {int(float(by))}")
        dy = r.get("death_year", "")
        if pd.notna(dy) and dy != "":
            tip.append(f"Смерть: {int(float(dy))}")
        tip.append(f"Потомков: {dc}")
        if fam:
            tip.append(f"Ветка: {fam}")
        if sp and sp in row_by:
            tip.append(f"Супруг/а: {row_by[sp].get('name', sp)}")
        tip.append("<i>Клик → сделать корнем</i>")
        hovers.append("<br>".join(tip))

        clrs.append(
            C_ROOT if nid == root_id
            else C_M if gender == "M" else C_F
        )
        sizes.append(max(14, min(40, 14 + dc * 2)))
        cdata.append(nid)

    trace_nodes = go.Scatter(
        x=xs, y=ys, mode="markers+text",
        marker=dict(size=sizes, color=clrs, line=dict(width=2, color="white")),
        text=texts, textposition="top center",
        textfont=dict(size=10, color="white"),
        hovertext=hovers, hoverinfo="text",
        customdata=cdata,
    )

    max_g = max(node_gens.values()) if node_gens else 0
    annotations = [
        dict(x=-20, y=-g * 4.5, text=f"Пок. {g}",
             showarrow=False, font=dict(color="#666688", size=11), xanchor="right")
        for g in range(max_g + 1)
    ]

    fig = go.Figure(data=[trace_pc, trace_sp, trace_nodes])
    fig.update_layout(
        showlegend=False,
        plot_bgcolor=BG, paper_bgcolor=BG, font=dict(color="white"),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-21, None]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=700, margin=dict(t=20, l=90, r=20, b=20),
        hovermode="closest", clickmode="event+select",
        annotations=annotations,
    )
    return fig


# ──────────────────────────────────────────────────────────────────────────────
# TAB 4 — GRAPHVIZ
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
    valid     = set(df["id"])
    node_gens = get_subtree(root_id, children_of, spouse_of, valid, max_depth)
    vis       = set(node_gens.keys())
    row_by    = df.set_index("id").to_dict("index")

    lines = [
        "digraph family {",
        f'  bgcolor="{BG}";',
        "  rankdir=TB;",
        '  node [fontname="Arial", fontsize=10, style="rounded,filled", margin="0.12,0.06"];',
        '  edge [color="#888888"];',
        "",
    ]

    # Объявление узлов
    for nid in vis:
        r      = row_by.get(nid, {})
        name   = r.get("name", nid).replace('"', '\\"')
        by     = r.get("birth_year", "")
        gender = r.get("gender", "")

        lbl = name
        if pd.notna(by) and by not in ("", None):
            try:
                lbl += f"\\nр.{int(float(by))}"
            except (ValueError, TypeError):
                pass

        if nid == root_id:
            fc, fn, border = "#4a3a00", C_ROOT, ', penwidth=3, color="#ffd700"'
        elif gender == "M":
            fc, fn, border = "#0d2a47", "#aad4ff", ""
        elif gender == "F":
            fc, fn, border = "#47100d", "#ffaad4", ""
        else:
            fc, fn, border = "#1e1e3a", "#cccccc", ""

        lines.append(
            f'  "{nid}" [label="{lbl}", fillcolor="{fc}", fontcolor="{fn}"{border}];'
        )

    lines.append("")

    # Семейные блоки с junction node
    processed: set[frozenset] = set()
    jcount = 0

    for nid in vis:
        sp     = spouse_of.get(nid, "")
        ch_all = [c for c in children_of.get(nid, []) if c in vis]
        if not ch_all:
            continue

        if sp and sp in vis:
            pair_key = frozenset({nid, sp})
            if pair_key in processed:
                continue
            processed.add(pair_key)

            # Общие дети (оба родителя в vis)
            ch_sp  = [c for c in children_of.get(sp, []) if c in vis]
            ch_com = list({c for c in ch_all if c in ch_sp
                           or father_of.get(c) == nid
                           or mother_of.get(c) == nid})
            if not ch_com:
                ch_com = ch_all

            jid = f"_j{jcount}"
            jcount += 1
            lines.append(f'  "{jid}" [shape=point, width=0.01, height=0.01, label=""];')
            lines.append(f'  {{ rank=same; "{nid}"; "{jid}"; "{sp}"; }}')
            lines.append(f'  "{nid}" -> "{jid}" [style=invis, weight=10];')
            lines.append(f'  "{jid}" -> "{sp}" [style=invis, weight=10];')
            lines.append(
                f'  "{nid}" -> "{sp}" [dir=none, style=dashed, '
                f'color="{C_SPOUSE}", constraint=false, penwidth=2];'
            )
            for c in ch_com:
                lines.append(f'  "{jid}" -> "{c}" [arrowhead=vee, arrowsize=0.7];')
        else:
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
# PDF-ЭКСПОРТ
# ──────────────────────────────────────────────────────────────────────────────

def _register_cyrillic_font() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("CyrFont", path))
            bold_path = (path.replace("Regular", "Bold")
                         .replace("Sans.ttf", "Sans-Bold.ttf")
                         .replace("Ubuntu-R", "Ubuntu-B")
                         .replace("FreeSans", "FreeSansBold"))
            if Path(bold_path).exists():
                pdfmetrics.registerFont(TTFont("CyrFont-Bold", bold_path))
            else:
                pdfmetrics.registerFont(TTFont("CyrFont-Bold", path))
            return "CyrFont"
    return "Helvetica"


def build_pdf(
    fig: go.Figure,
    df: pd.DataFrame,
    root_name: str,
    desc_count: dict,
    depths: dict,
    id_to_name: dict,
) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )
    fn  = _register_cyrillic_font()
    fnb = fn + "-Bold" if fn == "CyrFont" else "Helvetica-Bold"

    title_s = ParagraphStyle("t", fontName=fnb, fontSize=16, leading=20,
                             spaceAfter=6, textColor=rl_colors.HexColor("#1a1a2e"))
    cap_s   = ParagraphStyle("c", fontName=fn,  fontSize=9,  leading=12,
                             textColor=rl_colors.HexColor("#555555"), spaceAfter=12)
    hd_s    = ParagraphStyle("h", fontName=fnb, fontSize=12, leading=16,
                             spaceBefore=12, spaceAfter=6,
                             textColor=rl_colors.HexColor("#1a1a2e"))
    cell_s  = ParagraphStyle("cl", fontName=fn, fontSize=8, leading=10)
    hdr_s   = ParagraphStyle("ch", fontName=fnb, fontSize=8, leading=10)

    story = [
        Paragraph("Генеалогическое древо рода Дымковых", title_s),
        Paragraph(
            f"Корень: {root_name} | Персон в отчёте: {len(df)} "
            f"| Поколений: {max(depths.values()) if depths else 0}",
            cap_s,
        ),
    ]

    try:
        png = fig.to_image(format="png", width=1200, height=700, scale=1.5)
        pw  = A4[0] - 3*cm
        story.append(Image(io.BytesIO(png), width=pw, height=pw*700/1200))
        story.append(Spacer(1, 0.4*cm))
    except Exception:
        story.append(Paragraph("(диаграмма недоступна — проверьте kaleido)", cap_s))

    story.append(Paragraph("Список персон", hd_s))

    tbl_data = [[
        Paragraph(h, hdr_s)
        for h in ["Имя", "Пол", "Пок.", "Рождение", "Смерть",
                  "Ветка", "Отец/мать", "Потомков"]
    ]]
    for _, row in df.sort_values(
        by=["id"], key=lambda s: s.map(lambda v: depths.get(v, 0))
    ).iterrows():
        by = row["birth_year"]
        dy = row["death_year"]
        fid = row.get("father_id", "") or row.get("mother_id", "")
        tbl_data.append([
            Paragraph(row["name"], cell_s),
            Paragraph("М" if row["gender"] == "M" else "Ж", cell_s),
            Paragraph(str(depths.get(row["id"], 0)), cell_s),
            Paragraph(str(int(by)) if pd.notna(by) else "—", cell_s),
            Paragraph(str(int(dy)) if pd.notna(dy) else "—", cell_s),
            Paragraph(row.get("family", "") or "—", cell_s),
            Paragraph(id_to_name.get(fid, "—") if fid else "—", cell_s),
            Paragraph(str(desc_count.get(row["id"], 0)), cell_s),
        ])

    col_w = [4.5*cm, 0.8*cm, 0.8*cm, 1.4*cm, 1.4*cm, 2*cm, 3.5*cm, 1.4*cm]
    tbl = Table(tbl_data, colWidths=col_w, repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",     (0,0),(-1,0),   rl_colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR",      (0,0),(-1,0),   rl_colors.white),
        ("ROWBACKGROUNDS", (0,1),(-1,-1),  [rl_colors.white, rl_colors.HexColor("#f0f0f8")]),
        ("GRID",           (0,0),(-1,-1),  0.3, rl_colors.HexColor("#cccccc")),
        ("VALIGN",         (0,0),(-1,-1),  "TOP"),
        ("TOPPADDING",     (0,0),(-1,-1),  3),
        ("BOTTOMPADDING",  (0,0),(-1,-1),  3),
    ]))
    story.append(tbl)
    doc.build(story)
    return buf.getvalue()


# ──────────────────────────────────────────────────────────────────────────────
# ГЛАВНАЯ СТРАНИЦА
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── Состояние сессии ──────────────────────────────────────────────────────
    if "root_id" not in st.session_state:
        st.session_state.root_id = "root_T"

    # ── Данные ──────────────────────────────────────────────────────────────
    df = load_df()
    father_of, mother_of, spouse_of, children_of = index_family(df)
    desc_count = compute_desc_count_cached()
    valid      = set(df["id"])
    id_to_name = dict(zip(df["id"], df["name"]))
    name_list  = df["name"].tolist()

    # Проверяем, что root_id из session_state валидный
    if st.session_state.root_id not in valid:
        st.session_state.root_id = "root_T"
    root_id = st.session_state.root_id

    # ── Боковая панель ────────────────────────────────────────────────────────
    with st.sidebar:
        st.title("🌳 Настройки")
        st.markdown("---")

        # Быстрый переход к ветке
        st.markdown("**Перейти к ветке:**")
        for label, bid in BRANCH_PRESETS.items():
            if st.button(label, use_container_width=True,
                         type="primary" if root_id == bid else "secondary"):
                st.session_state.root_id = bid
                st.rerun()

        st.markdown("---")

        # Выбор корня из списка
        cur_name   = id_to_name.get(root_id, name_list[0])
        cur_idx    = name_list.index(cur_name) if cur_name in name_list else 0
        chosen_name = st.selectbox(
            "🔍 Корень / центральная персона",
            options=name_list, index=cur_idx, key="root_sel",
        )
        new_root = df.loc[df["name"] == chosen_name, "id"].values
        if len(new_root) > 0 and new_root[0] != root_id:
            st.session_state.root_id = new_root[0]
            root_id = new_root[0]

        st.markdown("---")

        # Глубина — единый ползунок для всех вкладок, каждая перегрузит своё
        depth_global = st.slider("Глубина поколений (умолч.)", 1, 8, 4, key="g_depth")

        st.markdown("---")
        st.markdown("**Легенда**")
        st.markdown(f"<span style='color:{C_M}'>■</span> Мужчина", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{C_F}'>■</span> Женщина", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{C_ROOT}'>■</span> Корень", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{C_SPOUSE}'>💍</span> Супруг/а", unsafe_allow_html=True)
        st.markdown(f"<span style='color:{C_SPOUSE}'>╌╌╌</span> Брак", unsafe_allow_html=True)

        st.markdown("---")
        st.caption(f"Всего персон: **{len(df)}**  \n"
                   f"Дымковых: **{int((df['family']=='Дымковы').sum())}**  \n"
                   f"Шуст: **{int((df['family']=='Шуст').sum())}**")

    # ── Заголовок и метрики ───────────────────────────────────────────────────
    st.title("🌳 Генеалогическое древо")

    root_row = df[df["id"] == root_id]
    root_name = root_row["name"].values[0] if not root_row.empty else root_id
    st.caption(f"Корень: **{root_name}** | Потомков: {desc_count.get(root_id, 0)}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Всего персон", len(df))
    c2.metric("Мужчин", int((df["gender"] == "M").sum()))
    c3.metric("Женщин", int((df["gender"] == "F").sum()))
    c4.metric("Ветка Дымковы", int((df["family"] == "Дымковы").sum()))
    c5.metric("Ветка Шуст", int((df["family"] == "Шуст").sum()))
    st.markdown("---")

    # ── Вкладки ───────────────────────────────────────────────────────────────
    tab_sb, tab_net, tab_gv, tab_tm, tab_tbl, tab_stat = st.tabs([
        "☀️ Sunburst",
        "🔗 Сетевой граф",
        "📐 Graphviz",
        "🗺️ Treemap",
        "📋 Таблица",
        "📊 Статистика",
    ])

    # ════════════════════════════════════════════════════════════════════════════
    # SUNBURST
    # ════════════════════════════════════════════════════════════════════════════
    # ── сессия: drill-down ветки супруга ──────────────────────────────────────
    for _key in ("sb_spouse_id", "sb_came_from_id"):
        if _key not in st.session_state:
            st.session_state[_key] = None

    with tab_sb:
        st.caption(
            "Иерархия потомков. "
            "**Клик по сегменту** — сделать его новым корнем. "
            "**Клик по 💍-листу** — раскрыть ветку супруга ниже."
        )
        depth_sb = st.slider("Глубина", 1, 8, depth_global, key="sb_d")

        fig_sb = build_sunburst(df, root_id, children_of, spouse_of,
                                desc_count, depth_sb)

        event_sb = st.plotly_chart(
            fig_sb, use_container_width=True,
            on_select="rerun", key="sb_chart",
        )

        # ── обработка клика ───────────────────────────────────────────────────
        if event_sb and hasattr(event_sb, "selection"):
            pts = getattr(event_sb.selection, "points", [])
            if pts:
                p = pts[0]
                # Sunburst может вернуть customdata как строку или список
                raw = (p.get("customdata") or p.get("id")) if isinstance(p, dict) else None
                if isinstance(raw, (list, tuple)):
                    raw = raw[0] if raw else None
                clicked_id = str(raw) if raw is not None else None

                # Debug (временно): показываем что получили из события
                with st.expander("🛠 debug click event", expanded=False):
                    st.write(p)
                    st.write(f"extracted id: {clicked_id!r}")

                if clicked_id:
                    if clicked_id.startswith("_sp_"):
                        # 💍-лист: открываем ветку супруга
                        parent_of_sp = clicked_id[4:]          # убираем "_sp_"
                        sp_id_found  = spouse_of.get(parent_of_sp, "")
                        if sp_id_found and sp_id_found in valid:
                            st.session_state.sb_spouse_id    = sp_id_found
                            st.session_state.sb_came_from_id = parent_of_sp
                    elif clicked_id in valid and clicked_id != root_id:
                        # Обычный узел → новый корень
                        st.session_state.root_id         = clicked_id
                        st.session_state.sb_spouse_id    = None
                        st.session_state.sb_came_from_id = None
                        st.rerun()

        # ── кнопки экспорта ───────────────────────────────────────────────────
        btn1, btn2 = st.columns(2)
        with btn1:
            st.download_button(
                "⬇️ Скачать HTML",
                data=fig_sb.to_html(include_plotlyjs=True).encode("utf-8"),
                file_name="family_sunburst.html",
                mime="text/html",
                use_container_width=True,
            )
        with btn2:
            depths_sb = compute_depth_from(root_id, children_of)
            with st.spinner("Формирую PDF…"):
                pdf_bytes = build_pdf(
                    fig_sb, df, root_name, desc_count, depths_sb, id_to_name
                )
            st.download_button(
                "📄 Скачать PDF",
                data=pdf_bytes,
                file_name="family_report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

        st.info(
            "💡 Клик по сегменту → новый корень дерева. "
            "Клик по 💍 → ветка супруга раскрывается ниже. "
            "Для полной схемы браков используйте вкладку «Graphviz»."
        )

        # ══════════════════════════════════════════════════════════════════════
        # DRILL-DOWN: ветка супруга
        # ══════════════════════════════════════════════════════════════════════
        sp_drill_id = st.session_state.get("sb_spouse_id")
        cf_drill_id = st.session_state.get("sb_came_from_id")

        if sp_drill_id and sp_drill_id in valid:
            sp_name = id_to_name.get(sp_drill_id, sp_drill_id)
            cf_name = id_to_name.get(cf_drill_id, cf_drill_id) if cf_drill_id else ""

            st.markdown("---")
            st.markdown(f"### 🌿 Ветка: {sp_name}")
            st.caption(
                f"Вход из основного дерева: **{cf_name}** ↔ 💍 **{sp_name}**. "
                f"**Золотой** сегмент = точка связи с Дымковыми. "
                f"**Бронзовый** = совместные дети обеих семей."
            )

            col_cl, col_root = st.columns(2)
            with col_cl:
                if st.button("✖ Закрыть ветку", key="sb_close_sp"):
                    st.session_state.sb_spouse_id    = None
                    st.session_state.sb_came_from_id = None
                    st.rerun()
            with col_root:
                if st.button(f"🌱 Сделать корнем: {sp_name}", key="sb_sp_as_root"):
                    st.session_state.root_id         = sp_drill_id
                    st.session_state.sb_spouse_id    = None
                    st.session_state.sb_came_from_id = None
                    st.rerun()

            depth_sp = st.slider("Глубина ветки", 1, 8, 5, key="sp_depth")

            try:
                fig_sp, anc_name = build_sunburst_spouse_view(
                    df, sp_drill_id, cf_drill_id,
                    father_of, mother_of,
                    children_of, spouse_of,
                    desc_count, depth_sp,
                )
                if anc_name and anc_name != sp_drill_id:
                    st.caption(f"Корневой предок ветки: **{anc_name}**")
                st.plotly_chart(fig_sp, use_container_width=True)
            except Exception as _e:
                import traceback as _tb
                st.error(f"Ошибка при построении ветки: {_e}")
                st.code(_tb.format_exc())

    # ════════════════════════════════════════════════════════════════════════════
    # СЕТЕВОЙ ГРАФ
    # ════════════════════════════════════════════════════════════════════════════
    with tab_net:
        col_graph, col_info = st.columns([3, 1])

        with col_info:
            depth_net = st.slider("Глубина", 1, 6, min(depth_global, 4), key="net_d")
            st.markdown("---")

            # Карточка текущей персоны
            if not root_row.empty:
                r = root_row.iloc[0]
                st.markdown(f"**{r['name']}**")
                if pd.notna(r["birth_year"]):
                    st.markdown(f"Рождение: {int(r['birth_year'])}")
                if pd.notna(r["death_year"]):
                    st.markdown(f"Смерть: {int(r['death_year'])}")
                fam = r.get("family", "")
                if fam:
                    st.markdown(f"Ветка: {fam}")
                st.markdown(f"Потомков: {desc_count.get(root_id, 0)}")

                sp_id = spouse_of.get(root_id, "")
                if sp_id and sp_id in valid:
                    sp_name = id_to_name.get(sp_id, sp_id)
                    if st.button(f"💍 {sp_name}", key="goto_sp"):
                        st.session_state.root_id = sp_id
                        st.rerun()

                fid = father_of.get(root_id, "")
                mid = mother_of.get(root_id, "")
                if fid and fid in valid:
                    if st.button(f"👨 {id_to_name.get(fid, fid)}", key="goto_f"):
                        st.session_state.root_id = fid
                        st.rerun()
                if mid and mid in valid:
                    if st.button(f"👩 {id_to_name.get(mid, mid)}", key="goto_m"):
                        st.session_state.root_id = mid
                        st.rerun()

                ch = [c for c in children_of.get(root_id, []) if c in valid]
                if sp_id:
                    ch += [c for c in children_of.get(sp_id, [])
                           if c in valid and c not in ch]
                if ch:
                    st.markdown(f"**Дети ({len(ch)}):**")
                    for cid in ch[:6]:
                        if st.button(id_to_name.get(cid, cid), key=f"gc_{cid}"):
                            st.session_state.root_id = cid
                            st.rerun()

        with col_graph:
            st.caption(
                "Клик по узлу → новый корень. "
                "Серые линии — родитель→ребёнок, оранжевый пунктир — брак."
            )
            fig_net = build_network_figure(
                df, root_id, father_of, mother_of, spouse_of, children_of,
                desc_count, depth_net,
            )
            event = st.plotly_chart(
                fig_net, use_container_width=True,
                on_select="rerun", key="net_chart",
            )

        if event and hasattr(event, "selection"):
            pts = getattr(event.selection, "points", [])
            if pts:
                clicked = pts[0].get("customdata") if isinstance(pts[0], dict) else None
                if clicked and clicked in valid and clicked != root_id:
                    st.session_state.root_id = clicked
                    st.rerun()

    # ════════════════════════════════════════════════════════════════════════════
    # GRAPHVIZ
    # ════════════════════════════════════════════════════════════════════════════
    with tab_gv:
        st.caption(
            "Классическая схема: супруги на одном уровне, "
            "дети через невидимый junction-узел."
        )
        depth_gv = st.slider("Глубина", 1, 5, min(depth_global, 3), key="gv_d")

        dot_code = build_graphviz_dot(
            df, root_id, father_of, mother_of, spouse_of, children_of, depth_gv
        )
        try:
            st.graphviz_chart(dot_code, use_container_width=True)
        except Exception as e:
            st.error(f"Graphviz недоступен: {e}")
            st.info("Установите: `sudo apt-get install graphviz`")

        with st.expander("🔎 DOT-код"):
            st.code(dot_code, language="dot")

    # ════════════════════════════════════════════════════════════════════════════
    # TREEMAP — верификация структуры
    # ════════════════════════════════════════════════════════════════════════════
    with tab_tm:
        st.markdown("#### Пошаговая проверка структуры")
        st.caption("Используйте для проверки порядка поколений.")

        depth_tm = st.slider("Глубина", 0, 8, 2, key="tm_d",
                              help="0 = только корень, 1 = +дети, 2 = +внуки …")

        fig_tm = build_treemap(df, root_id, children_of, desc_count, depth_tm)
        st.plotly_chart(fig_tm, use_container_width=True)

        # Таблица текущего поколения
        depths_tm  = compute_depth_from(root_id, children_of)
        cur_level  = [
            {
                "Имя":     row["name"],
                "Пол":     "М" if row["gender"] == "M" else "Ж",
                "Ветка":   row.get("family", ""),
                "Отец":    id_to_name.get(row["father_id"], "—") if row["father_id"] else "—",
                "Мать":    id_to_name.get(row["mother_id"], "—") if row["mother_id"] else "—",
                "Рождение": int(row["birth_year"]) if pd.notna(row["birth_year"]) else "—",
                "Место":   row.get("location", "") or "—",
            }
            for _, row in df.iterrows()
            if depths_tm.get(row["id"], -1) == depth_tm
        ]
        st.markdown(f"**Поколение {depth_tm}** — персон: {len(cur_level)}")
        if cur_level:
            st.dataframe(pd.DataFrame(cur_level), use_container_width=True,
                         hide_index=True)

    # ════════════════════════════════════════════════════════════════════════════
    # ТАБЛИЦА
    # ════════════════════════════════════════════════════════════════════════════
    with tab_tbl:
        depths_all = compute_depth_from("root_T", children_of)

        family_filter = st.selectbox(
            "Фильтр по ветке",
            ["Все"] + sorted(df["family"].unique().tolist()),
            key="tbl_fam",
        )
        search_tbl = st.text_input("🔍 Поиск", key="tbl_s",
                                   placeholder="имя, место, примечание …")

        rows = []
        for _, row in df.iterrows():
            fam = row.get("family", "")
            if family_filter != "Все" and fam != family_filter:
                continue
            by = row["birth_year"]
            dy = row["death_year"]
            rows.append({
                "Имя":        row["name"],
                "Пол":        "М" if row["gender"] == "M" else "Ж",
                "Пок.":       depths_all.get(row["id"], "—"),
                "Ветка":      fam,
                "Рождение":   int(by) if pd.notna(by) else "—",
                "Смерть":     int(dy) if pd.notna(dy) else "—",
                "Отец":       id_to_name.get(row["father_id"], "—") if row["father_id"] else "—",
                "Мать":       id_to_name.get(row["mother_id"], "—") if row["mother_id"] else "—",
                "Супруг/а":   id_to_name.get(row["spouse_id"], "—") if row["spouse_id"] else "—",
                "Место":      row.get("location", "") or "—",
                "Потомков":   desc_count.get(row["id"], 0),
                "Примечание": row.get("notes", "") or "—",
            })

        tbl_df = pd.DataFrame(rows)
        if search_tbl.strip():
            mask = tbl_df.apply(
                lambda col: col.astype(str).str.contains(search_tbl.strip(), case=False)
            ).any(axis=1)
            tbl_df = tbl_df[mask]

        st.dataframe(
            tbl_df.sort_values(["Пок.", "Имя"]),
            use_container_width=True, hide_index=True,
        )
        st.caption(f"Показано строк: {len(tbl_df)}")

    # ════════════════════════════════════════════════════════════════════════════
    # СТАТИСТИКА
    # ════════════════════════════════════════════════════════════════════════════
    with tab_stat:
        depths_for_stat = compute_depth_from("root_T", children_of)

        col_a, col_b = st.columns(2)

        with col_a:
            # Распределение по полу
            st.subheader("По полу")
            gender_data = df["gender"].value_counts()
            fig_g = go.Figure(go.Pie(
                labels=["Мужчины", "Женщины"],
                values=[gender_data.get("M", 0), gender_data.get("F", 0)],
                marker_colors=[C_M, C_F],
                textfont=dict(size=14),
            ))
            fig_g.update_layout(paper_bgcolor=BG, font=dict(color="white"), height=300,
                                margin=dict(t=10,b=10,l=10,r=10))
            st.plotly_chart(fig_g, use_container_width=True)

        with col_b:
            # Распределение по ветке
            st.subheader("По ветке")
            fam_counts = df["family"].replace("", "Другие").value_counts()
            fig_f = go.Figure(go.Pie(
                labels=fam_counts.index.tolist(),
                values=fam_counts.values.tolist(),
                textfont=dict(size=13),
            ))
            fig_f.update_layout(paper_bgcolor=BG, font=dict(color="white"), height=300,
                                margin=dict(t=10,b=10,l=10,r=10))
            st.plotly_chart(fig_f, use_container_width=True)

        # Распределение по поколениям (от root_T)
        st.subheader("Распределение по поколениям (от Тимофеева 1800)")
        gen_rows = []
        for _, row in df.iterrows():
            d = depths_for_stat.get(row["id"])
            if d is None:
                continue
            gen_rows.append({"Поколение": d, "Пол": row["gender"]})
        if gen_rows:
            gen_df = (
                pd.DataFrame(gen_rows)
                .groupby(["Поколение", "Пол"]).size()
                .reset_index(name="Кол-во")
                .pivot(index="Поколение", columns="Пол", values="Кол-во")
                .fillna(0)
            )
            gen_df.columns = [("Мужчин" if c=="M" else "Женщин") for c in gen_df.columns]
            st.bar_chart(gen_df)

        # Топ по числу потомков
        st.subheader("Топ 15 по числу потомков")
        top_rows = [
            {"Имя": row["name"],
             "Пок.": depths_for_stat.get(row["id"], "?"),
             "Ветка": row.get("family", ""),
             "Потомков": desc_count.get(row["id"], 0)}
            for _, row in df.iterrows()
            if desc_count.get(row["id"], 0) > 0
        ]
        if top_rows:
            st.dataframe(
                pd.DataFrame(top_rows)
                .sort_values("Потомков", ascending=False)
                .head(15),
                use_container_width=True, hide_index=True,
            )

        # Хронология рождений
        st.subheader("Хронология рождений")
        birth_df = df[df["birth_year"].notna()][
            ["name","birth_year","gender","family"]
        ].copy()
        birth_df["birth_year"] = birth_df["birth_year"].astype(int)
        if not birth_df.empty:
            st.dataframe(
                birth_df.sort_values("birth_year")
                .rename(columns={"name":"Имя","birth_year":"Год","gender":"Пол","family":"Ветка"}),
                use_container_width=True, hide_index=True,
            )


if __name__ == "__main__":
    main()
