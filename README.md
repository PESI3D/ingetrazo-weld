# Weld — join edges into curves for IngeTrazo

Joins loose edges into **one curve** that selects with a single click — like a circle or an arc — and closes small gaps on the way. Handy for imported plans (DXF/DWG/PDF) whose outlines arrive as hundreds of single segments.

[Deutsch → LIESMICH.md](LIESMICH.md)

![Weld](screenshot.webp)

## Installation
1. In IngeTrazo: **Extensions ▸ Open plugins folder** (Windows: `%APPDATA%\ingetrazo\plugins\`, Linux: `~/.local/share/ingetrazo/plugins/`).
2. Copy `weld_tool.py` into that folder.
3. Restart IngeTrazo → **Extensions ▸ Weld ▸** *Weld Edges… · Unweld Edges* (also on the right-click menu when edges are selected).

Requires IngeTrazo ≥ 0.5 (extension API 2).

## How to use
Select the edges and run **Weld Edges…**. Every unbroken chain becomes one curve; the preview shows each future curve in its own colour and every gap that will close in red.

- **Close gaps up to** — joins open ends closer than this distance (document unit). Two free ends meet in the middle; a free end next to attached geometry moves onto it. Faces are never moved.
- **Remove collinear points** — drops the extra vertices of straight runs (only where no face uses them).
- A chain stops at junctions (three or more edges) and where other, unselected geometry is attached — the same rule IngeTrazo uses for its own curves, so the result stays stable.
- **Unweld Edges** turns selected curves back into single edges.
- One undo step per command. The dialog does not block the viewport (orbit, pan, zoom).

## Changelog
- **1.1** — own toolbar **Weld** with one icon per command (Weld Edges… · Unweld Edges). It starts on a row of its own under the built-in toolbars; move, float or hide it like those (right-click on a toolbar). Icons drawn in IngeTrazo's own style, they follow the light/dark theme.
- **1.0** — first release.

## Licence
GPL-3.0-or-later · © 2026 Pesi (pesi3d.de) · [Impressum](https://pesi3d.de)
