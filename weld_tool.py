# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Peter Müller (PESI3D) — https://pesi3d.de
"""Weld — join loose edges into one curve, and close small gaps.

Select edges (lines drawn one by one, an imported polyline that arrived as
single segments) and run Extensions ▸ Weld ▸ Weld Edges…, or right-click ▸
Weld Edges…. Every unbroken chain of selected edges becomes ONE curve: a
click with Select picks the whole chain, as with a circle or an arc.

- A chain stops at a junction (three or more edges meet) or where other,
  unselected geometry is attached — the same rule IngeTrazo uses to split
  its own curves, so the result stays stable.
- «Close gaps up to» joins open ends that lie closer than the tolerance:
  two free ends meet in the middle, a free end next to attached geometry
  moves onto it. Faces are never moved.
- «Remove collinear points» drops the extra vertices of straight runs
  (only where no face uses them).
- Extensions ▸ Weld ▸ Unweld Edges turns the selected curves back into
  single edges.

One undo step per command. The dialog is non-modal: orbit, pan and zoom
while the preview shows each future curve in its own colour and every gap
that will close in red.
"""
from __future__ import annotations

import math

KEY = "weld_tool"
VERSION = "1.0"

_TEXTS = {
    "de": {
        "Weld": "Verschweißen",
        "Weld Edges…": "Kanten verschweißen…",
        "Unweld Edges": "Verschweißung lösen",
        "Join the selected edges into curves that select as one.":
            "Verbindet die gewählten Kanten zu Kurven, die sich als Ganzes auswählen.",
        "Split the selected curves back into single edges.":
            "Zerlegt die gewählten Kurven wieder in einzelne Kanten.",
        "Select the edges to weld first.": "Zuerst die Kanten zum Verschweißen auswählen.",
        "Select a welded curve first.": "Zuerst eine verschweißte Kurve auswählen.",
        "Selection": "Auswahl",
        "{n} edges": "{n} Kanten",
        "{n} curve(s), {c} closed": "{n} Kurve(n), davon {c} geschlossen",
        "Close gaps up to": "Lücken schließen bis",
        "{n} gap(s) will close": "{n} Lücke(n) werden geschlossen",
        "{n} gap(s) between attached ends — left open":
            "{n} Lücke(n) zwischen angebundenen Enden — bleiben offen",
        "Remove collinear points": "Kollineare Punkte entfernen",
        "Preview": "Vorschau",
        "Cancel": "Abbrechen",
        "Welded: {n} curve(s), {g} gap(s) closed, {p} point(s) removed":
            "Verschweißt: {n} Kurve(n), {g} Lücke(n) geschlossen, {p} Punkt(e) entfernt",
        "Unwelded {n} edge(s)": "{n} Kante(n) gelöst",
        "Nothing to weld: every chain is a single edge.":
            "Nichts zu verschweißen: jede Kette besteht aus nur einer Kante.",
        "The selection changed — nothing left to weld.":
            "Die Auswahl hat sich geändert — nichts mehr zu verschweißen.",
    },
    "es": {
        "Weld": "Soldar",
        "Weld Edges…": "Soldar aristas…",
        "Unweld Edges": "Separar soldadura",
        "Join the selected edges into curves that select as one.":
            "Une las aristas seleccionadas en curvas que se seleccionan como una.",
        "Split the selected curves back into single edges.":
            "Vuelve a separar las curvas seleccionadas en aristas sueltas.",
        "Select the edges to weld first.": "Primero seleccione las aristas a soldar.",
        "Select a welded curve first.": "Primero seleccione una curva soldada.",
        "Selection": "Selección",
        "{n} edges": "{n} aristas",
        "{n} curve(s), {c} closed": "{n} curva(s), {c} cerrada(s)",
        "Close gaps up to": "Cerrar huecos hasta",
        "{n} gap(s) will close": "Se cerrarán {n} hueco(s)",
        "{n} gap(s) between attached ends — left open":
            "{n} hueco(s) entre extremos unidos — quedan abiertos",
        "Remove collinear points": "Quitar puntos colineales",
        "Preview": "Vista previa",
        "Cancel": "Cancelar",
        "Welded: {n} curve(s), {g} gap(s) closed, {p} point(s) removed":
            "Soldado: {n} curva(s), {g} hueco(s) cerrados, {p} punto(s) quitados",
        "Unwelded {n} edge(s)": "{n} arista(s) separadas",
        "Nothing to weld: every chain is a single edge.":
            "Nada que soldar: cada cadena es una sola arista.",
        "The selection changed — nothing left to weld.":
            "La selección cambió: no queda nada que soldar.",
    },
}

