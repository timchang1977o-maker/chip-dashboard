#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股財報區 — 兩個獨立來源合成一頁 us_earnings.html（chip-dashboard / GitHub Pages）。

來源 A｜韭菜王 Allen：投資 cover list（Google Sheet，link-可讀免登入）
  export?format=xlsx → openpyxl。每分頁固定 B-M 12 欄（見 memory project_cover_list_sheet）：
  row2 季度標頭 / row5 Revenue / row9 EPS / row11-17 年度 / row19-24 估值
  欄位對應：B-E 歷史(A)｜F=本季Allen G=共識 H=實際｜I/J=下季｜K=下季指引｜L/M=下下季
來源 B｜Henry(Pentimetrics)：curated henry_data.json（由 pentimetrics_db 精準抽取）

設計：精煉財經編輯風、強制淺色（Evan Mac 深色模式，交付物一律淺色）。每檔一張獨立卡，
  hero 數字放大＋「vs 共識」發散比較條＋清楚分層留白；Henry 觀點做引言區塊。

用法：python3 build_us_earnings.py            （自動下載最新 sheet）
      python3 build_us_earnings.py local.xlsx  （用本機 xlsx，離線）
"""
import sys, json, io, datetime, html, urllib.request
import openpyxl
from pathlib import Path

SHEET_ID = "1Hfb1eX23xCbGMYOh-76_DjpAgwl7-8DG8TjbtxqZRD4"
EXPORT = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
ROOT = Path(__file__).resolve().parent

META = {
    "GOOG": ("Alphabet",   "看多",   "2026/07/23"),
    "AMZN": ("亞馬遜",      "看多",   "2026/08/03"),
    "MSFT": ("微軟",        "中性偏多","2026/07/31"),
    "META": ("Meta",        "偏空",   "2026/08/02"),
    "TSM":  ("台積電 ADR",  "中性",   "2026/07/17"),
    "MTK":  ("聯發科",      "看多",   "2026/08/02"),
    "ASML": ("艾司摩爾",    "看多",   "2026/07/15"),
    "AMD":  ("超微 AMD",    "看多",   "2026/08/06"),
    "TER":  ("Teradyne",    "看多",   "2026/08/04"),
    "VRT":  ("Vertiv",      "中性偏多","2026/08/09"),
    "ONTO": ("Onto",        "看多",   "2026/08/13"),
    "LITE": ("Lumentum",    "看多",   "2026/08/14"),
    "CLS":  ("Celestica",   "看多",   "2026/07/29"),
    "GLW":  ("康寧 Corning", "中性",  "2026/07/30"),
    "NOK":  ("Nokia",       "看多",   "2026/07/27"),
    "COHR": ("Coherent",    "看多",   "2026/05/10"),
    "AMAT": ("應用材料",    "看多",   "2026/05/16"),
    "AVGO": ("博通 Broadcom","中性",  "2026/07/23"),
    "NVDA": ("輝達 NVIDIA", "看多",   "2026/05/28"),
    "CIEN": ("Ciena",       "追蹤",   "2026/03/12"),
}
ORDER = list(META.keys())
COL = {c: i for i, c in enumerate("BCDEFGHIJKLM", start=2)}
STANCE_CLS = {"看多": "s-bull", "中性偏多": "s-bullmid", "中性": "s-neu",
              "偏空": "s-bear", "追蹤": "s-watch"}


def load_wb():
    if len(sys.argv) > 1:
        p = sys.argv[1]
        return (openpyxl.load_workbook(p, data_only=True),
                openpyxl.load_workbook(p, data_only=False))
    req = urllib.request.Request(EXPORT, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=60).read()
    return (openpyxl.load_workbook(io.BytesIO(raw), data_only=True),
            openpyxl.load_workbook(io.BytesIO(raw), data_only=False))


def num(v):
    return v if isinstance(v, (int, float)) else None


def extract(wbd, wbf):
    data = {}
    for t in ORDER:
        if t not in wbd.sheetnames:
            continue
        wd, wf = wbd[t], wbf[t]
        c = lambda col, row: wd.cell(row=row, column=COL[col]).value
        lab = lambda col: (str(wf.cell(row=2, column=COL[col]).value).strip()
                           if wf.cell(row=2, column=COL[col]).value else "")
        unit = (wf["A2"].value or "").replace("In Millions of", "").strip().upper()
        rec = {
            "name": META[t][0], "stance": META[t][1], "date": META[t][2],
            "unit": unit, "cur_q": lab("F").replace("(E)", ""),
            "act_rev": num(c("H", 5)), "cons_rev": num(c("G", 5)),
            "act_eps": num(c("H", 9)), "cons_eps": num(c("G", 9)),
            "n_q": lab("I").replace("(E)", ""),
            "n_est_rev": num(c("I", 5)), "n_est_eps": num(c("I", 9)),
            "guid": c("K", 5),
            "eps26": num(c("F", 17)), "eps27": num(c("H", 17)),
        }
        price = None
        for r in (19, 20, 21):
            for cc in ("B", "C"):
                f = wf.cell(row=r, column=COL[cc]).value
                if isinstance(f, str) and "GOOGLEFINANCE" in f and "252" not in f:
                    price = num(wd.cell(row=r, column=COL[cc]).value)
                    break
            if price:
                break
        rec["price"] = price
        pe = num(wd["C19"].value)
        if not (pe and 0 < pe < 200):
            pe = (price / rec["eps26"]) if (price and rec["eps26"] and 0 < rec["eps26"] < 500) else None
        rec["pe"] = pe
        data[t] = rec
    return data


# ---------- format helpers ----------
def is_eps(v):
    return isinstance(v, (int, float)) and abs(v) < 500  # 濾掉 AMZN 營業利益巨值


def bil(v):
    return f"{v/100:,.1f}" if isinstance(v, (int, float)) else None


def fmt(v, d=2):
    return f"{v:,.{d}f}" if isinstance(v, (int, float)) else None


def pct(a, b):
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and b):
        return None
    return (a / b - 1) * 100


def esc(v):
    return html.escape(str(v)) if v is not None else ""


def cmp_bar(p):
    """發散比較條：中線＝共識，右綠=beat 左紅=miss，寬度∝|delta|(±25% 滿格半邊)。回傳 HTML。"""
    if p is None:
        return ""
    w = min(abs(p) / 25.0, 1.0) * 50.0
    if p >= 0:
        seg = f'<span class="cf beat" style="left:50%;width:{w:.0f}%"></span>'
    else:
        seg = f'<span class="cf miss" style="right:50%;width:{w:.0f}%"></span>'
    return f'<div class="cbar"><span class="cmid"></span>{seg}</div>'


# ---------- Allen card ----------
def hero_block(label, big, unit, p, cons_label):
    """一個 hero 指標：標籤 + 大數字 + beat/miss pill + 比較條 + vs 共識。"""
    if big is None:
        return f'<div class="metric"><div class="mlabel">{esc(label)}</div><div class="mbig mut">待公布</div></div>'
    pill = ""
    if p is not None:
        cls = "beat" if p >= 0 else "miss"
        arr = "▲" if p >= 0 else "▼"
        pill = f'<span class="pill {cls}">{arr}{abs(p):.1f}%</span>'
    u = f'<span class="munit">億{unit}</span>' if unit else ""
    bar = cmp_bar(p)
    cl = f'<div class="cons">{esc(cons_label)}</div>' if cons_label else ""
    return (f'<div class="metric"><div class="mlabel">{esc(label)}</div>'
            f'<div class="mbig">{esc(big)}{u} {pill}</div>{bar}{cl}</div>')


def allen_card(t, r):
    scls = STANCE_CLS.get(r["stance"], "s-neu")
    unit = r["unit"] or "USD"
    rp = pct(r["act_rev"], r["cons_rev"])
    rev_hero = hero_block("實際營收", bil(r["act_rev"]), unit, rp,
                          f'vs 共識 {bil(r["cons_rev"])}' if bil(r["cons_rev"]) else "")
    # EPS 次要 hero（EPS 無單位）
    ep = pct(r["act_eps"], r["cons_eps"])
    eps_hero = ""
    if is_eps(r["act_eps"]):
        eps_hero = hero_block("EPS", fmt(r["act_eps"]), "", ep,
                              f'vs 共識 {fmt(r["cons_eps"])}' if is_eps(r["cons_eps"]) else "")
    # 下季 + 指引
    nq = r["n_q"] or ""
    nrev = bil(r["n_est_rev"]); neps = fmt(r["n_est_eps"]) if is_eps(r["n_est_eps"]) else None
    guid = r["guid"] if isinstance(r["guid"], str) else (bil(r["guid"]) if isinstance(r["guid"], (int, float)) else None)
    fwd = ""
    if nrev or neps or guid:
        parts = []
        if nrev: parts.append(f'<span>營收 <b>{nrev}</b></span>')
        if neps: parts.append(f'<span>EPS <b>{neps}</b></span>')
        gline = f'<div class="gd">指引 {esc(guid)}</div>' if guid else ""
        fwd = (f'<div class="fwd"><div class="fwd-h">下季 {esc(nq)}</div>'
               f'<div class="fwd-r">{"".join(parts)}</div>{gline}</div>')
    # 年度 + 估值 stat 列
    stats = [("FY26", fmt(r["eps26"]) if is_eps(r["eps26"]) else "—"),
             ("FY27", fmt(r["eps27"]) if is_eps(r["eps27"]) else "—"),
             ("股價", fmt(r["price"]) if r["price"] else "—"),
             ("PE", fmt(r["pe"], 1) if r["pe"] else "—")]
    stat_html = "".join(f'<div class="stat"><div class="sl">{k}</div><div class="sv">{v}</div></div>' for k, v in stats)
    searchtxt = f"{t} {r['name']}".lower()
    return f"""<article class="card {scls}" data-t="{t}" data-stance="{r['stance']}" data-s="{searchtxt}">
 <header class="chead">
   <div class="ident"><span class="sym">{t}</span><span class="nm">{esc(r['name'])}</span></div>
   <span class="badge {scls}">{r['stance']}</span>
 </header>
 <div class="qtag">{esc(r['cur_q'] or '—')}<span class="qdot">已公布</span></div>
 <div class="metrics">{rev_hero}{eps_hero}</div>
 {fwd}
 <div class="stats">{stat_html}</div>
