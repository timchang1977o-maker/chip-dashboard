#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""美股財報區 — 從投資 cover list（Google Sheet）抓每檔的財報預測/實際數字，
產出自含靜態頁 us_earnings.html，掛進 chip-dashboard（GitHub Pages）。

資料來源：cover list sheet（link-可讀，無需登入）
  https://docs.google.com/spreadsheets/d/<ID>/export?format=xlsx
每檔分頁固定 B-M 12 欄結構（見 memory project_cover_list_sheet）：
  row2 季度標頭 / row5 Revenue / row9 EPS / row11-17 年度 / row19-24 估值
欄位對應（固定）：B-E 歷史(A)｜F=本季Allen G=本季共識 H=本季實際｜
  I=下季Allen J=下季共識 K=下季公司指引｜L=下下季Allen M=下下季共識

用法：python3 build_us_earnings.py   （會自動下載最新 sheet）
      python3 build_us_earnings.py local.xlsx  （用本機檔，離線）
"""
import sys, json, io, datetime, html, urllib.request
import openpyxl

SHEET_ID = "1Hfb1eX23xCbGMYOh-76_DjpAgwl7-8DG8TjbtxqZRD4"
EXPORT = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 只收 Allen 覆蓋、且分頁有維護的（跳過空殼 CRDO/ALAB/ANET/FN、落後不更新的 ORCL）
# 名稱／立場／中文取自 kb/INDEX.md（最新一季論點）
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


def load_wb():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        return (openpyxl.load_workbook(path, data_only=True),
                openpyxl.load_workbook(path, data_only=False))
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
        cur_q = lab("F").replace("(E)", "")
        rec = {
            "name": META[t][0], "stance": META[t][1], "date": META[t][2],
            "unit": unit, "cur_q": cur_q,
            "act_rev": num(c("H", 5)), "cons_rev": num(c("G", 5)), "est_rev": num(c("F", 5)),
            "act_eps": num(c("H", 9)), "cons_eps": num(c("G", 9)), "est_eps": num(c("F", 9)),
            "n_q": lab("I").replace("(E)", ""),
            "n_est_rev": num(c("I", 5)), "n_cons_rev": num(c("J", 5)),
            "n_est_eps": num(c("I", 9)), "n_cons_eps": num(c("J", 9)),
            "guid": c("K", 5),
            "eps26": num(c("F", 17)), "eps26c": num(c("G", 17)),
            "eps27": num(c("H", 17)), "eps27c": num(c("I", 17)),
            "rev26": num(c("F", 13)), "rev27": num(c("H", 13)),
        }
        # 價格：掃 row19-21 找 GOOGLEFINANCE 算出的數字（避開偏移分頁）
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
        # 前瞻本益比：優先用 sheet 算好的 C19（0<pe<200），否則自算 price/eps26
        pe = num(wd["C19"].value)
        if not (pe and 0 < pe < 200):
            pe = (price / rec["eps26"]) if (price and rec["eps26"] and 0 < rec["eps26"] < 500) else None
        rec["pe"] = pe
        data[t] = rec
    return data


def is_eps(v):
    return isinstance(v, (int, float)) and abs(v) < 500  # 濾掉 AMZN 用營業利益的巨值


def fmt_bil(v):
    """百萬 → 億，1 位小數"""
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v/100:,.1f}"


def fmt(v, d=2):
    if not isinstance(v, (int, float)):
        return "—"
    return f"{v:,.{d}f}"


def pct(a, b):
    if not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and b):
        return None
    return (a / b - 1) * 100


STANCE_CLS = {"看多": "s-bull", "中性偏多": "s-bullmid", "中性": "s-neu",
              "偏空": "s-bear", "追蹤": "s-watch"}


def beat_cell(act, cons, is_pct_eps=False):
    """回傳 (顯示字串, class)。act vs cons 判 beat/miss。"""
    if not isinstance(act, (int, float)):
        return ("待公布", "")
    p = pct(act, cons)
    if p is None:
        return ("—", "")
    cls = "beat" if p >= 0 else "miss"
    tag = "▲" if p >= 0 else "▼"
    return (f"{tag}{abs(p):.1f}%", cls)


def row_html(t, r):
    scls = STANCE_CLS.get(r["stance"], "s-neu")
    cur = r["cur_q"] or "—"
    # 營收（億，native 幣別）
    act_rev = fmt_bil(r["act_rev"])
    cons_rev = fmt_bil(r["cons_rev"])
    rev_tag, rev_cls = beat_cell(r["act_rev"], r["cons_rev"])
    # EPS
    if is_eps(r["act_eps"]):
        act_eps = fmt(r["act_eps"])
        cons_eps = fmt(r["cons_eps"])
        eps_tag, eps_cls = beat_cell(r["act_eps"], r["cons_eps"])
    else:
        act_eps = cons_eps = "—"
        eps_tag, eps_cls = ("—", "")
    # 下季
    nq = r["n_q"] or "—"
    n_est_rev = fmt_bil(r["n_est_rev"])
    n_est_eps = fmt(r["n_est_eps"]) if is_eps(r["n_est_eps"]) else "—"
    guid = r["guid"] if isinstance(r["guid"], str) else (fmt_bil(r["guid"]) if isinstance(r["guid"], (int, float)) else "—")
    # 年度 EPS
    eps26 = fmt(r["eps26"]) if is_eps(r["eps26"]) else "—"
    eps27 = fmt(r["eps27"]) if is_eps(r["eps27"]) else "—"
    price = fmt(r["price"]) if r["price"] else "—"
    pe = fmt(r["pe"], 1) if r["pe"] else "—"
    unit = r["unit"] or "USD"

    # data-* 供排序/篩選
    sort_pe = r["pe"] if r["pe"] else -1
    sort_rev = pct(r["act_rev"], r["cons_rev"])
    sort_rev = sort_rev if sort_rev is not None else -999
    return f"""<tr data-t="{t}" data-stance="{r['stance']}" data-pe="{sort_pe}" data-beat="{sort_rev}">
 <td class="tk"><span class="sym">{t}</span><span class="nm">{html.escape(r['name'])}</span></td>
 <td><span class="badge {scls}">{r['stance']}</span></td>
 <td class="q">{cur}</td>
 <td class="n">{act_rev}<span class="u">億{unit}</span></td>
 <td class="n mut">{cons_rev}</td>
 <td class="n {rev_cls}">{rev_tag}</td>
 <td class="n">{act_eps}</td>
 <td class="n {eps_cls}">{eps_tag}</td>
 <td class="q">{nq}</td>
 <td class="n">{n_est_rev}</td>
 <td class="n">{n_est_eps}</td>
 <td class="n gd">{html.escape(str(guid))}</td>
 <td class="n">{eps26}</td>
 <td class="n">{eps27}</td>
 <td class="n">{price}</td>
 <td class="n pe">{pe}</td>