#: Straight-run test for «Remove collinear points»: 0.1°.
_COLLINEAR_COS = math.cos(math.radians(0.1))

_PREVIEW_COLOURS = ((0, 150, 255), (0, 190, 90), (230, 140, 0),
                    (170, 70, 220), (0, 180, 180), (220, 60, 140))


def _tr(text: str, **kw) -> str:
    """``text`` in the interface language, with ``{n}``-style fields."""
    try:
        from core.i18n import current_language
        lang = current_language()
    except Exception:  # noqa: BLE001
        lang = "en"
    out = _TEXTS.get(lang, {}).get(text, text)
    return out.format(**kw) if kw else out


# ---------------------------------------------------------------------------
# 1. Topology — chains, gaps, collinear points. Works on IngeTrazo's Mesh
#    (shared Vertex objects, Edge.v0/v1, Edge.faces, Edge.curve).
# ---------------------------------------------------------------------------

def selected_edges(scene) -> list:
    """The selected edges of the mesh being edited (loose or open group)."""
    from core.mesh import Edge
    live = set(scene.mesh.edges)
    return [e for e in scene.selection if isinstance(e, Edge) and e in live]


def build_chains(edges) -> list:
    """Unbroken chains of ``edges``: ``[(edge_list, vertex_list, closed)]``.

    A chain breaks at a vertex where its own edges do not continue as a
    simple path (selected degree ≠ 2) or where other geometry is attached —
    the rule of ``Mesh.resplit_curves``, so a welded curve is never split
    again by the core."""
    eset = set(edges)

    def sel_deg(v):
        return sum(1 for e in v.edges if e in eset)

    def is_break(v):
        d = sel_deg(v)
        return d != 2 or len(v.edges) != d

    unvisited = set(edges)
    order = list(edges)
    seeds = [e for e in order if is_break(e.v0) or is_break(e.v1)]
    chains = []
    for seed in seeds + order:
        if seed not in unvisited:
            continue
        start = seed.v0 if is_break(seed.v0) else (
            seed.v1 if is_break(seed.v1) else seed.v0)
        chain, verts, v, e = [], [start], start, seed
        while e in unvisited:
            unvisited.discard(e)
            chain.append(e)
            v = e.other(v)
            verts.append(v)
            if is_break(v):
                break
            nxt = next((n for n in v.edges if n in unvisited), None)
            if nxt is None:
                break
            e = nxt
        closed = len(chain) > 2 and verts[-1] is verts[0]
        chains.append((chain, verts, closed))
    return chains


