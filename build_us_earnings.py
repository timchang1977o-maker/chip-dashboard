#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股財報區 — 兩個獨立來源合成一頁 us_earnings.html（chip-dashboard / GitHub Pages）。

來源 A｜韭菜王 Allen：投資 cover list（Google Sheet，link-可讀免登入）
  export?format=xlsx → openpyxl。每分頁固定 B-M 12 欄（見 memory project_cover_list_sheet）：
  row2 季度標頭 / row5 Revenue / row9 EPS / row11-17 年度 / row19-24 估值
  欄位對應：B-E 歷史(A)｜F=本季Allen G=共識 H=實際｜I/J=下季｜K=下季指引｜L/M=下下季
來源 B｜Henry(Pentimetrics)：curated henry_data.json（由 pentimetrics_db 精準抽取，見 build 說明）

風格：強制淺色（Evan 的 Mac 深色模式，交付物一律淺色）。兩來源各自獨立卡片區塊。

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

# 只收 Allen 覆蓋、且分頁有維護的（跳過空殼 CRDO/ALAB/ANET/FN、落後不更新的 ORCL）
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


# ---------- Allen card ----------
def allen_card(t, r):
    scls = STANCE_CLS.get(r["stance"], "s-neu")
    unit = r["unit"] or "USD"
    # 最新季 beat/miss
    rp = pct(r["act_rev"], r["cons_rev"])
    rev_line = ""
    if bil(r["act_rev"]):
        tag = ("beat", f"▲{rp:.1f}%") if (rp is not None and rp >= 0) else \
              ("miss", f"▼{abs(rp):.1f}%") if rp is not None else ("", "")
        cons = f'<span class="vs">vs 共識 {bil(r["cons_rev"])}</span>' if bil(r["cons_rev"]) else ""
        badge = f'<span class="{tag[0]}">{tag[1]}</span>' if tag[1] else ""
        rev_line = (f'<div class="mrow"><span class="k">實際營收</span>'
                    f'<span class="val">{bil(r["act_rev"])}<i>億{unit}</i> {badge}</span></div>'
                    f'{("<div class=sub2>"+cons+"</div>") if cons else ""}')
    else:
        rev_line = '<div class="mrow"><span class="k">最新季</span><span class="val mut">待公布</span></div>'
    # EPS beat/miss
    eps_line = ""
    if is_eps(r["act_eps"]):
        ep = pct(r["act_eps"], r["cons_eps"])
        etag = ("beat", f"▲{ep:.1f}%") if (ep is not None and ep >= 0) else \
               ("miss", f"▼{abs(ep):.1f}%") if ep is not None else ("", "")
        eb = f'<span class="{etag[0]}">{etag[1]}</span>' if etag[1] else ""
        econs = f'<span class="vs">vs {fmt(r["cons_eps"])}</span>' if is_eps(r["cons_eps"]) else ""
        eps_line = (f'<div class="mrow"><span class="k">EPS</span>'
                    f'<span class="val">{fmt(r["act_eps"])} {eb}</span></div>'
                    f'{("<div class=sub2>"+econs+"</div>") if econs else ""}')
    # 下季
    nq = r["n_q"] or ""
    nrev = bil(r["n_est_rev"]); neps = fmt(r["n_est_eps"]) if is_eps(r["n_est_eps"]) else None
    guid = r["guid"] if isinstance(r["guid"], str) else (bil(r["guid"]) if isinstance(r["guid"], (int, float)) else None)
    next_line = ""
    if nrev or neps:
        parts = []
        if nrev: parts.append(f"營收 {nrev}")
        if neps: parts.append(f"EPS {neps}")
        next_line = f'<div class="mrow"><span class="k">下季 {esc(nq)}</span><span class="val sm">{" · ".join(parts)}</span></div>'
    guid_line = f'<div class="mrow"><span class="k">公司指引</span><span class="val sm gd">{esc(guid)}</span></div>' if guid else ""
    # 年度 + 估值
    eps26 = fmt(r["eps26"]) if is_eps(r["eps26"]) else "—"
    eps27 = fmt(r["eps27"]) if is_eps(r["eps27"]) else "—"
    price = fmt(r["price"]) if r["price"] else "—"
    pe = fmt(r["pe"], 1) if r["pe"] else "—"
    foot = (f'<div class="cfoot"><span>FY26 <b>{eps26}</b></span><span>FY27 <b>{eps27}</b></span>'
            f'<span>股價 <b>{price}</b></span><span>PE <b>{pe}</b></span></div>')
    searchtxt = f"{t} {r['name']}".lower()
    return f"""<div class="card" data-t="{t}" data-stance="{r['stance']}" data-s="{searchtxt}">
 <div class="chead"><span class="sym">{t}</span><span class="nm">{esc(r['name'])}</span>
   <span class="badge {scls}">{r['stance']}</span></div>
 <div class="qtag">{esc(r['cur_q'] or '—')} 已公布</div>
 {rev_line}{eps_line}{next_line}{guid_line}
 {foot}
</div>"""


