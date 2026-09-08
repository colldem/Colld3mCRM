"""Geometry for the inline SVG charts used by the analytics pages.

Everything is plain arithmetic returning coordinates — the templates only loop.
No chart library: the CRM runs on a closed network where a CDN would not load.
"""

# Series colours, drawn from the CRM palette.
SERIES_COLOURS = ("#062b63", "#2f6fbe", "#4f9ad8", "#168a45", "#d29a18", "#8b5cf6")

WIDTH = 900
HEIGHT = 210
PAD_LEFT = 36
PAD_RIGHT = 30
PAD_TOP = 10
PAD_BOTTOM = 28


def _nice_max(value):
    """Round an axis maximum up to something readable (1, 2, 5 × 10ⁿ)."""
    if value <= 0:
        return 1
    step = 1
    while step * 10 < value:
        step *= 10
    for factor in (1, 2, 5, 10):
        if step * factor >= value:
            return step * factor
    return step * 10


def _axis(top):
    """Horizontal gridlines with their labels, from 0 to `top`.

    Small maxima get one line per whole number so the labels never repeat.
    """
    plot_height = HEIGHT - PAD_TOP - PAD_BOTTOM
    steps = top if top <= 8 else 4
    return [{
        "value": int(round(top * index / steps)),
        "y": round(PAD_TOP + plot_height - plot_height * index / steps, 2),
    } for index in range(steps + 1)]


def stacked_bars(buckets, keys):
    """Stacked bars per bucket.

    `buckets` — [{"label": str, "values": {key: number}}]; `keys` — series order.
    """
    if not buckets:
        return None
    top = _nice_max(max((sum(b["values"].get(k, 0) for k in keys) for b in buckets), default=0))
    plot_height = HEIGHT - PAD_TOP - PAD_BOTTOM
    plot_width = WIDTH - PAD_LEFT - PAD_RIGHT
    slot = plot_width / len(buckets)
    bar_width = min(slot * 0.62, 34)
    bars, labels = [], []
    for index, bucket in enumerate(buckets):
        centre = PAD_LEFT + slot * (index + 0.5)
        bottom = PAD_TOP + plot_height
        for order, key in enumerate(keys):
            value = bucket["values"].get(key, 0)
            if not value:
                continue
            height = plot_height * value / top
            bottom -= height
            bars.append({"x": round(centre - bar_width / 2, 2), "y": round(bottom, 2),
                         "width": round(bar_width, 2), "height": round(height, 2),
                         "fill": SERIES_COLOURS[order % len(SERIES_COLOURS)],
                         "label": f'{bucket["label"]}: {value}'})
        labels.append({"x": round(centre, 2), "y": HEIGHT - 8, "text": bucket["label"]})
    return {"width": WIDTH, "height": HEIGHT, "bars": bars, "labels": labels,
            "axis": _axis(top), "x0": PAD_LEFT, "x1": WIDTH - PAD_RIGHT}


def line_series(buckets):
    """A single filled line. `buckets` — [{"label": str, "value": number}]."""
    if not buckets:
        return None
    top = _nice_max(max((b["value"] for b in buckets), default=0))
    plot_height = HEIGHT - PAD_TOP - PAD_BOTTOM
    plot_width = WIDTH - PAD_LEFT - PAD_RIGHT
    steps = max(len(buckets) - 1, 1)
    points, labels, dots = [], [], []
    for index, bucket in enumerate(buckets):
        x = PAD_LEFT + plot_width * index / steps
        y = PAD_TOP + plot_height - plot_height * bucket["value"] / top
        points.append(f"{x:.2f},{y:.2f}")
        dots.append({"x": round(x, 2), "y": round(y, 2),
                     "label": f'{bucket["label"]}: {bucket["value"]}'})
        if len(buckets) <= 14 or index % 2 == 0:
            labels.append({"x": round(x, 2), "y": HEIGHT - 8, "text": bucket["label"]})
    baseline = PAD_TOP + plot_height
    area = f"{PAD_LEFT:.2f},{baseline:.2f} " + " ".join(points) + \
           f" {PAD_LEFT + plot_width:.2f},{baseline:.2f}"
    return {"width": WIDTH, "height": HEIGHT, "points": " ".join(points), "area": area,
            "dots": dots, "labels": labels, "axis": _axis(top),
            "x0": PAD_LEFT, "x1": WIDTH - PAD_RIGHT}


def donut(done, total, size=132, stroke=16):
    """Completion ring. Returns the dash geometry for a single arc."""
    radius = (size - stroke) / 2
    circumference = 2 * 3.141592653589793 * radius
    percent = round(done * 100 / total) if total else 0
    return {"size": size, "stroke": stroke, "radius": round(radius, 2),
            "centre": size / 2, "circumference": round(circumference, 2),
            "dash": round(circumference * percent / 100, 2),
            "percent": percent, "done": done, "total": total}


def share_rows(rows):
    """Add a `share` percentage (of the largest row) for CSS bar widths."""
    top = max((row["total"] for row in rows), default=0)
    for row in rows:
        row["share"] = round(row["total"] * 100 / top) if top else 0
    return rows