def find_gaps(edges, tol: float):
    """Pairs of open chain ends closer than ``tol``: ``(pairs, blocked)``.

    ``pairs`` = ``[(keep, move, target_position)]``; ``blocked`` counts the
    gaps whose two ends both carry other geometry (not moved). Greedy,
    shortest gap first; each end joins once. The two ends of one chain
    join only when that closes a loop of three or more edges."""
    if tol <= 0:
        return [], 0
    eset = set(edges)
    ends = [v for v in {x for e in edges for x in (e.v0, e.v1)}
            if sum(1 for e in v.edges if e in eset) == 1]
    if len(ends) < 2:
        return [], 0

    # Which connected piece of the selection each vertex is on, and its size.
    adj = {}
    for e in edges:
        adj.setdefault(e.v0, []).append(e)
        adj.setdefault(e.v1, []).append(e)
    comp, size = {}, {}
    for v0 in adj:
        if v0 in comp:
            continue
        cid, stack, seen_e = len(size), [v0], set()
        comp[v0] = cid
        while stack:
            v = stack.pop()
            for e in adj[v]:
                seen_e.add(e)
                w = e.other(v)
                if w not in comp:
                    comp[w] = cid
                    stack.append(w)
        size[cid] = len(seen_e)

    tol2 = tol * tol
    cand = []
    pts = [(v, v.position) for v in ends]
    for i in range(len(pts)):
        vi, pi = pts[i]
        for j in range(i + 1, len(pts)):
            vj, pj = pts[j]
            d2 = (pi - pj).lengthSquared()
            if d2 > tol2:
                continue
            if comp[vi] == comp[vj] and size[comp[vi]] < 3:
                continue
            cand.append((d2, i, j))
    cand.sort(key=lambda t: t[0])
    used, pairs, blocked = set(), [], 0
    for _d2, i, j in cand:
        if i in used or j in used:
            continue
        vi, vj = pts[i][0], pts[j][0]
        free_i, free_j = len(vi.edges) == 1, len(vj.edges) == 1
        if free_i and free_j:
            target = (vi.position + vj.position) * 0.5
            keep, move = vi, vj
        elif free_j:
            keep, move, target = vi, vj, vi.position
        elif free_i:
            keep, move, target = vj, vi, vj.position
        else:
            blocked += 1
            continue
        # A free end has one edge, which borders no face (a face edge's
        # vertices always carry two or more edges): moving it bends no face.
        used.update((i, j))
        pairs.append((keep, move, target))
    return pairs, blocked


def _collinear_inner_vertices(chains) -> list:
    """Interior chain vertices on a straight run, used by no face."""
    out = []
    for _chain, verts, closed in chains:
        inner = verts[:-1] if closed else verts[1:-1]
        for v in inner:
            if len(v.edges) != 2:
                continue
            e1, e2 = list(v.edges)
            if e1.faces or e2.faces:
                continue
            a, b = e1.other(v), e2.other(v)
            d1, d2 = v.position - a.position, b.position - v.position
            if d1.length() < 1e-6 or d2.length() < 1e-6:
                continue
            if (d1.normalized().x() * d2.normalized().x()
                    + d1.normalized().y() * d2.normalized().y()
                    + d1.normalized().z() * d2.normalized().z()) >= _COLLINEAR_COS:
                out.append(v)
    return out