</article>"""


# ---------- Henry card ----------
def henry_card(h):
    t = h.get("ticker", "?")
    unit = ""  # Henry 金額自帶單位
    body = []
    if h.get("actual_rev") or h.get("cons_rev"):
        vs = []
        if h.get("cons_rev"): vs.append(f'共識 {h["cons_rev"]}')
        if h.get("buyside_rev"): vs.append(f'buyside {h["buyside_rev"]}')
        cons_label = "vs " + " · ".join(esc(x) for x in vs) if vs else ""
        body.append(f'<div class="metric"><div class="mlabel">營收</div>'
                    f'<div class="mbig">{esc(h.get("actual_rev") or "—")}</div>'
                    f'{("<div class=cons>"+cons_label+"</div>") if cons_label else ""}</div>')
    if h.get("actual_eps") or h.get("cons_eps"):
        cons = f'<span class="cons-inline">vs {esc(h["cons_eps"])}</span>' if h.get("cons_eps") else ""
        body.append(f'<div class="metric"><div class="mlabel">EPS</div>'
                    f'<div class="mbig sm">{esc(h.get("actual_eps") or "—")} {cons}</div></div>')
    guide = f'<div class="fwd"><div class="fwd-h">展望／指引</div><div class="gd">{esc(h.get("guide"))}</div></div>' if h.get("guide") else ""
    view = f'<blockquote class="cview">{esc(h.get("view"))}</blockquote>' if h.get("view") else ""
    src = f'{esc(h.get("src_label",""))} · {esc(h.get("src_date",""))}'
    searchtxt = f'{t} {h.get("company","")}'.lower()
    return f"""<article class="card s-henry" data-t="{t}" data-s="{searchtxt}">
 <header class="chead">
   <div class="ident"><span class="sym">{t}</span><span class="nm">{esc(h.get('company',''))}</span></div>
   <span class="badge s-henry">{esc(h.get('quarter','')) or 'Henry'}</span>
 </header>
 <div class="qtag src">{src}</div>
 <div class="metrics">{"".join(body)}</div>
 {guide}
 {view}