# ---------- Henry card ----------
def henry_card(h):
    t = h.get("ticker", "?")
    rows = []
    def mrow(k, v, cls=""):
        return f'<div class="mrow"><span class="k">{esc(k)}</span><span class="val {cls}">{esc(v)}</span></div>' if v else ""
    # 營收 / EPS 三方
    if h.get("actual_rev") or h.get("cons_rev"):
        rv = h.get("actual_rev") or "—"
        vs = []
        if h.get("cons_rev"): vs.append(f'共識 {h["cons_rev"]}')
        if h.get("buyside_rev"): vs.append(f'buyside {h["buyside_rev"]}')
        rows.append(f'<div class="mrow"><span class="k">營收</span><span class="val">{esc(rv)}</span></div>')
        if vs: rows.append(f'<div class="sub2"><span class="vs">vs {" · ".join(esc(x) for x in vs)}</span></div>')
    if h.get("actual_eps") or h.get("cons_eps"):
        ev = h.get("actual_eps") or "—"
        rows.append(f'<div class="mrow"><span class="k">EPS</span><span class="val">{esc(ev)}'
                    f'{(" <span class=vs>vs "+esc(h["cons_eps"])+"</span>") if h.get("cons_eps") else ""}</span></div>')
    rows.append(mrow("展望/指引", h.get("guide"), "sm gd"))
    view = f'<div class="cview">「{esc(h.get("view"))}」</div>' if h.get("view") else ""
    src = f'{esc(h.get("src_label",""))} · {esc(h.get("src_date",""))}'
    searchtxt = f'{t} {h.get("company","")}'.lower()
    return f"""<div class="card" data-t="{t}" data-s="{searchtxt}">
 <div class="chead"><span class="sym">{t}</span><span class="nm">{esc(h.get('company',''))}</span>
   <span class="badge s-henry">{esc(h.get('quarter','')) or 'Henry'}</span></div>
 <div class="qtag">{src}</div>
 {"".join(rows)}
 {view}
</div>"""


NAV = ('<nav class="topnav"><a href="index.html">📊 籌碼總覽</a>'
       '<a href="institutions.html">🏦 法人買賣超</a>'
       '<a href="us_earnings.html" class="on">📈 美股財報</a></nav>')