def weld(mesh, edges, tol: float = 0.0, collinear: bool = False) -> dict:
    """Weld ``edges`` of ``mesh`` in place (run it under an undo snapshot).

    Returns ``{"curves", "gaps", "points", "edges"}`` — the new curves,
    closed gaps, removed points and the resulting edge list (to select)."""
    from PySide6.QtGui import QVector3D

    edges = [e for e in edges if e in set(mesh.edges)]
    # 1. Close the gaps: move the end(s) together, then merge the vertices.
    #    The selection is tracked by vertex pairs, since a merge re-links
    #    the moved end's edge onto the kept vertex.
    pairs, _blocked = find_gaps(edges, tol)
    vpairs = [(e.v0, e.v1) for e in edges]
    alias = {}

    def res(v):
        while v in alias:
            v = alias[v]
        return v

    gaps = 0
    for keep, move, target in pairs:
        keep, move = res(keep), res(move)
        if keep is move or keep not in mesh.vertices or move not in mesh.vertices:
            continue
        mesh.place_vertex(keep, QVector3D(*target.toTuple()))
        mesh.place_vertex(move, QVector3D(*target.toTuple()))
        if hasattr(mesh, "_weld_into"):
            mesh._weld_into(keep, move)
        else:  # pragma: no cover - older cores
            mesh.weld_coincident()
        alias[move] = keep
        gaps += 1
    if gaps:
        out = []
        for a, b in vpairs:
            a, b = res(a), res(b)
            e = mesh.find_edge(a, b) if a is not b else None
            if e is not None and e not in out:
                out.append(e)
        edges = out

    # 2. Optionally drop the extra points of straight runs.
    points = 0
    if collinear:
        for v in _collinear_inner_vertices(build_chains(edges)):
            if v not in mesh.vertices or len(v.edges) != 2:
                continue
            e1, e2 = list(v.edges)
            n1, n2 = e1.other(v), e2.other(v)
            if n1 is n2 or mesh.find_edge(n1, n2) is not None:
                continue
            layer = e1.layer
            rec = mesh.collapse_vertex(v)
            ne = rec["new_edge"]
            ne.layer = layer
            edges = [e for e in edges if e is not e1 and e is not e2] + [ne]
            points += 1

    # 3. One curve id per chain of two or more edges.
    from core.mesh import Mesh
    curves = 0
    for chain, _verts, _closed in build_chains(edges):
        if len(chain) < 2:
            continue
        cid = Mesh.next_curve_id()
        for e in chain:
            e.curve = cid
        curves += 1
    if hasattr(mesh, "_chunk_dirty"):
        mesh._chunk_dirty = True
    if hasattr(mesh, "_mut_serial"):
        mesh._mut_serial += 1
    return {"curves": curves, "gaps": gaps, "points": points, "edges": edges}


def unweld(mesh, edges) -> int:
    """Clear the curve id of ``edges``; returns how many changed."""
    n = 0
    for e in edges:
        if getattr(e, "curve", None) is not None:
            e.curve = None
            n += 1
    if n and hasattr(mesh, "_chunk_dirty"):
        mesh._chunk_dirty = True
        mesh._mut_serial += 1
    return n


# ---------------------------------------------------------------------------
# 2. Commands — one undo step each.
# ---------------------------------------------------------------------------

def _run(viewport, mutate):
    from core.history import SnapshotImport
    viewport.history.execute(SnapshotImport(mutate))
    viewport.notify_scene_changed()
    viewport.update()


def run_weld(viewport, edges, tol=0.0, collinear=False) -> dict | None:
    scene = viewport.scene
    live = set(scene.mesh.edges)
    edges = [e for e in edges if e in live]
    if not edges:
        viewport.flash_status(_tr("The selection changed — nothing left to weld."), 4000)
        return None
    result = {}

    def mutate(sc):
        result.update(weld(sc.mesh, edges, tol, collinear))

    _run(viewport, mutate)
    if not result.get("curves") and not result.get("gaps"):
        viewport.flash_status(_tr("Nothing to weld: every chain is a single edge."), 4000)
    else:
        viewport.flash_status(_tr(
            "Welded: {n} curve(s), {g} gap(s) closed, {p} point(s) removed",
            n=result["curves"], g=result["gaps"], p=result["points"]), 5000)
    try:
        scene.select([e for e in result.get("edges", []) if e in set(scene.mesh.edges)])
    except Exception:  # noqa: BLE001
        pass
    viewport.update()
    return result


def run_unweld(viewport) -> None:
    edges = [e for e in selected_edges(viewport.scene)
             if getattr(e, "curve", None) is not None]
    if not edges:
        viewport.flash_status(_tr("Select a welded curve first."), 4000)
        return
    count = {"n": 0}

    def mutate(sc):
        count["n"] = unweld(sc.mesh, edges)

    _run(viewport, mutate)
    viewport.flash_status(_tr("Unwelded {n} edge(s)", n=count["n"]), 4000)


# ---------------------------------------------------------------------------
# 3. Dialog (non-modal) + preview overlay.
# ---------------------------------------------------------------------------

_STATE = {"dialog": None, "preview": None}