</article>"""


NAV = ('<nav class="topnav"><a href="index.html">📊 籌碼總覽</a>'
       '<a href="institutions.html">🏦 法人買賣超</a>'
       '<a href="us_earnings.html" class="on">📈 美股財報</a></nav>')


def build_html(data, henry, updated):
    allen_cards = "\n".join(allen_card(t, data[t]) for t in ORDER if t in data)
    henry_cards = "\n".join(henry_card(h) for h in henry) if henry else ""
    n = len(data)
    bull = sum(1 for r in data.values() if r["stance"] == "看多")
    bear = sum(1 for r in data.values() if r["stance"] == "偏空")
    ALIAS = {"GOOGL": "GOOG", "TSMC": "TSM"}
    henry_new = [h["ticker"] for h in henry
                 if ALIAS.get(h.get("ticker"), h.get("ticker")) not in ORDER] if henry else []
    henry_sec = ""
    if henry:
        henry_sec = f"""
<section class="src-block henry-block">
<div class="secthead"><h2><span class="dot">H</span>Henry · Pentimetrics</h2>
<span class="secsub">The Trace 券商彙整・市場（Bloomberg）共識與 buy side。{len(henry)} 檔，其中 <b>{len(henry_new)}</b> 檔為 cover list 未收。</span></div>
<div class="grid">
{henry_cards}
</div></section>"""
    return f"""<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>美股財報區 · Cover List</title>
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#f4f1ea">
<meta name="color-scheme" content="light">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="美股財報">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="icon" href="favicon.ico">
<style>
:root{{
  color-scheme:light;
  --bg:#f4f1ea; --bg2:#efeae0; --panel:#fffdf9; --ink:#232019; --ink2:#4a453b;
  --muted:#8f887a; --hair:#e7e1d5; --line:#ded7c8;
  --accent:#1a5e4a; --accent2:#c2410c;
  --beat:#1f7a4d; --beat-bg:#e6f2ea; --miss:#c0392b; --miss-bg:#fbeae7;
  --gd:#8a6d1f; --henry:#6d4bb8; --henry-bg:#efeaf8;
  --bull:#1f7a4d; --bear:#c0392b; --neu:#8f887a; --bullmid:#2563b8;
  --shadow:0 1px 2px rgba(60,50,30,.04),0 8px 24px rgba(60,50,30,.06);
  --serif:"Iowan Old Style","Palatino Linotype",Palatino,"Songti TC","Noto Serif TC",Georgia,serif;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;
  --mono:"SF Mono",ui-monospace,"Roboto Mono","DejaVu Sans Mono",Menlo,monospace;
}}
*{{box-sizing:border-box}}
html{{color-scheme:light}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
  -webkit-font-smoothing:antialiased;padding:20px 16px 56px;
  background-image:radial-gradient(circle at 1px 1px,rgba(120,105,75,.05) 1px,transparent 0);background-size:22px 22px}}