def build_html(data, henry, updated):
    allen_cards = "\n".join(allen_card(t, data[t]) for t in ORDER if t in data)
    henry_cards = "\n".join(henry_card(h) for h in henry) if henry else ""
    n = len(data)
    bull = sum(1 for r in data.values() if r["stance"] == "看多")
    bear = sum(1 for r in data.values() if r["stance"] == "偏空")
    ALIAS = {"GOOGL": "GOOG", "TSMC": "TSM"}  # Henry 用字對映 cover list ticker
    henry_new = [h["ticker"] for h in henry
                 if ALIAS.get(h.get("ticker"), h.get("ticker")) not in ORDER] if henry else []
    henry_sec = ""
    if henry:
        henry_sec = f"""
<div class="secthead" id="henry"><h2>🅗 Henry · Pentimetrics</h2>
<span class="secsub">The Trace 券商彙整／市場（Bloomberg）共識・buy side。{len(henry)} 檔，其中 <b>{len(henry_new)}</b> 檔為 cover list 未收。</span></div>
<div class="grid">
{henry_cards}
</div>"""
    return f"""<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>美股財報區 · Cover List</title>
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#eef1f5">
<meta name="color-scheme" content="light">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="美股財報">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="icon" href="favicon.ico">
<style>
/* 強制淺色（Evan Mac 深色模式，交付物一律淺色） */
:root{{
  color-scheme:light;
  --bg:#eef1f5; --panel:#fff; --panel2:#f7f9fc; --ink:#1a2230; --muted:#6b7686; --hair:#e4e8ee;
  --fill:#3d7bf0; --beat:#1f9d57; --miss:#d0342c; --gd:#8a6d1f; --henry:#7a52d8;
  --shadow:0 1px 2px rgba(20,30,50,.05),0 6px 20px rgba(20,30,50,.06);
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;
}}
*{{box-sizing:border-box}}
html{{color-scheme:light}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  -webkit-font-smoothing:antialiased;padding:16px 14px 44px}}
.wrap{{max-width:1180px;margin:0 auto}}
.topnav{{display:flex;gap:6px;margin:0 2px 14px;flex-wrap:wrap}}
.topnav a{{font:600 13px var(--font);color:var(--muted);text-decoration:none;padding:7px 14px;
  border-radius:10px;border:1px solid var(--hair);background:var(--panel);letter-spacing:.2px;box-shadow:var(--shadow)}}
.topnav a.on{{background:var(--fill);color:#fff;border-color:var(--fill)}}
h1{{font-size:19px;margin:2px 2px 3px;letter-spacing:.3px}}
.sub{{color:var(--muted);font-size:12.5px;margin:0 2px 14px;line-height:1.6}}
.sub b{{color:var(--ink)}}
.kpis{{display:flex;gap:9px;flex-wrap:wrap;margin:0 0 14px}}
.kpi{{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:9px 14px;box-shadow:var(--shadow)}}
.kpi .v{{font-size:19px;font-weight:750}} .kpi .l{{font-size:11px;color:var(--muted)}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 2px 16px}}
.bar input{{font:600 12.5px var(--font);color:var(--ink);background:var(--panel);
  border:1px solid var(--hair);border-radius:9px;padding:8px 12px;box-shadow:var(--shadow);min-width:200px}}
.bar .chip{{cursor:pointer;color:var(--muted);border:1px solid var(--hair);background:var(--panel);
  border-radius:20px;padding:6px 13px;font:600 12px var(--font);box-shadow:var(--shadow)}}
.bar .chip.on{{background:var(--fill);color:#fff;border-color:var(--fill)}}
.secthead{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin:22px 2px 12px;
  padding-bottom:9px;border-bottom:2px solid var(--hair)}}
.secthead h2{{font-size:16px;margin:0;letter-spacing:.3px}}
.secsub{{color:var(--muted);font-size:12px}} .secsub b{{color:var(--ink)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}}
.card{{background:var(--panel);border:1px solid var(--hair);border-radius:14px;padding:13px 15px 12px;
  box-shadow:var(--shadow);display:flex;flex-direction:column;gap:5px}}
.chead{{display:flex;align-items:center;gap:8px;margin-bottom:2px}}
.sym{{font-weight:800;font-size:15px;letter-spacing:.3px}}
.nm{{color:var(--muted);font-size:11.5px;margin-right:auto}}
.badge{{padding:2px 9px;border-radius:20px;font-size:10.5px;font-weight:700;white-space:nowrap}}
.s-bull{{background:rgba(31,157,87,.14);color:var(--beat)}}
.s-bullmid{{background:rgba(61,123,240,.14);color:var(--fill)}}
.s-neu{{background:rgba(120,130,145,.16);color:var(--muted)}}
.s-bear{{background:rgba(208,52,44,.14);color:var(--miss)}}
.s-watch{{background:rgba(180,140,20,.16);color:var(--gd)}}
.s-henry{{background:rgba(122,82,216,.14);color:var(--henry)}}
.qtag{{font-size:11px;color:var(--muted);margin:-2px 0 4px}}
.mrow{{display:flex;justify-content:space-between;align-items:baseline;gap:10px;font-size:13px}}
.mrow .k{{color:var(--muted);font-size:11.5px;white-space:nowrap}}
.mrow .val{{font-weight:700;font-variant-numeric:tabular-nums;text-align:right}}
.mrow .val.sm{{font-weight:600;font-size:12px}} .mrow .val.mut{{color:var(--muted);font-weight:600}}
.val i{{font-style:normal;font-size:9.5px;color:var(--muted);margin-left:1px;font-weight:600}}
.sub2{{text-align:right;margin:-3px 0 1px}} .vs{{color:var(--muted);font-size:10.5px;font-weight:600}}
.beat{{color:var(--beat);font-weight:800;font-size:11.5px;margin-left:3px}}
.miss{{color:var(--miss);font-weight:800;font-size:11.5px;margin-left:3px}}
.gd{{color:var(--gd)!important}}
.cfoot{{display:flex;flex-wrap:wrap;gap:4px 14px;margin-top:7px;padding-top:8px;
  border-top:1px solid var(--hair);font-size:11px;color:var(--muted)}}
.cfoot b{{color:var(--ink);font-weight:700}}
.cview{{margin-top:6px;padding-top:7px;border-top:1px solid var(--hair);
  font-size:11.5px;color:var(--ink);line-height:1.55}}
.empty{{color:var(--muted);font-size:12.5px;padding:14px 2px}}
footer{{color:var(--muted);font-size:11.5px;text-align:center;margin-top:24px;line-height:1.7}}
</style></head><body><div class="wrap">
{NAV}
<h1>📈 美股財報區</h1>
<p class="sub">兩位分析師的美股財報數字，各自獨立。<b>韭菜王 Allen</b>＝投資 cover list 模型（Allen 預估／Bloomberg 共識／實際／公司指引）；<b>Henry</b>＝Pentimetrics「The Trace」券商彙整與市場（Bloomberg）共識。營收單位＝億（各檔原幣別）。更新 <b>{updated}</b>。</p>
<div class="kpis">
 <div class="kpi"><div class="v">{n}</div><div class="l">Allen 覆蓋</div></div>
 <div class="kpi"><div class="v" style="color:var(--beat)">{bull}</div><div class="l">Allen 看多</div></div>
 <div class="kpi"><div class="v" style="color:var(--miss)">{bear}</div><div class="l">Allen 偏空</div></div>
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

<div class="secthead" id="allen"><h2>🅐 韭菜王 Allen · Cover List</h2>
<span class="secsub">每季財報模型・數字取自 cover list（股價/PE 隨 GOOGLEFINANCE 日更）。</span></div>
<div class="grid" id="allenGrid">
{allen_cards}
</div>
{henry_sec}

<footer>Allen 數字取自 cover list（AMZN 用營業利益、PANW 用 FCF 故 EPS 留「—」；ASML/NOK 歐元、聯發科台幣，其餘美元；GOOG 2Q26 EPS 含未實現利得故 Beat% 偏高）。<br>
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
    // 立場篩選只作用於 Allen 卡（有 data-stance）；Henry 卡不受立場影響、只受搜尋
    var okS=(s==='all'||!c.dataset.stance||c.dataset.stance===s);
    c.style.display=(okQ&&okS)?'':'none';
  }});
  // 區塊全空時整段淡化
  document.querySelectorAll('.grid').forEach(function(g){{
    var any=[].some.call(g.querySelectorAll('.card'),x=>x.style.display!=='none');
    g.style.opacity=any?'1':'.4';
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