def _unit_scale_and_label():
    """Metres per displayed unit and its label, from the document."""
    try:
        from core import units
        code = units.model_unit()
        scale = units._BARE_SCALE.get(code, 1.0)
        return scale, code
    except Exception:  # noqa: BLE001
        return 1.0, "m"


def _draw_preview(viewport, painter) -> None:
    data = _STATE.get("preview")
    if not data or _STATE.get("dialog") is None:
        return
    import numpy as np
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QPen

    for idx, poly in enumerate(data["chains"]):
        if len(poly) < 2:
            continue
        arr = np.array(poly, dtype=float)
        px, py, front = viewport.world_to_pixels(arr)
        r, g, b = _PREVIEW_COLOURS[idx % len(_PREVIEW_COLOURS)]
        pen = QPen(QColor(r, g, b, 220), 4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        for i in range(len(poly) - 1):
            if front[i] and front[i + 1]:
                painter.drawLine(QPointF(px[i], py[i]), QPointF(px[i + 1], py[i + 1]))
    if data["gaps"]:
        arr = np.array([p for pair in data["gaps"] for p in pair], dtype=float)
        px, py, front = viewport.world_to_pixels(arr)
        pen = QPen(QColor(230, 30, 30), 2, Qt.DashLine)
        painter.setPen(pen)
        for k in range(0, len(arr), 2):
            if front[k] and front[k + 1]:
                a, b = QPointF(px[k], py[k]), QPointF(px[k + 1], py[k + 1])
                painter.drawLine(a, b)
                painter.drawEllipse(a, 5, 5)
                painter.drawEllipse(b, 5, 5)


def open_dialog(viewport) -> None:
    from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                   QDoubleSpinBox, QFormLayout, QHBoxLayout,
                                   QLabel, QVBoxLayout)

    edges = selected_edges(viewport.scene)
    if not edges:
        viewport.flash_status(_tr("Select the edges to weld first."), 4000)
        return
    old = _STATE.get("dialog")
    if old is not None:
        old.close()

    scale, unit = _unit_scale_and_label()
    dlg = QDialog(viewport.window())
    dlg.setWindowTitle(f"{_tr('Weld')} {VERSION}")
    dlg.setModal(False)
    lay = QVBoxLayout(dlg)
    form = QFormLayout()
    info = QLabel()
    form.addRow(_tr("Selection"), info)

    gap_row = QHBoxLayout()
    gap_on = QCheckBox(_tr("Close gaps up to"))
    gap_val = QDoubleSpinBox()
    gap_val.setDecimals(4 if scale >= 1.0 else 2)
    gap_val.setRange(0.0, 1e6)
    gap_val.setSuffix(f" {unit}")
    gap_row.addWidget(gap_on)
    gap_row.addWidget(gap_val, 1)
    form.addRow(gap_row)
    gap_info = QLabel()
    form.addRow("", gap_info)
    collinear = QCheckBox(_tr("Remove collinear points"))
    form.addRow(collinear)
    preview = QCheckBox(_tr("Preview"))
    form.addRow(preview)
    lay.addLayout(form)
    btns = QDialogButtonBox()
    ok = btns.addButton(_tr("Weld"), QDialogButtonBox.AcceptRole)
    btns.addButton(_tr("Cancel"), QDialogButtonBox.RejectRole)
    lay.addWidget(btns)

    # Remembered settings.
    from PySide6.QtCore import QSettings
    st = QSettings()
    gap_on.setChecked(st.value(f"plugins/{KEY}/gaps", True, type=bool))
    tol_m = float(st.value(f"plugins/{KEY}/tol_m", 0.01))
    gap_val.setValue(tol_m / scale)
    collinear.setChecked(st.value(f"plugins/{KEY}/collinear", False, type=bool))
    preview.setChecked(st.value(f"plugins/{KEY}/preview", True, type=bool))

    def tol() -> float:
        return gap_val.value() * scale if gap_on.isChecked() else 0.0

    def refresh(*_a):
        live = set(viewport.scene.mesh.edges)
        cur = [e for e in edges if e in live]
        chains = build_chains(cur)
        pairs, blocked = find_gaps(cur, tol())
        n_curves = sum(1 for c in chains if len(c[0]) >= 2)
        n_closed = sum(1 for c in chains if c[2])
        info.setText(_tr("{n} edges", n=len(cur)) + " · "
                     + _tr("{n} curve(s), {c} closed", n=n_curves, c=n_closed))
        txt = _tr("{n} gap(s) will close", n=len(pairs)) if gap_on.isChecked() else ""
        if blocked:
            txt += "\n" + _tr("{n} gap(s) between attached ends — left open", n=blocked)
        gap_info.setText(txt)
        gap_val.setEnabled(gap_on.isChecked())
        if preview.isChecked():
            _STATE["preview"] = {
                "chains": [[v.position.toTuple() for v in c[1]] for c in chains],
                "gaps": [(m.position.toTuple(), k.position.toTuple())
                         for k, m, _t in pairs],
            }
        else:
            _STATE["preview"] = None
        viewport.update()

    def save_settings():
        st.setValue(f"plugins/{KEY}/gaps", gap_on.isChecked())
        st.setValue(f"plugins/{KEY}/tol_m", gap_val.value() * scale)
        st.setValue(f"plugins/{KEY}/collinear", collinear.isChecked())
        st.setValue(f"plugins/{KEY}/preview", preview.isChecked())

    def on_ok():
        save_settings()
        t, c = tol(), collinear.isChecked()
        _STATE["preview"] = None
        dlg.close()
        run_weld(viewport, edges, t, c)

    def on_finished(*_a):
        _STATE["preview"] = None
        _STATE["dialog"] = None
        try:
            viewport.update()
        except RuntimeError:  # the window is already gone (app closing)
            pass

    for w in (gap_on, collinear, preview):
        w.toggled.connect(refresh)
    gap_val.valueChanged.connect(refresh)
    ok.clicked.connect(on_ok)
    btns.rejected.connect(dlg.close)
    dlg.finished.connect(on_finished)
    dlg.destroyed.connect(on_finished)

    _STATE["dialog"] = dlg
    refresh()
    dlg.show()
    dlg.raise_()