.wrap{{max-width:1240px;margin:0 auto}}
.topnav{{display:flex;gap:7px;margin:0 0 18px;flex-wrap:wrap}}
.topnav a{{font:600 13px var(--sans);color:var(--muted);text-decoration:none;padding:8px 15px;
  border-radius:11px;border:1px solid var(--hair);background:var(--panel);letter-spacing:.2px;box-shadow:var(--shadow)}}
.topnav a.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}

.masthead{{margin:0 0 6px;padding-bottom:16px;border-bottom:2.5px solid var(--ink)}}
h1{{font-family:var(--serif);font-size:31px;font-weight:600;margin:0 0 6px;letter-spacing:.2px;line-height:1.1}}
.lede{{color:var(--ink2);font-size:13px;margin:0;line-height:1.7;max-width:80ch}}
.lede b{{color:var(--ink);font-weight:700}}
.updated{{color:var(--muted);font-size:11.5px;margin-top:7px;font-family:var(--mono);letter-spacing:.3px}}

.kpis{{display:flex;gap:0;flex-wrap:wrap;margin:16px 0 6px;border:1px solid var(--hair);
  border-radius:14px;overflow:hidden;background:var(--panel);box-shadow:var(--shadow)}}
.kpi{{flex:1;min-width:120px;padding:13px 18px;border-right:1px solid var(--hair)}}
.kpi:last-child{{border-right:0}}
.kpi .v{{font-family:var(--serif);font-size:26px;font-weight:600;line-height:1}}
.kpi .l{{font-size:11px;color:var(--muted);margin-top:5px;letter-spacing:.3px}}

.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:20px 0 6px}}
.bar input{{font:500 13px var(--sans);color:var(--ink);background:var(--panel);
  border:1px solid var(--line);border-radius:10px;padding:9px 13px;box-shadow:var(--shadow);min-width:210px}}
.bar .chip{{cursor:pointer;color:var(--muted);border:1px solid var(--line);background:var(--panel);
  border-radius:20px;padding:7px 14px;font:600 12px var(--sans);box-shadow:var(--shadow);transition:all .12s}}
.bar .chip.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}

.secthead{{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin:30px 0 16px}}
.secthead h2{{font-family:var(--serif);font-size:20px;font-weight:600;margin:0;letter-spacing:.2px;
  display:flex;align-items:center;gap:10px}}
