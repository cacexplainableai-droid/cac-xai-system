"""Tiny SVG chart helpers. Charts are drawn by the server, so the system works with NO internet connection."""
from html import escape
from markupsafe import Markup

COLORS = ["#1f2a5a", "#b8892b", "#2e7d6b", "#a23b3b", "#6a5acd"]


def _nice_max(v):
    if v <= 0: return 1
    import math
    p = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        if v <= m * p: return m * p


def line_chart(labels, series, width=760, height=290, money=False, forecast_from=None):
    """series = [(name, values, color_or_None)]"""
    L, R, T, B = 62, 14, 16, 58
    w, h = width - L - R, height - T - B
    allv = [v for _, vals, _ in series for v in vals if v is not None]
    ymax = _nice_max(max(allv) * 1.05) if allv else 1
    n = max(len(labels) - 1, 1)
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    for i in range(5):
        y = T + h - h * i / 4
        val = ymax * i / 4
        out.append(f'<line x1="{L}" x2="{width-R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{L-6}" y="{y+4:.1f}" class="axis" text-anchor="end">{val:,.0f}</text>')
    step = max(1, len(labels) // 8)
    for i, lab in enumerate(labels):
        if i % step == 0:
            x = L + w * i / n
            out.append(f'<text x="{x:.1f}" y="{height-B+16}" class="axis" text-anchor="middle">{escape(str(lab))}</text>')
    if forecast_from is not None and forecast_from < len(labels):
        x0 = L + w * forecast_from / n
        out.append(f'<rect x="{x0:.1f}" y="{T}" width="{width-R-x0:.1f}" height="{h}" class="forecast-zone"/>')
        out.append(f'<text x="{x0+6:.1f}" y="{T+14}" class="axis">Forecast</text>')
    for k, (name, vals, col) in enumerate(series):
        col = col or COLORS[k % len(COLORS)]
        pts = [(L + w * i / n, T + h - h * v / ymax) for i, v in enumerate(vals) if v is not None]
        if pts:
            out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.2" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}"/>')
    lx = L
    for k, (name, vals, col) in enumerate(series):
        col = col or COLORS[k % len(COLORS)]
        out.append(f'<rect x="{lx}" y="{height-16}" width="12" height="12" fill="{col}"/><text x="{lx+17}" y="{height-6}" class="axis">{escape(name)}</text>')
        lx += 30 + 7 * len(name)
    out.append("</svg>")
    return Markup("".join(out))


def bar_chart(labels, groups, width=760, height=290, money=False):
    """groups = [(name, values)] -> grouped vertical bars"""
    L, R, T, B = 62, 14, 16, 58
    w, h = width - L - R, height - T - B
    ymax = _nice_max(max(v for _, vals in groups for v in vals) * 1.05) if groups and labels else 1
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    for i in range(5):
        y = T + h - h * i / 4
        out.append(f'<line x1="{L}" x2="{width-R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{L-6}" y="{y+4:.1f}" class="axis" text-anchor="end">{ymax*i/4:,.0f}</text>')
    gw = w / len(labels)
    bw = gw * 0.7 / len(groups)
    for i, lab in enumerate(labels):
        cx = L + gw * i
        out.append(f'<text x="{cx+gw/2:.1f}" y="{height-B+16}" class="axis" text-anchor="middle">{escape(str(lab))}</text>')
        for k, (name, vals) in enumerate(groups):
            bh = h * vals[i] / ymax
            out.append(f'<rect x="{cx+gw*0.15+bw*k:.1f}" y="{T+h-bh:.1f}" width="{bw-2:.1f}" height="{bh:.1f}" fill="{COLORS[k % len(COLORS)]}"><title>{escape(name)}: {vals[i]:,.0f}</title></rect>')
    lx = L
    for k, (name, _) in enumerate(groups):
        out.append(f'<rect x="{lx}" y="{height-16}" width="12" height="12" fill="{COLORS[k % len(COLORS)]}"/><text x="{lx+17}" y="{height-6}" class="axis">{escape(name)}</text>')
        lx += 30 + 7 * len(name)
    out.append("</svg>")
    return Markup("".join(out))


def contribution_chart(items, base_label="average", unit="", width=760, top=7):
    """Horizontal diverging bars: right (gold) pushes the result UP, left (red) pushes it DOWN."""
    items = items[:top]
    row, L, mid_w = 34, 300, 360
    height = row * len(items) + 40
    mx = max(abs(i["phi"]) for i in items) or 1
    cx = L + mid_w / 2
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">',
           f'<line x1="{cx}" x2="{cx}" y1="8" y2="{height-24}" class="zero"/>']
    for k, it in enumerate(items):
        y = 12 + k * row
        bw = (abs(it["phi"]) / mx) * (mid_w / 2 - 50)
        up = it["phi"] >= 0
        x = cx if up else cx - bw
        out.append(f'<text x="{L-10}" y="{y+16}" class="axis" text-anchor="end">{escape(it["label"][:50])}</text>')
        out.append(f'<rect x="{x:.1f}" y="{y}" width="{max(bw,1):.1f}" height="22" fill="{"#b8892b" if up else "#a23b3b"}"/>')
        tx = cx + bw + 6 if up else cx - bw - 6
        val = f'{it["phi"]:+,.3f}' if abs(it["phi"]) < 1 else f'{it["phi"]:+,.0f}'
        out.append(f'<text x="{tx:.1f}" y="{y+16}" class="axis" text-anchor="{"start" if up else "end"}">{val} {unit}</text>')
    out.append(f'<text x="{cx}" y="{height-6}" class="axis" text-anchor="middle">Gold = pushes the result up | Red = pushes it down</text>')
    out.append("</svg>")
    return Markup("".join(out))