# ---------------------------------------------------------------------------
# 4. Registration.
# ---------------------------------------------------------------------------

def setup(app) -> None:
    """Extensions ▸ Weld ▸ Weld Edges… / Unweld Edges, and the same entries
    in the viewport's right-click menu when edges are selected."""
    from PySide6.QtCore import QTimer

    sub = app.add_menu(_tr("Weld"))
    if sub is not None:
        a = sub.addAction(_tr("Weld Edges…"))
        a.setStatusTip(_tr("Join the selected edges into curves that select as one."))
        a.triggered.connect(lambda _c=False: open_dialog(app.viewport))
        b = sub.addAction(_tr("Unweld Edges"))
        b.setStatusTip(_tr("Split the selected curves back into single edges."))
        b.triggered.connect(lambda _c=False: run_unweld(app.viewport))
    else:  # pragma: no cover - no Extensions menu
        app.add_menu_action(_tr("Weld Edges…"), lambda: open_dialog(app.viewport),
                            tip=_tr("Join the selected edges into curves that select as one."))

    def context(menu, selection) -> None:
        edges = selected_edges(app.viewport.scene)
        if not edges:
            return
        menu.addSeparator()
        act = menu.addAction(_tr("Weld Edges…"))
        act.triggered.connect(
            lambda _c=False: QTimer.singleShot(0, lambda: open_dialog(app.viewport)))
        if any(getattr(e, "curve", None) is not None for e in edges):
            act2 = menu.addAction(_tr("Unweld Edges"))
            act2.triggered.connect(
                lambda _c=False: QTimer.singleShot(0, lambda: run_unweld(app.viewport)))

    app.add_context_menu(context)
    app.add_overlay(_draw_preview)