.secthead .dot{{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:8px;
  background:var(--accent);color:#fff;font:700 13px var(--sans)}}
.henry-block .secthead .dot{{background:var(--henry)}}
.secsub{{color:var(--muted);font-size:12px;line-height:1.5}} .secsub b{{color:var(--ink)}}

.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}}
.card{{position:relative;background:var(--panel);border:1px solid var(--hair);border-radius:16px;
  padding:20px 20px 16px;box-shadow:var(--shadow);overflow:hidden}}
.card::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--neu)}}
.card.s-bull::before{{background:var(--bull)}} .card.s-bullmid::before{{background:var(--bullmid)}}
.card.s-neu::before{{background:var(--neu)}} .card.s-bear::before{{background:var(--bear)}}
.card.s-watch::before{{background:var(--gd)}} .card.s-henry::before{{background:var(--henry)}}

.chead{{display:flex;align-items:center;gap:10px;margin-bottom:3px}}
.ident{{display:flex;align-items:baseline;gap:9px;margin-right:auto;min-width:0}}
.sym{{font-family:var(--serif);font-weight:700;font-size:21px;letter-spacing:.3px}}
.nm{{color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.badge{{padding:3px 11px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap;flex:none}}
.badge.s-bull{{background:var(--beat-bg);color:var(--bull)}}
.badge.s-bullmid{{background:#e7effb;color:var(--bullmid)}}
.badge.s-neu{{background:#efece5;color:var(--neu)}}
.badge.s-bear{{background:var(--miss-bg);color:var(--bear)}}
.badge.s-watch{{background:#f5edd8;color:var(--gd)}}
.badge.s-henry{{background:var(--henry-bg);color:var(--henry)}}
.qtag{{font-size:11px;color:var(--muted);letter-spacing:.4px;text-transform:uppercase;
  margin:0 0 15px;font-family:var(--mono)}}
.qtag .qdot{{margin-left:7px;padding-left:8px;border-left:1px solid var(--line)}}
.qtag.src{{text-transform:none;letter-spacing:.2px}}

.metrics{{display:flex;flex-direction:column;gap:16px}}
.metric{{}}
.mlabel{{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:1px;font-weight:700;margin-bottom:5px}}
.mbig{{font-family:var(--serif);font-size:27px;font-weight:600;line-height:1.05;
  font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}}
.mbig.sm{{font-size:20px}} .mbig.mut{{color:var(--muted);font-size:18px}}
.munit{{font-family:var(--sans);font-size:11px;color:var(--muted);font-weight:600;margin-left:-3px}}
.pill{{font-family:var(--sans);font-size:12px;font-weight:800;padding:2px 9px;border-radius:7px;letter-spacing:.2px}}
.pill.beat{{background:var(--beat-bg);color:var(--beat)}} .pill.miss{{background:var(--miss-bg);color:var(--miss)}}
.cbar{{position:relative;height:6px;background:var(--bg2);border-radius:4px;margin:9px 0 6px}}
.cmid{{position:absolute;left:50%;top:-2px;bottom:-2px;width:1.5px;background:var(--line)}}
.cf{{position:absolute;top:0;bottom:0;border-radius:4px}}
.cf.beat{{background:var(--beat)}} .cf.miss{{background:var(--miss)}}
.cons{{font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums}}
.cons-inline{{font-size:12px;color:var(--muted);font-weight:600;margin-left:4px}}

.fwd{{margin-top:16px;padding:12px 14px;background:var(--bg2);border-radius:11px}}
.fwd-h{{font-size:10.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;font-weight:700;margin-bottom:6px}}
.fwd-r{{display:flex;gap:16px;flex-wrap:wrap;font-size:13.5px;color:var(--ink2)}}
.fwd-r b{{color:var(--ink);font-weight:700;font-variant-numeric:tabular-nums}}
.gd{{font-size:12px;color:var(--gd);line-height:1.6;margin-top:6px}}
.fwd .gd{{margin-top:8px}}

.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;margin-top:16px;
  background:var(--line);border-radius:11px;overflow:hidden;border:1px solid var(--line)}}
.stat{{background:var(--panel);padding:9px 6px;text-align:center}}
.sl{{font-size:9.5px;color:var(--muted);letter-spacing:.5px;text-transform:uppercase;margin-bottom:3px}}
.sv{{font-family:var(--mono);font-size:13.5px;font-weight:600;font-variant-numeric:tabular-nums}}

.cview{{margin:15px 0 0;padding:12px 14px 12px 16px;background:var(--henry-bg);border-left:3px solid var(--henry);
  border-radius:0 10px 10px 0;font-size:12.5px;color:var(--ink2);line-height:1.72;font-style:normal}}
.cview::before{{content:"“";font-family:var(--serif);color:var(--henry);font-size:20px;line-height:0;
  margin-right:2px;vertical-align:-4px;opacity:.5}}

footer{{color:var(--muted);font-size:11.5px;text-align:center;margin-top:30px;line-height:1.8;
  padding-top:18px;border-top:1px solid var(--line)}}
@media(max-width:520px){{
  body{{padding:16px 12px 44px}} h1{{font-size:25px}}
  .grid{{grid-template-columns:1fr;gap:13px}} .kpi{{min-width:100px;padding:11px 13px}}
}}
</style></head><body><div class="wrap">
{NAV}
<div class="masthead">
<h1>美股財報區</h1>
<p class="lede">兩位分析師的美股財報數字，各自獨立呈現。<b>韭菜王 Allen</b>＝投資 cover list 模型（Allen 預估／Bloomberg 共識／實際／公司指引）；<b>Henry</b>＝Pentimetrics「The Trace」券商彙整與市場（Bloomberg）共識。營收單位為億、各檔原幣別。</p>
<div class="updated">UPDATED {updated}</div>
</div>
<div class="kpis">
 <div class="kpi"><div class="v">{n}</div><div class="l">Allen 覆蓋</div></div>
 <div class="kpi"><div class="v" style="color:var(--bull)">{bull}</div><div class="l">Allen 看多</div></div>
 <div class="kpi"><div class="v" style="color:var(--bear)">{bear}</div><div class="l">Allen 偏空</div></div>
 <div class="kpi"><div class="v" style="color:var(--henry)">{len(henry)}</div><div class="l">Henry 覆蓋</div></div>
</div>
<div class="bar">
 <input id="q" placeholder="🔍 搜尋代號／名稱…" oninput="flt()">
 <span class="chip on" data-s="all" onclick="pick(this)">全部立場</span>
 <span class="chip" data-s="看多" onclick="pick(this)">看多</span>
 <span class="chip" data-s="中性偏多" onclick="pick(this)">中性偏多</span>
 <span class="chip" data-s="中性" onclick="pick(this)">中性</span>
 <span class="chip" data-s="偏空" onclick="pick(this)">偏空</span>
</div>

<section class="src-block">
<div class="secthead"><h2><span class="dot">A</span>韭菜王 Allen · Cover List</h2>
<span class="secsub">每季財報模型・數字取自 cover list（股價／PE 隨 GOOGLEFINANCE 日更）。</span></div>
<div class="grid">
{allen_cards}
</div></section>
{henry_sec}

<footer>Allen 數字取自 cover list（AMZN 用營業利益、PANW 用 FCF 故 EPS 留「—」；ASML／NOK 歐元、聯發科台幣，其餘美元；GOOG 2Q26 EPS 含未實現利得故 Beat% 偏高）。<br>
Henry 數字為 Pentimetrics「The Trace」原文摘錄、標出處期號／日期；「市場預期」＝Bloomberg 共識，另附 buy side。數字一字不差、未明列者留空。<br>
Allen 區每日重跑更新；Henry 區為精選快照。© Evan 投資工作區</footer>
</div>
<script>
function pick(el){{document.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));el.classList.add('on');flt();}}
function flt(){{
  var q=document.getElementById('q').value.trim().toLowerCase();
  var s=document.querySelector('.chip.on').dataset.s;
  document.querySelectorAll('.card').forEach(function(c){{
    var okQ=(!q||c.dataset.s.indexOf(q)>=0);
    var okS=(s==='all'||!c.dataset.stance||c.dataset.stance===s);
    c.style.display=(okQ&&okS)?'':'none';
  }});
  document.querySelectorAll('.src-block').forEach(function(b){{
    var any=[].some.call(b.querySelectorAll('.card'),x=>x.style.display!=='none');
    b.style.display=any?'':'none';
  }});
}}
</script>
</body></html>"""


def main():
    wbd, wbf = load_wb()
    data = extract(wbd, wbf)
    henry = []
    hp = ROOT / "henry_data.json"
    if hp.exists():
        try:
            henry = json.loads(hp.read_text(encoding="utf-8"))
        except Exception as e:
            print("henry_data.json parse fail:", e)
    updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    (ROOT / "us_earnings.html").write_text(build_html(data, henry, updated), encoding="utf-8")
    print(f"wrote us_earnings.html  (Allen {len(data)} / Henry {len(henry)})")


if __name__ == "__main__":
    main()
