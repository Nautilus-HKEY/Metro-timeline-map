#!/usr/bin/env python3
"""Render a metro / Liniennetzplan-style timeline map with a two-view toggle bar (view names come from the data).

    python render_map.py --data ../data/stations.json [--data extra.json ...] \
        --from 1996 --until 2026 --out smfret-map [--view both|bio|method] [--html]

Writes <out>-biological.png and <out>-methodological.png (a PNG cannot toggle, so each
view is its own image with the toggle bar drawn in), <out>-references.md, and with --html
an interactive page <out>.html whose toggle bar switches between the two views.
Needs only Pillow. Later --data files override earlier ones by station id.
"""
import argparse, datetime, html as H, json, math, os, sys
from PIL import Image, ImageDraw, ImageFont

FONTS = {
    "regular": ["/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                "C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
             "/Library/Fonts/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
             "C:/Windows/Fonts/arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}
_fc, FONT_OVERRIDE = {}, {}


def font(kind, px):
    key = (kind, round(px))
    if key not in _fc:
        for p in ([FONT_OVERRIDE[kind]] if kind in FONT_OVERRIDE else []) + FONTS[kind]:
            if os.path.exists(p):
                _fc[key] = ImageFont.truetype(p, round(px)); break
        else:
            sys.exit("No usable font found. Pass --font-regular and --font-bold with .ttf paths.")
    return _fc[key]


LIGHT = dict(bg="#FFFFFF", ink="#16191C", muted="#5A646C", grid="#E1E5E8", rule="#C9D0D5", dot="#FFFFFF", pill_ink="#FFFFFF")
DARK = dict(bg="#101315", ink="#EEF1F3", muted="#9AA5AD", grid="#262D32", rule="#313A40", dot="#101315", pill_ink="#101315")
SS = 4
LH_YEAR, LH, ROWGAP = 21, 17, 126
SVG_FONT = "'Helvetica Neue',Helvetica,Arial,'Liberation Sans',sans-serif"


def lighten(hexc, f=0.4):
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02X%02X%02X" % tuple(round(c + (238 - c) * f) for c in (r, g, b))


def load(paths):
    views, stations, meta, links = None, {}, {}, []
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        if d.get("views"): views = d["views"]
        meta.update(d.get("meta", {}))
        for k in d.get("links", []):
            if not any(x["from"] == k["from"] and x["to"] == k["to"] for x in links): links.append(k)
        for s in d.get("stations", []):
            for k in ("id", "lines", "year", "label", "title", "cite"):
                if k not in s: sys.exit(f"station {s.get('id', '?')} in {p} is missing '{k}'")
            stations[s["id"]] = s
    if not views: sys.exit("no 'views' block found in the data files")
    return views, list(stations.values()), meta, links


def overlap(a, b, m=3):
    return a[0] < b[2] + m and b[0] < a[2] + m and a[1] < b[3] + m and b[1] < a[3] + m


def tw(txt, kind, px): return font(kind, px * SS).getlength(txt) / SS


# ====================================================================== scene
def hop_path(pts, others, r=12):
    """Return pts with a semicircular hop wherever the polyline crosses a segment of `others`.
    Straight between crossings; the hop bulges up (horizontal runs) or right (vertical runs)."""
    def inter(p1, p2, q1, q2):
        d = (p2[0] - p1[0]) * (q2[1] - q1[1]) - (p2[1] - p1[1]) * (q2[0] - q1[0])
        if abs(d) < 1e-9: return None
        s = ((q1[0] - p1[0]) * (q2[1] - q1[1]) - (q1[1] - p1[1]) * (q2[0] - q1[0])) / d
        u = ((q1[0] - p1[0]) * (p2[1] - p1[1]) - (q1[1] - p1[1]) * (p2[0] - p1[0])) / d
        return (s, u) if 0 < s < 1 and 0 <= u <= 1 else None
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
        ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
        hits = []
        for seg in others:
            for q1, q2 in zip(seg, seg[1:]):
                h = inter(a, b, q1, q2)
                if h and r + 4 < h[0] * L < L - r - 4: hits.append(h[0] * L)
        nx, ny = (uy, -ux) if abs(ux) >= abs(uy) else (abs(uy), 0)
        if abs(ux) >= abs(uy): nx, ny = 0, -1
        else: nx, ny = 1, 0
        last = -1e9
        for d in sorted(hits):
            if d - last < 2 * r + 4: continue
            last = d; cx, cy = a[0] + ux * d, a[1] + uy * d
            for k in range(0, 17):
                th = math.pi - math.pi * k / 16
                out.append((cx + ux * r * math.cos(th) + nx * r * math.sin(th), cy + uy * r * math.cos(th) + ny * r * math.sin(th)))
        out.append(b)
    return out


def build_scene(views, allst, links_all, meta, view, y0, y1, today):
    vcfg = views[view]; lines_cfg = vcfg["lines"]; cfg = {l["id"]: l for l in lines_cfg}
    sts = []
    for s in allst:
        if not (y0 <= int(s["year"]) <= y1): continue
        ln = s["lines"].get(view) if isinstance(s["lines"], dict) else s["lines"]
        if not ln: continue
        for i in ln:
            if i not in cfg: sys.exit(f"station {s['id']} uses unknown line '{i}' in view '{view}'")
        t = dict(s); t["ln"] = ln; sts.append(t)
    if not sts: sys.exit(f"No stations between {y0} and {y1}.")
    present = [l for l in lines_cfg if any(l["id"] in s["ln"] for s in sts)]
    row_of = {l["id"]: i for i, l in enumerate(present)}
    ids = {s["id"] for s in sts}
    links = [k for k in links_all if k["from"] in ids and k["to"] in ids]

    span = y1 - y0 + 1
    ppy = max(46.0, min(110.0, 1500.0 / span))
    LEFT, RIGHT, HEAD = 190, 170, 150
    W = int(LEFT + span * ppy + RIGHT)
    AX = HEAD + 44; ROW0 = AX + 118
    rowy = {l["id"]: ROW0 + row_of[l["id"]] * ROWGAP for l in present}
    MAPBOT = ROW0 + (len(present) - 1) * ROWGAP + 95
    for s in sts: s["x"] = LEFT + (s["year"] - y0) * ppy
    by_line = {l["id"]: sorted([s for s in sts if l["id"] in s["ln"]], key=lambda s: s["x"]) for l in present}
    first_of = {k: v[0] for k, v in by_line.items()}

    diverge, capsule = {}, {}
    for s in sts:
        if len(s["ln"]) == 1: continue
        rows = sorted(rowy[i] for i in s["ln"]); placed = False
        for L in s["ln"]:
            if first_of[L] is s:
                others = [M for M in s["ln"] if M != L and first_of[M] is not s]
                if others:
                    M = others[0]; dd = abs(rowy[L] - rowy[M])
                    nxt = [t for t in by_line[L] if t["x"] > s["x"]]
                    if not nxt or nxt[0]["x"] >= s["x"] + dd + 14:
                        diverge[(L, s["id"])] = M; placed = True; break
        if not placed: capsule[s["id"]] = (rows[0], rows[-1])

    def dot_rows(s):
        for (L, sid), M in diverge.items():
            if sid == s["id"]: return [rowy[M]]
        return [rowy[i] for i in s["ln"]]

    paths = {}
    for l in present:
        L = l["id"]; pts = []
        for i, s in enumerate(by_line[L]):
            if i == 0 and (L, s["id"]) in diverge:
                M = diverge[(L, s["id"])]; dd = abs(rowy[L] - rowy[M])
                pts += [(s["x"], rowy[M]), (s["x"] + dd, rowy[L])]
            else: pts.append((s["x"], rowy[L]))
        paths[L] = pts

    sc = []   # scene primitives

    # ---- obstacles
    obst = [(0, 0, W, AX + 14)]
    def seg_obst(p, q, pad=8):
        (x1, y1), (x2, y2) = p, q
        if y1 == y2: obst.append((min(x1, x2) - 6, y1 - pad, max(x1, x2) + 6, y1 + pad))
        elif x1 == x2: obst.append((x1 - pad, min(y1, y2) - 6, x1 + pad, max(y1, y2) + 6))
        else:
            n = int(math.hypot(x2 - x1, y2 - y1) / 6) + 1
            for k in range(n + 1):
                px, py = x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n
                obst.append((px - 8, py - 8, px + 8, py + 8))
    for L, pts in paths.items():
        for p, q in zip(pts, pts[1:]): seg_obst(p, q)

    dotbox = {}
    for s in sts:
        if s["id"] in capsule:
            t, b = capsule[s["id"]]; bb = (s["x"] - 14, t - 14, s["x"] + 14, b + 14)
        else:
            ys = dot_rows(s); bb = (s["x"] - 14, min(ys) - 14, s["x"] + 14, max(ys) + 14)
        dotbox[s["id"]] = bb

    # ---- links: along the source row, then straight to the target
    sid = {s["id"]: s for s in sts}
    link_paths = []
    link_tgt = {}; link_side = {}
    src_last = set()
    for k in links:
        sa, sb = sid[k["from"]], sid[k["to"]]
        ya = (dotbox[sa["id"]][1] + dotbox[sa["id"]][3]) / 2; yb = (dotbox[sb["id"]][1] + dotbox[sb["id"]][3]) / 2
        if sb["x"] > sa["x"] + 30:
            pts = [(sa["x"] + 17, ya), (sb["x"], ya)]
            if abs(yb - ya) > 1: pts.append((sb["x"], yb - 17 * (1 if yb > ya else -1)))
            else: pts[-1] = (sb["x"] - 17, ya)
        else:
            pts = [(sa["x"], ya), (sb["x"], yb)]
        link_paths.append(pts)
        for L in sa["ln"]:
            if by_line[L][-1] is sa: src_last.add(L)
        link_tgt[sb["id"]] = pts
        link_side[sb["id"]] = "a" if yb > ya else "b"
        for p, q in zip(pts, pts[1:]):
            if p[0] == q[0] and p is pts[-2] and q is pts[-1] and abs(q[1] - p[1]) > 1 and pts[-2][0] == pts[-1][0] and len(pts) > 2: continue
            seg_obst(p, q, 6)

    # ---- pills
    PW, PH = 38, 25; pillbox = {}
    for l in present:
        L = l["id"]; ex = paths[L][-1][0]
        if L not in src_last:
            pillbox[("end", L)] = (ex + 20, rowy[L] - PH / 2, ex + 20 + PW, rowy[L] + PH / 2)
        s0 = first_of[L]
        if ((L, s0["id"]) not in diverge and s0["id"] not in capsule and len(by_line[L]) > 1) or L in src_last:
            if s0["id"] not in capsule and (L, s0["id"]) not in diverge:
                pillbox[("start", L)] = (s0["x"] - 20 - PW, rowy[L] - PH / 2, s0["x"] - 20, rowy[L] + PH / 2)
    obst += [(b[0] - 2, b[1] - 2, b[2] + 2, b[3] + 2) for b in pillbox.values()]
    obst += list(dotbox.values())

    # ---- labels
    def label_lines(s):
        out = [(str(int(s["year"])) + ("" if s.get("checked", True) else "\u2020"), "bold", 17)]
        out += [(t, "bold" if i == 0 else "regular", 14 if i == 0 else 13) for i, t in enumerate(s["label"])]
        if s.get("delivery"): out.append((s["delivery"], "regular", 12.5))
        return out
    placed_lab, placement, side_ct = [], {}, {}
    for s in sorted(sts, key=lambda s: (s["x"], s["id"])):
        L = s["ln"][0]; k = side_ct.get(L, 0); side_ct[L] = k + 1
        pref = "b" if k % 2 == 0 else "a"
        txt = label_lines(s); wid = max(tw(t, kd, px) for t, kd, px in txt) + 4
        hts = [LH_YEAR if i == 0 else LH for i in range(len(txt))]; Ht = sum(hts); bb = dotbox[s["id"]]; best = None
        for oi, off in enumerate((0, 26, 52)):
            for side in (pref, "a" if pref == "b" else "b"):
                if s["id"] in link_tgt and (side != link_side[s["id"]] or off): continue
                for an in (("m",) if s["id"] in link_tgt else ("m", "s", "e", "S", "E")):
                    x = s["x"]
                    x0, x1 = {"m": (x - wid / 2, x + wid / 2), "s": (x - 6, x - 6 + wid), "e": (x + 6 - wid, x + 6), "S": (x + 10, x + 10 + wid), "E": (x - 10 - wid, x - 10)}[an]
                    if side == "a": y1b = bb[1] - off; y0b = y1b - Ht - 4
                    else: y0b = bb[3] + off - 2; y1b = y0b + Ht + 4
                    box = (x0, y0b, x1, y1b); scr = 0
                    for o in obst:
                        if o is bb: continue
                        if overlap(box, o, 2): scr += 1000
                    for p in placed_lab:
                        if overlap(box, p, 4): scr += 1000
                    if x0 < 8 or x1 > W - 8 or y1b > MAPBOT + 40: scr += 1000
                    scr += (0 if an == "m" else 6 if an in "SE" else 4) + (0 if side == pref else 3) + oi * 9
                    if best is None or scr < best[0]: best = (scr, box, side, an, off)
            if best and best[0] < 1000: break
        _, box, side, an, off = best
        placement[s["id"]] = (box, side, an, off, txt, hts); placed_lab.append(box)
        if s["id"] in link_tgt and side == link_side[s["id"]]:
            pts = link_tgt[s["id"]]; pts[-1] = (pts[-1][0], box[1] - 2 if side == "a" else box[3] + 2)
            seg_obst(pts[-2], pts[-1], 6)

    # ---- legend / footer geometry
    LEG_Y = MAPBOT + 40; cols = 3; colw = (W - 120) / cols; nrows = (len(present) + cols - 1) // cols
    FOOT_Y = LEG_Y + nrows * 46 + 28; Ht_total = int(FOOT_Y + 70)

    # ================= emit primitives
    def add(**k): sc.append(k)
    add(t="text", x=60, y=52, s="LINIENNETZPLAN  \u00b7  %d\u2013%d  \u00b7  %s VIEW" % (y0, y1, vcfg["name"].upper()),
        kind="bold", px=15, c="muted", an="ls", halo=False)
    add(t="text", x=60, y=108, s=meta.get("title", "Timeline"), kind="bold", px=52, c="ink", an="ls", halo=False)
    add(t="text", x=60, y=134, s=vcfg.get("subtitle", ""), kind="regular", px=16, c="muted", an="ls", halo=False)
    # toggle bar
    SW, SH = 176, 40; tx0 = W - 60 - 2 * SW; ty0 = 62
    add(t="text", x=tx0, y=ty0 - 10, s="VIEW", kind="bold", px=12, c="muted", an="ls", halo=False)
    for i, v in enumerate(views):
        add(t="seg", view=v, x0=tx0 + i * SW, y0=ty0, x1=tx0 + (i + 1) * SW, y1=ty0 + SH, name=views[v]["name"],
            active=(v == view), first=(i == 0), last=(i == len(views) - 1))
    # axis
    span_y = y1 - y0; step = 1 if span_y <= 12 else (2 if span_y <= 20 else 5)
    add(t="line", pts=[(LEFT - 70, AX), (W - 60, AX)], c="ink", w=1.6)
    for y in range(y0, y1 + 1):
        x = LEFT + (y - y0) * ppy; major = (y % step == 0) if step > 1 else True
        add(t="line", pts=[(x, AX - (8 if major else 4)), (x, AX + 5)], c="ink", w=1.3)
        if major:
            add(t="line", pts=[(x, AX + 12), (x, MAPBOT)], c="grid", w=1)
            add(t="text", x=x, y=AX - 16, s=str(y), kind="bold", px=15, c="ink", an="ms", halo=False)
    if y0 <= today.year <= y1:
        tx = LEFT + (today.year + (today.timetuple().tm_yday - 1) / 365.0 - y0) * ppy
        add(t="poly", pts=[(tx - 7, AX - 12), (tx + 7, AX - 12), (tx, AX + 1)], c="ink")
        add(t="text", x=tx, y=AX - 40, s=today.strftime("%b %Y"), kind="bold", px=13, c="muted", an="ms", halo=False)
    # lines
    for l in present:
        pts = paths[l["id"]]
        if len(pts) == 1: pts = [pts[0], (pts[0][0] + 0.01, pts[0][1])]
        add(t="line", pts=pts, c="L:" + l["id"], w=10, dash=(14, 9) if l.get("style") == "dashed" else None)
    # link arrows
    for pts in link_paths:
        add(t="line", pts=hop_path(pts, [paths[l["id"]] for l in present if len(paths[l["id"]]) > 1]), c="ink", w=2.4, dash=(10, 7))
        (x1, y1_), (x2, y2) = pts[-2], pts[-1]; Ln = math.hypot(x2 - x1, y2 - y1_) or 1
        ux, uy = (x2 - x1) / Ln, (y2 - y1_) / Ln; nx, ny = -uy, ux
        add(t="poly", pts=[(x2, y2), (x2 - ux * 12 + nx * 6, y2 - uy * 12 + ny * 6), (x2 - ux * 12 - nx * 6, y2 - uy * 12 - ny * 6)], c="ink")
    # pills
    for (kind, L), b in pillbox.items():
        add(t="pill", box=b, c="L:" + L, s=cfg[L].get("badge", L))
    # leaders
    for s in sts:
        box, side, an, off, txt, hts = placement[s["id"]]; bb = dotbox[s["id"]]
        if off > 0:
            yf = bb[1] + 14 if side == "a" else bb[3] - 14; yt = box[3] if side == "a" else box[1]
            add(t="line", pts=[(s["x"], yf), (s["x"], yt)], c="muted", w=1.2)
    # stations + labels (grouped by sid)
    for s in sts:
        x = s["x"]; bb = dotbox[s["id"]]
        add(t="hit", sid=s["id"], box=(bb[0] - 6, bb[1] - 6, bb[2] + 6, bb[3] + 6))
        if s["id"] in capsule:
            t, b = capsule[s["id"]]
            add(t="rrect", sid=s["id"], box=(x - 9, t - 9, x + 9, b + 9), r=9, fill="dot", stroke="ink", sw=3.6, ring=(x - 15, t - 15, x + 15, b + 15, 15))
        elif len(s["ln"]) > 1:
            y = dot_rows(s)[0]
            add(t="circle", sid=s["id"], cx=x, cy=y, r=11, fill="dot", stroke="ink", sw=4, ring=15)
        else:
            y = rowy[s["ln"][0]]
            add(t="circle", sid=s["id"], cx=x, cy=y, r=8, fill="dot", stroke="ink", sw=3.6, ring=14)
        box, side, an, off, txt, hts = placement[s["id"]]
        ax = {"m": x, "s": x - 6, "e": x + 6, "S": x + 10, "E": x - 10}[an]; yy = box[1] + 2
        for i, (tt, kd, px) in enumerate(txt):
            add(t="text", sid=s["id"], x=ax, y=yy + hts[i] - 5, s=tt, kind=kd, px=px, c="ink" if i < 2 else "muted", an={"m": "ms", "s": "ls", "e": "rs", "S": "ls", "E": "rs"}[an], halo=True)
            yy += hts[i]
    # legend
    add(t="line", pts=[(60, LEG_Y - 20), (W - 60, LEG_Y - 20)], c="rule", w=1.2)
    for i, l in enumerate(present):
        cx = 60 + (i % cols) * colw; cy = LEG_Y + (i // cols) * 46
        add(t="pill", box=(cx, cy, cx + PW, cy + PH), c="L:" + l["id"], s=l.get("badge", l["id"]))
        add(t="text", x=cx + PW + 14, y=cy + 11, s=l["name"] + ("  (dashed)" if l.get("style") == "dashed" else ""), kind="bold", px=15, c="ink", an="ls", halo=False)
        add(t="text", x=cx + PW + 14, y=cy + 30, s=l["desc"], kind="regular", px=13, c="muted", an="ls", halo=False)
    add(t="text", x=60, y=FOOT_Y, s="Dates are publication years. Verified against sources through %s." % meta.get("verified_through", "n/a"), kind="regular", px=13, c="muted", an="ls", halo=False)
    if any(not s.get("checked", True) for s in sts):
        add(t="text", x=60, y=FOOT_Y + 22, s="\u2020 Authors or year taken from memory, not re-checked against the paper.", kind="regular", px=13, c="muted", an="ls", halo=False)
    if meta.get("credit"):
        _cy = FOOT_Y + (44 if any(not s.get("checked", True) for s in sts) else 22)
        add(t="text", x=60, y=_cy, s=meta["credit"], kind="regular", px=13, c="muted", an="ls", halo=False)
    if links:
        lt = "Dashed arrow: documented link (see references)."
        if any(not k.get("checked", True) for k in links): lt = lt[:-1] + ", source not fully confirmed."
        add(t="text", x=W - 60, y=FOOT_Y, s=lt, kind="regular", px=13, c="muted", an="rs", halo=False)
    return dict(sc=sc, W=W, H=Ht_total, cfg=cfg, present=present, sts=sts, links=links, view=view)


# ====================================================================== PNG
def render_png(scene, T, path, scale):
    W, Hh, cfg = scene["W"], scene["H"], scene["cfg"]; S = SS
    img = Image.new("RGB", (W * S, Hh * S), T["bg"]); d = ImageDraw.Draw(img)
    def col(c): return cfg[c[2:]]["color"] if c.startswith("L:") else T[c]
    def dashed(pts, c, w, dash):
        on, off = dash
        for p, q in zip(pts, pts[1:]):
            Ln = math.hypot(q[0] - p[0], q[1] - p[1]) or 1; ux, uy = (q[0] - p[0]) / Ln, (q[1] - p[1]) / Ln; pos = 0.0
            while pos < Ln:
                e = min(pos + on, Ln)
                d.line([((p[0] + ux * pos) * S, (p[1] + uy * pos) * S), ((p[0] + ux * e) * S, (p[1] + uy * e) * S)], fill=c, width=int(w * S))
                pos += on + off
    for p in scene["sc"]:
        t = p["t"]
        if t == "line":
            pts = [(x * S, y * S) for x, y in p["pts"]]
            if p.get("dash"): dashed(p["pts"], col(p["c"]), p["w"], p["dash"])
            else:
                d.line(pts, fill=col(p["c"]), width=int(p["w"] * S), joint="curve")
                if p["w"] >= 9:
                    for (x, y) in pts[1:-1]:
                        r = p["w"] * S / 2; d.ellipse([x - r, y - r, x + r, y + r], fill=col(p["c"]))
        elif t == "poly": d.polygon([(x * S, y * S) for x, y in p["pts"]], fill=col(p["c"]))
        elif t == "pill":
            b = p["box"]; d.rounded_rectangle([b[0] * S, b[1] * S, b[2] * S, b[3] * S], radius=int(6 * S), fill=col(p["c"]))
            d.text(((b[0] + b[2]) / 2 * S, ((b[1] + b[3]) / 2 + .5) * S), p["s"], font=font("bold", 16 * S), fill=T["pill_ink"], anchor="mm")
        elif t == "seg":
            r = int(10 * S); fill = T["ink"] if p["active"] else T["bg"]
            d.rounded_rectangle([p["x0"] * S, p["y0"] * S, p["x1"] * S, p["y1"] * S], radius=r, fill=fill, outline=T["ink"], width=int(1.8 * S))
            d.text(((p["x0"] + p["x1"]) / 2 * S, (p["y0"] + p["y1"]) / 2 * S + 1), p["name"], font=font("bold", 16 * S),
                   fill=T["bg"] if p["active"] else T["ink"], anchor="mm")
        elif t == "circle":
            r = p["r"]; d.ellipse([(p["cx"] - r) * S, (p["cy"] - r) * S, (p["cx"] + r) * S, (p["cy"] + r) * S], fill=col(p["fill"]), outline=col(p["stroke"]), width=int(p["sw"] * S))
        elif t == "rrect":
            b = p["box"]; d.rounded_rectangle([b[0] * S, b[1] * S, b[2] * S, b[3] * S], radius=int(p["r"] * S), fill=col(p["fill"]), outline=col(p["stroke"]), width=int(p["sw"] * S))
        elif t == "text":
            d.text((p["x"] * S, p["y"] * S), p["s"], font=font(p["kind"], p["px"] * S), fill=col(p["c"]), anchor=p["an"],
                   stroke_width=int(3 * S) if p.get("halo") else 0, stroke_fill=T["bg"])
    img = img.resize((int(W * scale), int(Hh * scale)), Image.LANCZOS)
    img.save(path, optimize=True)
    return img.size


# ====================================================================== SVG
def svg_scene(scene, vid, hidden):
    cfg = scene["cfg"]
    def col(c): return "var(--lc-%s)" % c[2:] if c.startswith("L:") else "var(--%s)" % c.replace("_", "-")
    e = lambda v: ("%.1f" % v).rstrip("0").rstrip(".")
    base, groups = [], {}
    def tx(p):
        halo = ' style="paint-order:stroke;stroke:var(--bg);stroke-width:3px;stroke-linejoin:round"' if p.get("halo") else ""
        an = {"ls": "start", "ms": "middle", "rs": "end"}[p["an"]]
        return '<text x="%s" y="%s" text-anchor="%s" font-size="%s" font-weight="%s" fill="%s"%s>%s</text>' % (
            e(p["x"]), e(p["y"]), an, e(p["px"]), 700 if p["kind"] == "bold" else 400, col(p["c"]), halo, H.escape(p["s"]))
    for p in scene["sc"]:
        t = p["t"]; out = None
        if t == "line":
            dash = ' stroke-dasharray="%s %s"' % p["dash"] if p.get("dash") else ""
            out = '<path d="M%s" fill="none" stroke="%s" stroke-width="%s" stroke-linejoin="round"%s/>' % (
                " L".join("%s,%s" % (e(x), e(y)) for x, y in p["pts"]), col(p["c"]), e(p["w"]), dash)
        elif t == "poly":
            out = '<polygon points="%s" fill="%s"/>' % (" ".join("%s,%s" % (e(x), e(y)) for x, y in p["pts"]), col(p["c"]))
        elif t == "pill":
            b = p["box"]; out = ('<rect x="%s" y="%s" width="%s" height="%s" rx="6" fill="%s"/><text x="%s" y="%s" text-anchor="middle" font-size="16" font-weight="700" fill="var(--pill-ink)">%s</text>' %
                                 (e(b[0]), e(b[1]), e(b[2] - b[0]), e(b[3] - b[1]), col(p["c"]), e((b[0] + b[2]) / 2), e((b[1] + b[3]) / 2 + 5.5), H.escape(p["s"])))
        elif t == "seg":
            fill = "var(--ink)" if p["active"] else "var(--bg)"; fg = "var(--bg)" if p["active"] else "var(--ink)"
            out = ('<g class="seg%s" data-view="%s" role="button" tabindex="0" aria-pressed="%s" aria-label="%s view"><rect x="%s" y="%s" width="%s" height="%s" rx="10" fill="%s" stroke="var(--ink)" stroke-width="1.8"/>'
                   '<text x="%s" y="%s" text-anchor="middle" font-size="16" font-weight="700" fill="%s">%s</text></g>' %
                   (" on" if p["active"] else "", p["view"], str(p["active"]).lower(), H.escape(p["name"]), e(p["x0"]), e(p["y0"]), e(p["x1"] - p["x0"]), e(p["y1"] - p["y0"]), fill,
                    e((p["x0"] + p["x1"]) / 2), e((p["y0"] + p["y1"]) / 2 + 5.5), fg, H.escape(p["name"])))
        elif t == "text" and not p.get("sid"): out = tx(p)
        if out and not p.get("sid"): base.append(out)
        if p.get("sid"):
            g = groups.setdefault(p["sid"], [])
            if t == "hit":
                b = p["box"]; g.append('<rect x="%s" y="%s" width="%s" height="%s" fill="transparent"/>' % (e(b[0]), e(b[1]), e(b[2] - b[0]), e(b[3] - b[1])))
            elif t == "circle":
                g.append('<circle class="ring" cx="%s" cy="%s" r="%s" fill="none" stroke="var(--ink)" stroke-width="2"/>' % (e(p["cx"]), e(p["cy"]), e(p["ring"])))
                g.append('<circle cx="%s" cy="%s" r="%s" fill="%s" stroke="%s" stroke-width="%s"/>' % (e(p["cx"]), e(p["cy"]), e(p["r"]), col(p["fill"]), col(p["stroke"]), e(p["sw"])))
            elif t == "rrect":
                r = p["ring"]; b = p["box"]
                g.append('<rect class="ring" x="%s" y="%s" width="%s" height="%s" rx="%s" fill="none" stroke="var(--ink)" stroke-width="2"/>' % (e(r[0]), e(r[1]), e(r[2] - r[0]), e(r[3] - r[1]), e(r[4])))
                g.append('<rect x="%s" y="%s" width="%s" height="%s" rx="%s" fill="%s" stroke="%s" stroke-width="%s"/>' % (e(b[0]), e(b[1]), e(b[2] - b[0]), e(b[3] - b[1]), e(p["r"]), col(p["fill"]), col(p["stroke"]), e(p["sw"])))
            elif t == "text": g.append(tx(p))
    st = {s["id"]: s for s in scene["sts"]}
    gs = "".join('<g class="st" tabindex="0" role="button" data-id="%s" aria-label="%s">%s</g>' % (
        k, H.escape("%d, %s, %s" % (int(st[k]["year"]), st[k]["title"], st[k]["cite"])), "".join(v)) for k, v in groups.items())
    return '<svg id="%s" class="map"%s viewBox="0 0 %d %d" xmlns="http://www.w3.org/2000/svg" font-family="%s" role="group" aria-label="%s view of milestones">%s%s</svg>' % (
        vid, " hidden" if hidden else "", scene["W"], scene["H"], SVG_FONT, scene["view"], "".join(base), gs)


HTML = """<title>%TITLE% Map</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* Layout: a Liniennetzplan with a Biological / Methodological toggle bar inside the figure. */
:root{--bg:#FFFFFF;--panel:#FFFFFF;--page:#F1F3F4;--ink:#16191C;--muted:#5A646C;--grid:#E1E5E8;--rule:#C9D0D5;--dot:#FFFFFF;--pill-ink:#FFFFFF;%LC_LIGHT%}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#171B1E;--panel:#171B1E;--page:#101315;--ink:#EEF1F3;--muted:#9AA5AD;--grid:#262D32;--rule:#313A40;--dot:#171B1E;--pill-ink:#101315;%LC_DARK%color-scheme:dark}}
:root[data-theme="dark"]{--bg:#171B1E;--panel:#171B1E;--page:#101315;--ink:#EEF1F3;--muted:#9AA5AD;--grid:#262D32;--rule:#313A40;--dot:#171B1E;--pill-ink:#101315;%LC_DARK%color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--page);color:var(--ink);font-family:'Helvetica Neue',Helvetica,Arial,'Liberation Sans',sans-serif;font-size:15px;line-height:1.5}
.page{max-width:1500px;margin:0 auto;padding-block:24px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:flex;flex-direction:column;gap:18px}
.wrap{background:var(--panel);border:1px solid var(--rule);border-radius:10px;overflow-x:auto;overscroll-behavior-x:contain}
svg.map{display:block;width:100%;min-width:1500px;height:auto}
svg.map text{user-select:none}
.st{cursor:pointer;outline:none}.st .ring{opacity:0}.st:hover .ring{opacity:.35}.st.sel .ring,.st:focus-visible .ring{opacity:1}
.seg{cursor:pointer;outline:none}.seg:focus-visible rect{stroke-width:4}.seg:not(.on):hover rect{fill:var(--grid)}
.hint{margin:0;font-size:13px;color:var(--muted)}
.detail{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:20px;display:grid;grid-template-columns:auto 1fr;gap:8px 24px;align-items:start}
.d-year{font-weight:700;font-size:clamp(44px,6vw,72px);line-height:.9;font-variant-numeric:tabular-nums}
.d-body{min-width:0;display:flex;flex-direction:column;gap:6px}
.d-body h2{margin:0;font-size:24px;line-height:1.15;text-wrap:balance}
.d-lines{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.pl{display:inline-flex;align-items:center;justify-content:center;min-width:26px;height:22px;padding:0 7px;border-radius:5px;color:var(--pill-ink);font-weight:700;font-size:13px;white-space:nowrap}
.d-cite{margin:0;font-size:14px;color:var(--muted)}.d-text{margin:0;max-width:70ch}
.d-body a,td a{color:var(--ink);text-decoration-thickness:1px;text-underline-offset:3px}
@media (max-width:640px){.detail{grid-template-columns:1fr}}
h3{margin:6px 0 0;font-size:22px}
.tbl{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:760px;font-size:14px}
th{font-size:12.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);text-align:left;padding:10px 14px;border-bottom:1px solid var(--rule)}
td{padding:9px 14px;border-bottom:1px solid var(--grid);vertical-align:top}tr:last-child td{border-bottom:0}
td.num{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.note{margin:0;font-size:13px;color:var(--muted);max-width:80ch}
</style>
<div class="page">
  <div class="wrap" id="wrap">%SVGS%</div>
  <p class="hint">Use the toggle bar at the top right of the map to switch view. Select a station for its reference. On a narrow screen, scroll the map sideways.</p>
  <section class="detail" id="detail" aria-live="polite">
    <div class="d-year" id="d-year"></div>
    <div class="d-body"><div class="d-lines" id="d-lines"></div><h2 id="d-title"></h2><p class="d-cite" id="d-cite"></p><p class="d-text" id="d-text"></p><p class="d-cite" id="d-link"></p></div>
  </section>
  <h3>Fahrplan</h3>
  <div class="tbl"><table><thead><tr><th>Year</th><th>Station</th><th>%V1% line</th><th>%V2% line</th><th>Reference</th></tr></thead><tbody>%ROWS%</tbody></table></div>
  <p class="note">%NOTE%</p>
</div>
<script>
(function(){
  var D=%DATA%, cur=%FIRST%, sel=%SEL%;
  function pills(ids,view){return ids.map(function(i){var l=D.lines[view][i];return '<span class="pl" style="background:var(--lc-'+i+')">'+l.badge+' '+l.name+'</span>';}).join('');}
  function detail(id){
    var s=D.st[id]; if(!s) return; sel=id;
    document.getElementById('d-year').textContent=s.year; document.getElementById('d-title').textContent=s.title;
    document.getElementById('d-cite').textContent=s.cite; document.getElementById('d-text').textContent=s.text;
    document.getElementById('d-lines').innerHTML=pills(s.ln[cur]||[],cur);
    var k=document.getElementById('d-link'); k.innerHTML=''; if(s.url){var a=document.createElement('a');a.href=s.url;a.target='_blank';a.rel='noopener';a.textContent='Open source';k.appendChild(a);}
    document.querySelectorAll('.st').forEach(function(g){g.classList.toggle('sel',g.getAttribute('data-id')===id);});
  }
  function view(v){
    cur=v; Object.keys(D.lines).forEach(function(k){document.getElementById('v-'+k).hidden=(k!==v);});
    if(!D.st[sel]||!(D.st[sel].ln[v]||[]).length){var f=document.querySelector('#v-'+v+' .st'); if(f) sel=f.getAttribute('data-id');}
    detail(sel);
  }
  document.querySelectorAll('.seg').forEach(function(g){
    g.addEventListener('click',function(){view(g.getAttribute('data-view'));});
    g.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();view(g.getAttribute('data-view'));}});
  });
  document.querySelectorAll('.st').forEach(function(g){
    g.addEventListener('click',function(){detail(g.getAttribute('data-id'));});
    g.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();detail(g.getAttribute('data-id'));}});
  });
  view(cur);
})();
</script>
"""


def build_html(scenes, views, sts_all, links, meta, y0, y1, first, standalone):
    ids_lines = {}
    lc_l, lc_d = "", ""
    for v, vc in views.items():
        for l in vc["lines"]:
            ids_lines.setdefault(l["id"], l["color"])
    for i, c in ids_lines.items():
        lc_l += "--lc-%s:%s;" % (i, c); lc_d += "--lc-%s:%s;" % (i, lighten(c))
    svgs = "".join(svg_scene(sc, "v-" + v, v != first) for v, sc in scenes.items())
    data = {"lines": {v: {l["id"]: {"badge": l.get("badge", l["id"]), "name": l["name"]} for l in vc["lines"]} for v, vc in views.items()}, "st": {}}
    rows = ""
    shown = {s["id"]: s for sc in scenes.values() for s in sc["sts"]}
    for s in sorted(shown.values(), key=lambda s: (s["year"], s["id"])):
        data["st"][s["id"]] = dict(year=str(int(s["year"])), title=s["title"], cite=s["cite"], text=s["text"], url=s.get("url"),
                                   ln={v: s["lines"].get(v, []) if isinstance(s["lines"], dict) else s["lines"] for v in views})
        def pl(v):
            out = ""
            for i in data["st"][s["id"]]["ln"][v]:
                l = next(x for x in views[v]["lines"] if x["id"] == i)
                out += '<span class="pl" style="background:var(--lc-%s);margin-right:4px">%s</span>' % (i, H.escape(l.get("badge", i)))
            return out or "–"
        ref = H.escape(s["cite"]) + ("\u2020" if not s.get("checked", True) else "")
        if s.get("url"): ref = '<a href="%s" target="_blank" rel="noopener">%s</a>' % (H.escape(s["url"]), ref)
        rows += '<tr><td class="num">%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % (int(s["year"]), H.escape(s["title"]), pl("a"), pl("b"), ref)
    note = "A selection of milestones, not a full census. Years are publication years. Verified against sources through %s. \u2020 marks authors or years taken from memory." % meta.get("verified_through", "n/a")
    if links: note += " The dashed arrow marks a documented link" + (" whose source is not fully confirmed." if any(not k.get("checked", True) for k in links) else ".")
    if meta.get("credit"): note += " " + meta["credit"]
    selid = "sak10" if "sak10" in data["st"] else next(iter(data["st"]))
    vk = list(views); out = HTML.replace("%TITLE%", H.escape(meta.get("title", "Timeline"))).replace("%V1%", H.escape(views[vk[0]]["name"])).replace("%V2%", H.escape(views[vk[-1]]["name"])).replace("%LC_LIGHT%", lc_l).replace("%LC_DARK%", lc_d).replace("%SVGS%", svgs).replace("%ROWS%", rows) \
              .replace("%NOTE%", H.escape(note)).replace("%DATA%", json.dumps(data, ensure_ascii=False)) \
              .replace("%FIRST%", json.dumps(first)).replace("%SEL%", json.dumps(selid))
    if standalone: out = "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"></head><body>\n" + out + "\n</body></html>"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="append", required=True)
    ap.add_argument("--from", dest="y0", type=int, required=True)
    ap.add_argument("--until", dest="y1", type=int, required=True)
    ap.add_argument("--out", default="smfret-map")
    ap.add_argument("--view", default="both", choices=["both", "a", "b"])
    ap.add_argument("--html", action="store_true", help="also write an interactive page with the toggle bar")
    ap.add_argument("--html-fragment", action="store_true", help="html without doctype/head wrapper (for artifact hosts)")
    ap.add_argument("--title", help="map title (overrides meta.title in the data)")
    ap.add_argument("--credit", help="optional credit line printed in the footer of each map and in the page note")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--dark", action="store_true")
    ap.add_argument("--font-regular"); ap.add_argument("--font-bold")
    a = ap.parse_args()
    if a.font_regular: FONT_OVERRIDE["regular"] = a.font_regular
    if a.font_bold: FONT_OVERRIDE["bold"] = a.font_bold
    if a.y1 < a.y0: sys.exit("--until must not be before --from")
    views, allst, meta, links = load(a.data)
    if a.title: meta["title"] = a.title
    if a.credit: meta["credit"] = a.credit
    today = datetime.date.today(); T = DARK if a.dark else LIGHT
    scenes = {v: build_scene(views, allst, links, meta, v, a.y0, a.y1, today) for v in views}
    import re as _re; names = {v: _re.sub(r"[^a-z0-9]+", "-", views[v]["name"].lower()).strip("-") or v for v in views}
    for v, sc in scenes.items():
        if a.view in ("both", v):
            w, h = render_png(sc, T, "%s-%s.png" % (a.out, names.get(v, v)), a.scale)
            print("wrote %s-%s.png (%dx%d), %d stations" % (a.out, names.get(v, v), w, h, len(sc["sts"])))
    if a.html or a.html_fragment:
        first = "a" if a.view == "both" else a.view
        open(a.out + ".html", "w", encoding="utf-8").write(build_html(scenes, views, allst, links, meta, a.y0, a.y1, first, not a.html_fragment))
        print("wrote %s.html" % a.out)
    shown = {s["id"]: s for sc in scenes.values() for s in sc["sts"]}
    with open(a.out + "-references.md", "w", encoding="utf-8") as f:
        f.write("# References, %d\u2013%d\n\n| Year | Station | %s line | %s line | Reference |\n|---|---|---|---|---|\n" % (a.y0, a.y1, views[list(views)[0]]["name"], views[list(views)[-1]]["name"]))
        for s in sorted(shown.values(), key=lambda s: (s["year"], s["id"])):
            def nm(v):
                ids = s["lines"].get(v, []) if isinstance(s["lines"], dict) else s["lines"]
                return " + ".join(next(x for x in views[v]["lines"] if x["id"] == i)["name"] for i in ids) or "-"
            ref = s["cite"] + ("\u2020" if not s.get("checked", True) else "")
            if s.get("url"): ref = "[%s](%s)" % (ref, s["url"])
            f.write("| %d | %s | %s | %s | %s |\n" % (int(s["year"]), s["title"], nm("a"), nm("b"), ref))
        vis = [k for k in links if k["from"] in shown and k["to"] in shown]
        if vis:
            f.write("\n## Links\n\n")
            for k in vis:
                f.write("- %s to %s: %s%s\n" % (shown[k["from"]]["title"], shown[k["to"]]["title"], k["note"], (" [source](%s)" % k["url"]) if k.get("url") else ""))
    print("wrote %s-references.md" % a.out)


if __name__ == "__main__":
    main()