</tr>"""


NAV = ('<nav class="topnav"><a href="index.html">📊 籌碼總覽</a>'
       '<a href="institutions.html">🏦 法人買賣超</a>'
       '<a href="us_earnings.html" class="on">📈 美股財報</a></nav>')


def build_html(data, updated):
    rows = "\n".join(row_html(t, data[t]) for t in ORDER if t in data)
    n = len(data)
    bull = sum(1 for r in data.values() if r["stance"] == "看多")
    bear = sum(1 for r in data.values() if r["stance"] == "偏空")
    beats = sum(1 for r in data.values()
                if isinstance(r["act_rev"], (int, float)) and isinstance(r["cons_rev"], (int, float))
                and r["act_rev"] >= r["cons_rev"])
    return f"""<!doctype html><html lang="zh-Hant"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>美股財報區 · Cover List</title>
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#eef1f5">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="美股財報">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="icon" href="favicon.ico">
<style>
:root{{
  --bg:#eef1f5; --panel:#fff; --ink:#1a2230; --muted:#6b7686; --hair:#e4e8ee;
  --fill:#3d7bf0; --beat:#1f9d57; --miss:#d0342c; --gd:#8a6d1f;
  --shadow:0 1px 2px rgba(20,30,50,.05),0 6px 20px rgba(20,30,50,.06);
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;
}}
@media (prefers-color-scheme:dark){{:root{{
  --bg:#0e1218; --panel:#161c26; --ink:#e8edf4; --muted:#8b97a8; --hair:#242c38;
  --fill:#4d89ff; --beat:#25c274; --miss:#ff5a4d; --gd:#d9b45a;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.35);
}}}}
:root[data-theme="light"]{{--bg:#eef1f5;--panel:#fff;--ink:#1a2230;--muted:#6b7686;--hair:#e4e8ee;--fill:#3d7bf0;--beat:#1f9d57;--miss:#d0342c;--gd:#8a6d1f;}}
:root[data-theme="dark"]{{--bg:#0e1218;--panel:#161c26;--ink:#e8edf4;--muted:#8b97a8;--hair:#242c38;--fill:#4d89ff;--beat:#25c274;--miss:#ff5a4d;--gd:#d9b45a;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  -webkit-font-smoothing:antialiased;padding:16px 14px 40px}}
.wrap{{max-width:1180px;margin:0 auto}}
.topnav{{display:flex;gap:6px;margin:0 2px 14px;flex-wrap:wrap}}
.topnav a{{font:600 13px var(--font);color:var(--muted);text-decoration:none;padding:7px 14px;
  border-radius:10px;border:1px solid var(--hair);background:var(--panel);letter-spacing:.2px;
  box-shadow:var(--shadow)}}
.topnav a.on{{background:var(--fill);color:#fff;border-color:var(--fill)}}
h1{{font-size:19px;margin:2px 2px 3px;letter-spacing:.3px}}
.sub{{color:var(--muted);font-size:12.5px;margin:0 2px 14px}}
.sub b{{color:var(--ink)}}
.kpis{{display:flex;gap:9px;flex-wrap:wrap;margin:0 0 14px}}
.kpi{{background:var(--panel);border:1px solid var(--hair);border-radius:12px;padding:9px 14px;
  box-shadow:var(--shadow)}}
.kpi .v{{font-size:19px;font-weight:750}}
.kpi .l{{font-size:11px;color:var(--muted)}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 2px 10px}}
.bar input,.bar select{{font:600 12.5px var(--font);color:var(--ink);background:var(--panel);
  border:1px solid var(--hair);border-radius:9px;padding:7px 11px;box-shadow:var(--shadow)}}
.bar .chip{{cursor:pointer;color:var(--muted);border:1px solid var(--hair);background:var(--panel);
  border-radius:20px;padding:5px 12px;font:600 12px var(--font);box-shadow:var(--shadow)}}
.bar .chip.on{{background:var(--fill);color:#fff;border-color:var(--fill)}}
.card{{background:var(--panel);border:1px solid var(--hair);border-radius:14px;
  box-shadow:var(--shadow);overflow:hidden}}
.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;min-width:1050px;font-size:13px}}
thead th{{position:sticky;top:0;background:var(--panel);z-index:2;text-align:right;
  padding:9px 8px;border-bottom:2px solid var(--hair);color:var(--muted);font-size:11px;
  font-weight:700;white-space:nowrap;cursor:pointer;user-select:none}}
thead th.l{{text-align:left}} thead th.grp{{color:var(--fill)}}
thead th:hover{{color:var(--ink)}}
tbody td{{padding:9px 8px;border-bottom:1px solid var(--hair);text-align:right;white-space:nowrap}}
tbody tr:hover{{background:rgba(61,123,240,.05)}}
.tk{{text-align:left!important}}
.sym{{font-weight:750;font-size:13.5px}} .nm{{color:var(--muted);font-size:11px;margin-left:7px}}
.n{{font-variant-numeric:tabular-nums}} .mut{{color:var(--muted)}}
.q{{color:var(--muted);font-size:12px;text-align:center!important}}
.u{{font-size:9.5px;color:var(--muted);margin-left:2px;font-weight:600}}
.beat{{color:var(--beat);font-weight:700}} .miss{{color:var(--miss);font-weight:700}}
.gd{{color:var(--gd);font-size:11.5px}}
.pe{{font-weight:700}}
.badge{{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:700;white-space:nowrap}}
.s-bull{{background:rgba(31,157,87,.14);color:var(--beat)}}
.s-bullmid{{background:rgba(61,123,240,.14);color:var(--fill)}}
.s-neu{{background:rgba(120,130,145,.16);color:var(--muted)}}
.s-bear{{background:rgba(208,52,44,.14);color:var(--miss)}}
.s-watch{{background:rgba(180,140,20,.16);color:var(--gd)}}
.grpr th{{background:var(--bg)!important;border-bottom:1px solid var(--hair);padding:5px 8px;
  font-size:10px;color:var(--muted);text-align:center;position:static;top:auto;cursor:default}}
footer{{color:var(--muted);font-size:11.5px;text-align:center;margin-top:18px;line-height:1.7}}
</style></head><body><div class="wrap">
{NAV}
<h1>📈 美股財報區</h1>
<p class="sub">資料來源＝投資 <b>cover list</b> 試算表（韭菜王 Allen 每季財報模型：Allen 預估／Bloomberg 共識／實際結果／公司指引）。
最新已公布季的實際值 vs 共識判 <span class="beat">Beat</span>／<span class="miss">Miss</span>；營收單位＝億（各檔原幣別）。更新於 <b>{updated}</b>。</p>
<div class="kpis">
 <div class="kpi"><div class="v">{n}</div><div class="l">覆蓋檔數</div></div>
 <div class="kpi"><div class="v" style="color:var(--beat)">{bull}</div><div class="l">Allen 看多</div></div>
 <div class="kpi"><div class="v" style="color:var(--miss)">{bear}</div><div class="l">Allen 偏空</div></div>
 <div class="kpi"><div class="v">{beats}<span style="font-size:12px;color:var(--muted)">/{n}</span></div><div class="l">最新季營收 Beat 共識</div></div>
</div>
<div class="bar">
 <input id="q" placeholder="🔍 搜尋代號／名稱…" oninput="flt()">
 <span class="chip on" data-s="all" onclick="pick(this)">全部</span>
 <span class="chip" data-s="看多" onclick="pick(this)">看多</span>
 <span class="chip" data-s="中性偏多" onclick="pick(this)">中性偏多</span>
 <span class="chip" data-s="中性" onclick="pick(this)">中性</span>
 <span class="chip" data-s="偏空" onclick="pick(this)">偏空</span>
</div>
<div class="card"><div class="scroll"><table id="tb">
<thead>
<tr class="grpr">
  <th colspan="2"></th><th colspan="6" class="l">最新已公布季（實際 vs 共識）</th>
  <th colspan="4" class="l">下一季預估</th><th colspan="2" class="l">年度 non-GAAP EPS</th><th colspan="2" class="l">估值</th>
</tr>
<tr>
 <th class="l" onclick="sortby('t')">標的</th>
 <th class="l">立場</th>
 <th>季別</th>
 <th onclick="sortby('beat')">實際營收</th>
 <th>共識營收</th>
 <th onclick="sortby('beat')">營收<br>Beat/Miss</th>
 <th>實際 EPS</th>
 <th>EPS<br>Beat/Miss</th>
 <th>季別</th>
 <th>Allen 營收</th>
 <th>Allen EPS</th>
 <th>公司指引<br>(營收)</th>
 <th>FY26</th>
 <th>FY27</th>
 <th>股價</th>
 <th onclick="sortby('pe')">PE<br>(本益比)</th>
</tr>
</thead>
<tbody>
{rows}
</tbody></table></div></div>
<footer>數字一字不差取自 cover list（韭菜王 Allen 模型）。營收＝百萬換算億、各檔原幣別（ASML／NOK 歐元、聯發科 台幣，其餘美元）。<br>
AMZN 因模型用營業利益、PANW 用 FCF，此處 EPS 欄留「—」。「待公布」＝該季尚未發財報。PE＝股價 ÷ cover list 底部估值列 EPS（各檔依該分頁設定，多為 FY26）。<br>
本頁為 cover list 快照，每次重跑 build_us_earnings.py 更新。© Evan 投資工作區</footer>
</div>
<script>
var sortState={{}};
function pick(el){{document.querySelectorAll('.chip').forEach(c=>c.classList.remove('on'));el.classList.add('on');flt();}}
function flt(){{
  var q=document.getElementById('q').value.trim().toLowerCase();
  var s=document.querySelector('.chip.on').dataset.s;
  document.querySelectorAll('#tb tbody tr').forEach(function(tr){{
    var okS=(s==='all'||tr.dataset.stance===s);
    var txt=(tr.dataset.t+' '+tr.querySelector('.nm').textContent).toLowerCase();
    var okQ=(!q||txt.indexOf(q)>=0);
    tr.style.display=(okS&&okQ)?'':'none';
  }});
}}
function sortby(key){{
  var tb=document.querySelector('#tb tbody');
  var rows=[].slice.call(tb.querySelectorAll('tr'));
  var dir=sortState[key]=(sortState[key]===1?-1:1);
  rows.sort(function(a,b){{
    var va,vb;
    if(key==='t'){{va=a.dataset.t;vb=b.dataset.t;return dir*va.localeCompare(vb);}}
    va=parseFloat(a.dataset[key]);vb=parseFloat(b.dataset[key]);
    return dir*((va||-1e9)-(vb||-1e9));
  }});
  rows.forEach(function(r){{tb.appendChild(r);}});
}}
</script>
</body></html>"""


def main():
    wbd, wbf = load_wb()
    data = extract(wbd, wbf)
    updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    from pathlib import Path
    out = Path(__file__).resolve().parent / "us_earnings.html"
    out.write_text(build_html(data, updated), encoding="utf-8")
    print(f"wrote {out}  ({len(data)} tickers)")


if __name__ == "__main__":
    main()
