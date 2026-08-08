#!/usr/bin/env python3
"""台股籌碼儀表板 pipeline — TAIFEX 三大法人期/選未平倉 + TWSE 三大法人現貨買賣超/融資餘額。

五個面板（對齊財經 M 平方風格）：
  ① 臺股期貨·三大法人未平倉淨口數（外資/投信/自營）  ← TAIFEX futContractsDate
  ② 三大法人·現貨買賣超（外資/投信/自營，億元·日）   ← TWSE BFI82U 三大法人買賣金額
  ③ 台指期近月收盤價                                  ← TAIFEX futDataDown（TX 一般盤近月）
  ④ 台指選擇權·外資未平倉淨口數（CALL/PUT）          ← TAIFEX callsAndPutsDate
  ⑤ 上市融資餘額（億元·日）                           ← TWSE MI_MARGN 市場合計

頂部另有「連續方向」KPI：外資期貨部位淨多/淨空、加多/加空連續天數，
及外資/投信/自營現貨連買/連賣連續天數（前端即時由 futures/institutions 算）。

用法：
    python3 chip_tracker.py                 # 全抓 2 年區間 → data.json + 籌碼儀表板.html
    python3 chip_tracker.py --from-cache    # 用既有 data.json 只重繪 HTML
    python3 chip_tracker.py --years 2       # 抓幾年（預設 2）

資料全部來自官方免費端點，無需 token；台指期日行情有 ~31 天區間上限故分段抓。
"""
import urllib.request
import urllib.parse
import json
import datetime
import time
import sys
import os
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE.parent / "chip_reports"
DATA_PATH = HERE / "chip_data.json"


# ----------------------------- helpers -----------------------------
def _post(url, form):
    raw = urllib.request.urlopen(
        urllib.request.Request(url, data=urllib.parse.urlencode(form).encode(), headers=UA),
        timeout=90,
    ).read()
    for enc in ("utf-8-sig", "big5", "cp950", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25).read()


def _I(s):
    s = str(s).replace(",", "").strip()
    return 0 if s in ("", "-", "--", "–") else int(float(s))


def _F(s):
    s = str(s).replace(",", "").strip()
    return None if s in ("", "-", "--", "–") else float(s)


# ----------------------------- fetchers -----------------------------
def fetch_futures(start, end, existing=None):
    """臺股期貨 三大法人 未平倉口數淨額（口）。

    ⚠️ 失敗保底：TAIFEX 對雲端 IP 偶爾封鎖／回空。3 次重試，全空就「保留既有、不清空」
    （未平倉為歷史不變值，全量成功時 merge 進既有＝自癒缺口；失敗時絕不覆蓋成空）。
    """
    fut = dict(existing or {})
    for _ in range(3):
        t = _post("https://www.taifex.com.tw/cht/3/futContractsDateDown",
                  {"firstDate": "", "lastDate": "", "queryStartDate": start,
                   "queryEndDate": end, "commodity_id": "TXF"})
        new = {}
        for ln in t.splitlines():
            c = ln.split(",")
            if len(c) < 14 or c[1] != "臺股期貨":  # 臺股期貨
                continue
            r = new.setdefault(c[0], {})
            who = c[2]
            if "外資" in who:            # 外資
                r["foreign"] = _I(c[13])
            elif who == "投信":          # 投信
                r["trust"] = _I(c[13])
            elif who == "自營商":    # 自營商
                r["dealer"] = _I(c[13])
        if new:
            fut.update(new)
            return fut
        time.sleep(1.0)
    print("  futures BAD → 保留既有不清空", file=sys.stderr)
    return fut


def fetch_options(start, end, existing=None):
    """臺指選擇權 外資 未平倉口數買賣淨額（口）CALL / PUT。

    ⚠️ 失敗保底同 fetch_futures：3 次重試，全空保留既有不清空。
    """
    opt = dict(existing or {})
    for _ in range(3):
        t = _post("https://www.taifex.com.tw/cht/3/callsAndPutsDateDown",
                  {"firstDate": "", "lastDate": "", "queryStartDate": start,
                   "queryEndDate": end, "commodity_id": "TXO"})
        new = {}
        for ln in t.splitlines():
            c = ln.split(",")
            if len(c) < 15 or c[1] != "臺指選擇權" or "外資" not in c[3]:
                continue
            r = new.setdefault(c[0], {})
            if c[2] == "CALL":
                r["call"] = _I(c[14])
            elif c[2] == "PUT":
                r["put"] = _I(c[14])
        if new:
            opt.update(new)
            return opt
        time.sleep(1.0)
    print("  options BAD → 保留既有不清空", file=sys.stderr)
    return opt


def fetch_price(start_date, end_date, existing=None):
    """台指期 TX 近月（一般盤）收盤價；日行情有 ~31 天區間上限，分 30 天段抓。

    existing 有值時走增量：保留歷史、只重抓最近 ~45 天補新日（價格為歷史不變值，
    不需每天全量重抓，也避免舊 chunk 偶發失敗導致整檔掉資料）。
    """
    price = dict(existing or {})
    d = (end_date - datetime.timedelta(days=45)) if existing else start_date
    while d <= end_date:
        de = min(d + datetime.timedelta(days=29), end_date)
        ok = False
        for _ in range(3):
            t = _post("https://www.taifex.com.tw/cht/3/futDataDown",
                      {"down_type": "1", "commodity_id": "TX",
                       "queryStartDate": d.strftime("%Y/%m/%d"),
                       "queryEndDate": de.strftime("%Y/%m/%d")})
            lines = t.splitlines()
            if lines and lines[0].startswith("交易日期"):  # 交易日期
                for ln in lines[1:]:
                    c = [x.strip() for x in ln.split(",")]
                    if len(c) < 8 or c[1] != "TX" or not c[2].isdigit():
                        continue  # 排除價差契約（到期含 "/"）
                    sess = c[17] if len(c) > 17 else ""
                    if sess and "一般" not in sess:  # 只取一般盤
                        continue
                    cl = _F(c[6])
                    if cl and c[0] not in price:  # 第一筆＝近月
                        price[c[0]] = cl
                ok = True
                break
            time.sleep(1.0)
        if not ok:
            print(f"  price BAD {d}~{de}", file=sys.stderr)
        d = de + datetime.timedelta(days=1)
        time.sleep(0.6)
    return price


def _margin_one(ds):
    """查單一交易日的上市融資餘額（億元）；非交易日回 None。"""
    try:
        j = json.loads(_get(
            f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=MS&response=json"))
        for tb in j.get("tables", []):
            for row in tb.get("data", []):
                if row and "融資金額" in str(row[0]):  # 融資金額(仟元)
                    return round(_I(row[5]) / 100000.0, 1)  # 仟元 → 億
    except Exception:
        pass
    return None


def fetch_margin(start_date, end_date, existing=None):
    """TWSE 上市融資餘額（億元），逐交易日抓；existing 為已有 [date,val]（增量續抓，不重打）。"""
    margin = list(existing or [])
    have = {r[0] for r in margin}
    d = start_date
    while d <= end_date:
        if d.weekday() < 5 and d.isoformat() not in have:  # 平日且未抓過
            val = _margin_one(d.strftime("%Y%m%d"))
            if val:
                margin.append([d.isoformat(), val])
            time.sleep(0.15)
        d += datetime.timedelta(days=1)
    margin.sort()
    return margin


def _inst_one(ds):
    """單一交易日三大法人現貨買賣超（億元）；非交易日回 None。

    TWSE BFI82U「買賣差額」以元計；三大法人淨額慣例：
      外資 = 外資及陸資(不含外資自營商)   投信 = 投信   自營 = 自行買賣 + 避險
    （外資自營商已計入自營商，且不納入三大法人合計，故 foreign 不重複加它，
      dealer+trust+foreign 即等於官方「合計」列。）
    """
    url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={ds}&type=day&response=json"
    for attempt in range(3):  # TWSE 對連續請求會 307 節流，退避重試
        try:
            j = json.loads(_get(url))
            if j.get("stat") != "OK":
                return None  # 非交易日：明確無資料，不重試
            m = {str(r[0]): _I(r[3]) for r in j.get("data", []) if r}  # 買賣差額(元)
            if not m:
                return None
            E = 1e8  # 元 → 億
            dealer = m.get("自營商(自行買賣)", 0) + m.get("自營商(避險)", 0)
            return {
                "foreign": round(m.get("外資及陸資(不含外資自營商)", 0) / E, 2),
                "trust": round(m.get("投信", 0) / E, 2),
                "dealer": round(dealer / E, 2),
            }
        except Exception:
            time.sleep(1.5 * (attempt + 1))  # 遇節流/暫時錯誤退避
    return None


def fetch_institutions(start_date, end_date, existing=None):
    """三大法人現貨買賣超（億元），逐交易日抓；existing 為已有 [[date,{...}],..]（增量續抓）。"""
    inst = list(existing or [])
    have = {r[0] for r in inst}
    d = start_date
    while d <= end_date:
        if d.weekday() < 5 and d.isoformat() not in have:  # 平日且未抓過
            v = _inst_one(d.strftime("%Y%m%d"))
            if v:
                inst.append([d.isoformat(), v])
            time.sleep(0.15)
        d += datetime.timedelta(days=1)
    inst.sort()
    return inst


def load_maintain(existing=None):
    """大盤融資維持率序列 [date, total%, 上市%, 上櫃%]。

    來源＝同目錄 tw_margin_history.json（korea-leverage workflow 每日算好 commit）。
    檔案不在的 runner（如 Pages GHA、Mac clone 沒帶檔時）就沿用既有、不清空
    （由「有帶檔」的 runner＝workspace GHA / Mac 先抓檔 來刷新）。"""
    merged = {r[0]: r for r in (existing or [])}
    path = HERE / "tw_margin_history.json"
    if path.exists():
        try:
            hist = json.load(open(path, encoding="utf-8"))
            for k, e in hist.items():
                iso = f"{k[:4]}-{k[4:6]}-{k[6:]}"
                merged[iso] = [iso, e.get("total_ratio"),
                               e.get("twse_ratio"), e.get("tpex_ratio")]
        except Exception as ex:
            print(f"  maintain load failed: {ex}", file=sys.stderr)
    return [merged[d] for d in sorted(merged)]


def fetch_all(years=2, prior=None):
    prior = prior or {}
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=int(365 * years))
    s, e = start_date.strftime("%Y/%m/%d"), end_date.strftime("%Y/%m/%d")
    # 期/選單一區間全量請求；成功 merge 進既有＝自癒缺口，失敗保留既有不清空（防雲端 IP 被擋洗檔）
    print("fetching futures...", file=sys.stderr)
    fut = fetch_futures(s, e, existing=prior.get("futures"))
    print(f"  {len(fut)} days", file=sys.stderr)
    print("fetching options...", file=sys.stderr)
    opt = fetch_options(s, e, existing=prior.get("options"))
    print(f"  {len(opt)} days", file=sys.stderr)
    # price/margin 為歷史不變值 → 增量（只補最近，歷史沿用既有）
    print("fetching price (incremental)...", file=sys.stderr)
    price = fetch_price(start_date, end_date, existing=prior.get("price"))
    print(f"  {len(price)} days", file=sys.stderr)
    print("fetching margin (incremental)...", file=sys.stderr)
    margin = fetch_margin(start_date, end_date, existing=prior.get("margin"))
    print(f"  {len(margin)} days", file=sys.stderr)
    print("fetching institutions (incremental)...", file=sys.stderr)
    inst = fetch_institutions(start_date, end_date, existing=prior.get("institutions"))
    print(f"  {len(inst)} days", file=sys.stderr)
    maintain = load_maintain(prior.get("maintain"))
    print(f"  maintain {len(maintain)} days", file=sys.stderr)
    return {
        "generated": end_date.isoformat(),
        "futures": fut, "price": price, "options": opt, "margin": margin,
        "institutions": inst, "maintain": maintain,
    }


# ----------------------------- render -----------------------------
def build_html(data):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    tpl = _TEMPLATE.replace("/*__DATA__*/", payload).replace(
        "__GEN__", data.get("generated", ""))
    return tpl


def build_artifact(data):
    """Artifact 專用版：去掉外層 <!doctype>/<html>/<head>/<body>，只留 <style>+內容+<script>。"""
    html = build_html(data)
    style = html[html.index("<style>"):html.index("</style>") + len("</style>")]
    body = html[html.index("<body>") + len("<body>"):html.index("</body>")]
    return style + "\n" + body.strip() + "\n"


def main():
    args = sys.argv[1:]
    if "--from-cache" in args and DATA_PATH.exists():
        data = json.load(open(DATA_PATH, encoding="utf-8"))
        data["maintain"] = load_maintain(data.get("maintain"))  # 維持率從歷史檔補上/刷新
    else:
        years = 2
        if "--years" in args:
            years = float(args[args.index("--years") + 1])
        prior = {}
        if DATA_PATH.exists():
            try:
                prior = json.load(open(DATA_PATH, encoding="utf-8"))
            except Exception:
                prior = {}
        data = fetch_all(years, prior=prior)
        json.dump(data, open(DATA_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "籌碼儀表板.html"
    out.write_text(build_html(data), encoding="utf-8")
    print("wrote", out)
    art = OUT_DIR / "籌碼儀表板_artifact.html"
    art.write_text(build_artifact(data), encoding="utf-8")
    print("wrote", art)


# ----------------------------- HTML template -----------------------------
# NOTE: 標記 /*__DATA__*/ 會被換成 JSON；__GEN__ 換成產生日期。
_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>台股籌碼儀表板</title>
<style>
:root{
  --bg:#eef1f5; --panel:#ffffff; --ink:#1a2230; --muted:#6b7686; --hair:#e4e8ee;
  --grid:#eef1f5; --axis:#aab2be; --sub:#8b95a4;
  --up:#d0342c; --down:#1f9d57;               /* 台股慣例：紅漲綠跌 */
  --foreign:#2f6df0; --trust:#e8912b; --dealer:#1faf7a;
  --call:#2f6df0; --put:#e0533d; --price:#2a3444; --fill:#3d7bf0;
  --shadow:0 1px 2px rgba(20,30,50,.05),0 6px 20px rgba(20,30,50,.06);
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0e1218; --panel:#161c26; --ink:#e8edf4; --muted:#8b97a8; --hair:#242c38;
    --grid:#1c232e; --axis:#3a4552; --sub:#7c8798;
    --up:#ff5a4d; --down:#25c274;
    --foreign:#4d89ff; --trust:#f0a53a; --dealer:#2fc78e;
    --call:#4d89ff; --put:#ff6f57; --price:#c6d0dc; --fill:#4d89ff;
    --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.35);
  }
}
:root[data-theme="light"]{
  --bg:#eef1f5; --panel:#ffffff; --ink:#1a2230; --muted:#6b7686; --hair:#e4e8ee;
  --grid:#eef1f5; --axis:#aab2be; --sub:#8b95a4;
  --up:#d0342c; --down:#1f9d57; --foreign:#2f6df0; --trust:#e8912b; --dealer:#1faf7a;
  --call:#2f6df0; --put:#e0533d; --price:#2a3444; --fill:#3d7bf0;
  --shadow:0 1px 2px rgba(20,30,50,.05),0 6px 20px rgba(20,30,50,.06);
}
:root[data-theme="dark"]{
  --bg:#0e1218; --panel:#161c26; --ink:#e8edf4; --muted:#8b97a8; --hair:#242c38;
  --grid:#1c232e; --axis:#3a4552; --sub:#7c8798;
  --up:#ff5a4d; --down:#25c274; --foreign:#4d89ff; --trust:#f0a53a; --dealer:#2fc78e;
  --call:#4d89ff; --put:#ff6f57; --price:#c6d0dc; --fill:#4d89ff;
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;
  padding:max(14px,env(safe-area-inset-top)) 14px calc(24px + env(safe-area-inset-bottom));}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;
  gap:6px 14px;margin:2px 2px 16px}
h1{font-size:20px;font-weight:700;letter-spacing:.3px;margin:0}
.sub{color:var(--muted);font-size:12.5px}
.sub b{color:var(--ink);font-weight:600}
.controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0 2px 12px}
.ranges{display:inline-flex;gap:3px;background:var(--panel);border:1px solid var(--hair);
  border-radius:10px;padding:3px;box-shadow:var(--shadow)}
.ranges button{border:0;background:transparent;color:var(--muted);font-family:var(--font);
  font-size:12.5px;font-weight:600;padding:5px 12px;border-radius:8px;cursor:pointer;
  letter-spacing:.2px;transition:background .12s,color .12s}
.ranges button:hover{color:var(--ink)}
.ranges button.on{background:var(--fill);color:#fff}
.linktoggle{border:1px solid var(--hair);background:var(--panel);color:var(--muted);
  font-family:var(--font);font-size:12.5px;font-weight:600;padding:8px 13px;border-radius:10px;
  cursor:pointer;box-shadow:var(--shadow);letter-spacing:.2px;
  transition:background .12s,color .12s,border-color .12s}
.linktoggle:hover{color:var(--ink)}
.linktoggle.on{background:var(--fill);color:#fff;border-color:var(--fill)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:760px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--hair);border-radius:14px;
  padding:15px 16px 8px;box-shadow:var(--shadow);min-width:0}
.phead{display:flex;align-items:flex-start;justify-content:space-between;gap:10px;margin-bottom:2px}
.ptitle{font-size:14.5px;font-weight:600;line-height:1.35;letter-spacing:.2px}
.ptitle .u{color:var(--sub);font-weight:500;font-size:12px;margin-left:2px}
.metric{text-align:right;white-space:nowrap;line-height:1.15}
.value{font-size:26px;font-weight:700;letter-spacing:.2px}
.value .un{font-size:12px;font-weight:600;color:var(--muted);margin-left:3px}
.delta{font-size:12px;font-weight:600;margin-top:1px}
.delta.up{color:var(--up)} .delta.down{color:var(--down)} .delta.flat{color:var(--muted)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin:3px 1px 0;font-size:12px;color:var(--muted)}
.legend span{display:inline-flex;align-items:center;gap:5px}
.legend i{width:11px;height:3px;border-radius:2px;display:inline-block}
.chart{position:relative;width:100%;margin-top:4px}
.chart svg{display:block;width:100%;height:auto;overflow:visible;touch-action:pan-y}
.tt{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--hair);
  border-radius:9px;box-shadow:var(--shadow);padding:7px 9px;font-size:11.5px;opacity:0;
  transition:opacity .08s;white-space:nowrap;z-index:5}
.tt .d{color:var(--muted);margin-bottom:4px;font-size:11px}
.tt .ttt{border-collapse:collapse}
.tt .ttt td{padding:1.5px 7px;text-align:right;font-variant-numeric:tabular-nums;line-height:1.3}
.tt .ttt td.nm{text-align:left;color:var(--muted);padding-left:0;padding-right:11px}
.tt .ttt td.nm i{width:9px;height:3px;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle}
.tt .ttt tr.hd td{color:var(--sub);font-size:10px;padding-bottom:3px;font-weight:600}
.tt .ttt td.cur{color:var(--ink);font-weight:700}
.tt .ttt td.mut{color:var(--sub)}
footer{color:var(--muted);font-size:11.5px;text-align:center;margin-top:18px;line-height:1.6}
footer a{color:var(--foreign);text-decoration:none}
/* 分頁列（籌碼總覽 / 主動 ETF 追蹤） */
.tabs{display:inline-flex;gap:4px;background:var(--panel);border:1px solid var(--hair);
  border-radius:11px;padding:4px;box-shadow:var(--shadow);margin:0 2px 14px}
.tabs button{border:0;background:transparent;color:var(--muted);font-family:var(--font);
  font-size:13.5px;font-weight:700;padding:7px 16px;border-radius:8px;cursor:pointer;
  letter-spacing:.3px;transition:background .12s,color .12s}
.tabs button:hover{color:var(--ink)}
.tabs button.on{background:var(--fill);color:#fff}
/* 連續方向 KPI 卡片 */
.streaks{display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:10px;margin:0 2px 14px}
.scard{background:var(--panel);border:1px solid var(--hair);border-radius:12px;
  padding:10px 13px 11px;box-shadow:var(--shadow);position:relative;overflow:hidden}
.scard .bar{position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--muted)}
.scard .lab{font-size:11.5px;color:var(--muted);font-weight:600;letter-spacing:.2px}
.scard .dir{font-size:18px;font-weight:800;margin-top:2px;letter-spacing:.4px;
  display:flex;align-items:baseline;gap:7px;line-height:1.2}
.scard .cnt{font-size:12.5px;font-weight:700;color:var(--muted)}
.scard .sub{font-size:11px;color:var(--sub);margin-top:2px}
.scard.up .dir{color:var(--up)} .scard.up .bar{background:var(--up)}
.scard.down .dir{color:var(--down)} .scard.down .bar{background:var(--down)}
.scard.flat .dir{color:var(--muted)}
/* ETF 分頁：無框、與頁面連續捲動（高度自動貼齊內容，不用內部捲軸）*/
.etfnote{color:var(--muted);font-size:12px;margin:0 2px 10px}
.etfnote a{color:var(--foreign);text-decoration:none;font-weight:600}
#etfFrame{width:100%;border:0;background:transparent;display:block}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>台股籌碼儀表板</h1>
    <div class="sub">資料截至 <b>__GEN__</b> · <span id="rlabel">近 1 年</span> · 來源：TAIFEX 期交所／TWSE 證交所（官方免費）</div>
  </header>
  <div class="tabs" id="tabs">
    <button data-tab="chip" class="on">籌碼總覽</button>
    <button data-tab="etf">主動 ETF 追蹤</button>
  </div>
  <section id="tab-chip">
    <div class="controls">
      <div class="ranges" id="ranges">
        <button data-r="1W">1W</button><button data-r="1M">1M</button><button data-r="6M">6M</button><button data-r="YTD">YTD</button><button data-r="1Y">1Y</button><button data-r="2Y">2Y</button>
      </div>
      <button id="linkBtn" class="linktoggle" type="button" aria-pressed="false" title="開啟後：滑過任一張圖，各圖會在同一天同步顯示十字線與數值">🔗 多圖連動</button>
      <button id="themeBtn" class="linktoggle" type="button" title="切換淺色／深色主題">🌙 深色</button>
    </div>
    <div class="streaks" id="streaks"></div>
    <div class="grid" id="grid"></div>
    <footer>
      未平倉淨口數為多空未平倉口數淨額（口），正=淨多、負=淨空 · 現貨買賣超/融資餘額為上市市場合計、每交易日<br>
      三大法人現貨買賣超取 TWSE BFI82U「買賣差額」（外資＝外資及陸資，自營＝自行買賣＋避險）<br>
      大盤融資維持率＝Σ融資股票市值 ÷ 融資金額餘額（上市+上櫃、含 ETF 市場通用口徑）；警戒線 <span style="color:var(--down)">≥170 🟢</span> / 160–170 🟡 / <span style="color:var(--up)">&lt;160 🔴</span><br>
      數字直接取自官方公開資料，未經第三方加工 · 台股慣例 <span style="color:var(--up)">紅漲</span> / <span style="color:var(--down)">綠跌</span>
    </footer>
  </section>
  <section id="tab-etf" hidden>
    <div class="etfnote">主動型 ETF 每日持股動態追蹤。<a href="/etf" target="_blank" rel="noopener">↗ 另開整頁</a></div>
    <iframe id="etfFrame" title="主動 ETF 追蹤" loading="lazy"></iframe>
  </section>
</div>
<script>
const DATA = /*__DATA__*/;

const RANGES={"1W":"近 1 週","1M":"近 1 個月","6M":"近 6 個月","YTD":"今年以來","1Y":"近 1 年","2Y":"近 2 年"};
let RANGE="1Y";
try{ if(RANGES[localStorage.getItem("chipRange")]) RANGE=localStorage.getItem("chipRange"); }catch(e){}
// 四圖連動（crosshair / tooltip 跨圖同步，依日期對齊）；localStorage 記住
window.LINK=false;
try{ window.LINK = localStorage.getItem("chipLink")==="1"; }catch(e){}
// 主題：預設淺色（白底），localStorage 記住；<html data-theme="light"> 先擋首屏閃深色
let THEME="light";
try{ if(localStorage.getItem("chipTheme")==="dark") THEME="dark"; }catch(e){}
document.documentElement.setAttribute("data-theme",THEME);

// 依目前區間算最早保留日期（ISO 字串比較即可）；"" = 不裁切
const RANGE_DAYS={"1W":7,"1M":31,"6M":183,"1Y":365};
function rangeCutoff(){
  const gen = DATA.generated || "";
  if(RANGE==="2Y" || !gen) return "";
  if(RANGE==="YTD") return gen.slice(0,4)+"-01-01";
  const days = RANGE_DAYS[RANGE] || 365;
  const end = new Date(gen+"T00:00:00");
  return new Date(end.getTime()-days*86400000).toISOString().slice(0,10);
}

const fmtInt = n => (n<0?"-":"")+Math.abs(Math.round(n)).toLocaleString("en-US");
const fmtSign = n => (n>0?"+":n<0?"-":"")+Math.abs(Math.round(n)).toLocaleString("en-US");
const fmtSign1 = n => (n>0?"+":n<0?"-":"")+Math.abs(n).toFixed(1);   // 億元帶 1 位小數＋正負號
const cssv = k => getComputedStyle(document.documentElement).getPropertyValue(k).trim();

// 把 {日期:值} 或 {日期:{..}} 轉成排序後的 labels / rows
function series(obj){
  const keys = Object.keys(obj).sort();
  return {labels:keys, get:k=>obj[k]};
}

// 建立一個面板
function panel(cfg){
  const el = document.createElement("div"); el.className="panel";
  const legend = cfg.lines.length>1
    ? `<div class="legend">${cfg.lines.map(l=>`<span><i style="background:${l.color}"></i>${l.name}</span>`).join("")}</div>`
    : "";
  const dcls = cfg.delta>0?"up":cfg.delta<0?"down":"flat";
  const arrow = cfg.delta>0?"▲":cfg.delta<0?"▼":"→";
  el.innerHTML = `
    <div class="phead">
      <div class="ptitle">${cfg.title}${cfg.tunit?`<span class="u">${cfg.tunit||cfg.unit}</span>`:""}</div>
      <div class="metric">
        <div class="value">${cfg.valueTxt}<span class="un">${cfg.unit}${cfg.who?`（${cfg.who}）`:""}</span></div>
        <div class="delta ${dcls}">${arrow} ${cfg.dfmt?cfg.dfmt(Math.abs(cfg.delta)):fmtInt(Math.abs(cfg.delta))} vs 前一筆</div>
      </div>
    </div>
    ${legend}
    <div class="chart"></div>`;
  cfg._mount = el.querySelector(".chart");
  cfg._el = el;
  return cfg;
}

// SVG 折線圖（多序列、可零軸基線、可面積）
function drawChart(cfg){
  const box = cfg._mount, W = box.clientWidth || 520;
  const H = cfg.h || 176;
  const padL=44, padR=10, padT=10, padB=20;
  const iw=W-padL-padR, ih=H-padT-padB;
  const labels=cfg.labels, n=labels.length;
  let lo=Infinity, hi=-Infinity;
  cfg.lines.forEach(l=>l.data.forEach(v=>{if(v==null)return; if(v<lo)lo=v; if(v>hi)hi=v;}));
  if(cfg.baseline){ lo=Math.min(lo,0); hi=Math.max(hi,0); }
  if(lo===hi){lo-=1;hi+=1;}
  const pad=(hi-lo)*0.08; lo-=pad; hi+=pad;
  const X=i=> padL + (n<=1?0:iw*i/(n-1));
  const Y=v=> padT + ih*(1-(v-lo)/(hi-lo));

  const NS="http://www.w3.org/2000/svg";
  const svg=document.createElementNS(NS,"svg");
  svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio","none");
  svg.style.height=H+"px";
  const mk=(t,a)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);return e;};

  // y gridlines + labels
  const ticks=4;
  for(let i=0;i<=ticks;i++){
    const v=lo+(hi-lo)*i/ticks, y=Y(v);
    svg.appendChild(mk("line",{x1:padL,y1:y,x2:W-padR,y2:y,stroke:cssv("--grid"),"stroke-width":1}));
    const tx=mk("text",{x:padL-6,y:y+3.5,"text-anchor":"end",fill:cssv("--sub"),"font-size":10});
    tx.textContent = cfg.yfmt? cfg.yfmt(v) : fmtInt(v);
    svg.appendChild(tx);
  }
  // zero baseline emphasis
  if(cfg.baseline && lo<0 && hi>0){
    svg.appendChild(mk("line",{x1:padL,y1:Y(0),x2:W-padR,y2:Y(0),stroke:cssv("--axis"),"stroke-width":1.2}));
  }
  // x labels (~6 ticks)
  const xt=Math.min(6,n-1);
  for(let i=0;i<=xt;i++){
    const idx=Math.round((n-1)*i/xt), x=X(idx);
    const d=labels[idx].replaceAll("-","/");
    const parts=d.split("/");
    const tx=mk("text",{x:x,y:H-6,"text-anchor":i===0?"start":i===xt?"end":"middle",
      fill:cssv("--sub"),"font-size":10});
    tx.textContent=parts[0]+"/"+parts[1];
    svg.appendChild(tx);
  }
  // area fill：單序列較濃、多序列各自淡填（與融資圖一致的漸層填色風格）
  if(cfg.fill){
    const single=cfg.lines.length===1;
    const base=cfg.baseline?Y(0):(padT+ih);
    cfg.lines.forEach((l,li)=>{
      let d="", first=null, last=null;
      l.data.forEach((v,i)=>{ if(v==null)return; if(first==null)first=i; last=i; d+=(d?"L":"M")+X(i)+" "+Y(v);});
      if(first==null) return;
      d+=`L ${X(last)} ${base} L ${X(first)} ${base} Z`;
      const gid="g_"+cfg.key+"_"+li;
      const grad=mk("linearGradient",{id:gid,x1:0,y1:0,x2:0,y2:1});
      grad.appendChild(mk("stop",{offset:"0%","stop-color":l.color,"stop-opacity":single?.22:.13}));
      grad.appendChild(mk("stop",{offset:"100%","stop-color":l.color,"stop-opacity":0}));
      svg.appendChild(grad);
      svg.appendChild(mk("path",{d,fill:`url(#${gid})`,stroke:"none"}));
    });
  }
  // lines
  cfg.lines.forEach(l=>{
    let d="";
    l.data.forEach((v,i)=>{ if(v==null){return;} d+=(d?"L":"M")+X(i)+" "+Y(v);});
    svg.appendChild(mk("path",{d,fill:"none",stroke:l.color,"stroke-width":cfg.lines.length===1?1.7:1.4,
      "stroke-linejoin":"round","stroke-linecap":"round"}));
    // endpoint dot
    for(let i=l.data.length-1;i>=0;i--){ if(l.data[i]!=null){
      svg.appendChild(mk("circle",{cx:X(i),cy:Y(l.data[i]),r:2.6,fill:l.color}));break;}}
  });

  box.innerHTML=""; box.appendChild(svg);

  // tooltip / crosshair（可跨圖連動）
  const tt=document.createElement("div"); tt.className="tt"; box.appendChild(tt);
  const cross=mk("line",{x1:0,y1:padT,x2:0,y2:padT+ih,stroke:cssv("--axis"),"stroke-width":1,
    "stroke-dasharray":"3 3",opacity:0}); svg.appendChild(cross);
  const dots=cfg.lines.map(l=>{const c=mk("circle",{r:3.3,fill:cssv("--panel"),stroke:l.color,
    "stroke-width":2,opacity:0});svg.appendChild(c);return c;});
  // 日期正規化（TAIFEX 2025/08/05 與 TWSE 2025-08-05 統一成 dash，供跨圖日期對齊）
  const norm=labels.map(d=>d.split("/").join("-"));
  const md=i=> labels[i].replaceAll("-","/").slice(5);   // MM/DD
  function showIdx(idx){
    idx=Math.max(0,Math.min(n-1,idx));
    const x=X(idx);
    cross.setAttribute("x1",x);cross.setAttribute("x2",x);cross.setAttribute("opacity",1);
    const pi=idx>0?idx-1:null, ni=idx<n-1?idx+1:null;      // 前一筆 / 後一筆
    const vf=v=> v==null?null:(cfg.vfmt?cfg.vfmt(v):fmtInt(v));
    // 表頭：前 / 當日 / 後 三欄日期
    const hcell=(i,cur)=> i==null?'<td class="mut">—</td>':`<td class="${cur?'cur':''}">${md(i)}</td>`;
    let head=`<tr class="hd"><td></td>${hcell(pi,0)}${hcell(idx,1)}${hcell(ni,0)}</tr>`;
    let rows="";
    cfg.lines.forEach((l,k)=>{
      const v=l.data[idx];
      if(v==null){dots[k].setAttribute("opacity",0);}
      else{dots[k].setAttribute("cx",x);dots[k].setAttribute("cy",Y(v));dots[k].setAttribute("opacity",1);}
      const cell=(i,cur)=>{const t=i==null?null:vf(l.data[i]);
        return t==null?'<td class="mut">—</td>':`<td class="${cur?'cur':''}">${t}</td>`;};
      rows+=`<tr><td class="nm"><i style="background:${l.color}"></i>${l.name}</td>`
           +`${cell(pi,0)}${cell(idx,1)}${cell(ni,0)}</tr>`;
    });
    tt.innerHTML=`<div class="d">${labels[idx].replaceAll("-","/")}</div><table class="ttt">${head}${rows}</table>`;
    tt.style.opacity=1;
    // 定位：垂直留在圖內（不上飄到標題大數字），水平往指標另一側翻，避免遮到當日數值
    const r=box.getBoundingClientRect();
    const lx=x/W*r.width, tw=tt.offsetWidth;
    let left = idx>n/2 ? lx-12-tw : lx+12;                 // 右半邊→往左放，左半邊→往右放
    left=Math.max(4,Math.min(r.width-4-tw,left));
    tt.style.transform="none";
    tt.style.left=left+"px"; tt.style.top=(padT+6)+"px";
  }
  function hide(){tt.style.opacity=0;cross.setAttribute("opacity",0);dots.forEach(d=>d.setAttribute("opacity",0));}
  // 連動控制器：依日期定位（找最後一個 <= 目標日期的索引，各圖交易日不同也對得上）
  const ctrl={norm,showByDate(dateISO){let idx=0;for(let i=0;i<norm.length;i++){if(norm[i]<=dateISO)idx=i;else break;}showIdx(idx);},hide};
  window.__charts.push(ctrl);
  function move(ev){
    const r=box.getBoundingClientRect();
    const px=((ev.touches?ev.touches[0].clientX:ev.clientX)-r.left)/r.width*W;
    let idx=Math.round((px-padL)/(iw)*(n-1)); idx=Math.max(0,Math.min(n-1,idx));
    showIdx(idx);
    if(window.LINK){const date=norm[idx];window.__charts.forEach(c=>{if(c!==ctrl)c.showByDate(date);});}
  }
  function leave(){hide();if(window.LINK){window.__charts.forEach(c=>{if(c!==ctrl)c.hide();});}}
  box.addEventListener("mousemove",move); box.addEventListener("mouseleave",leave);
  box.addEventListener("touchstart",move,{passive:true}); box.addEventListener("touchmove",move,{passive:true});
  box.addEventListener("touchend",leave);
}

// ---- 連續方向（streak）----
// 從序列尾端往回數，計算「最近值同號」連續筆數；0 或 null 中斷（null 跳過不中斷）
function signStreak(arr){
  let i=arr.length-1; while(i>=0 && arr[i]==null) i--;
  if(i<0) return {sign:0,count:0};
  const s=Math.sign(arr[i]); if(!s) return {sign:0,count:0};
  let c=0;
  for(let j=i;j>=0;j--){ const v=arr[j]; if(v==null) continue;
    if(Math.sign(v)===s) c++; else break; }
  return {sign:s,count:c};
}
// 日變化序列（未平倉口數的逐日增減，用來判斷加多/加空）
function deltaSeries(arr){
  const out=[]; let prev=null;
  for(const v of arr){ if(v==null){out.push(null);continue;}
    out.push(prev==null?null:v-prev); prev=v; }
  return out;
}
function scard(lab, sign, count, posLabel, negLabel, sub){
  const cls=sign>0?"up":sign<0?"down":"flat";
  const dir=sign>0?posLabel:sign<0?negLabel:"—";
  const cnt=count>0?`連 ${count} 日`:"";
  return `<div class="scard ${cls}"><span class="bar"></span>`
    +`<div class="lab">${lab}</div>`
    +`<div class="dir">${dir}<span class="cnt">${cnt}</span></div>`
    +(sub?`<div class="sub">${sub}</div>`:"")+`</div>`;
}
// streak 為「最近事實」，不隨區間裁切，一律用全量資料計算
function renderStreaks(){
  const box=document.getElementById("streaks"); if(!box) return;
  const futK=Object.keys(DATA.futures||{}).sort();
  const F=futK.map(d=>DATA.futures[d].foreign??null);
  const pos=signStreak(F);                       // 淨多／淨空（部位正負）
  const add=signStreak(deltaSeries(F));          // 加多／加空（未平倉逐日增減）
  const lastF=F.length?F[F.length-1]:null;
  const posSub=lastF!=null?`${lastF<0?"淨空":"淨多"} ${fmtInt(Math.abs(lastF))} 口`:"";
  const inst=(DATA.institutions||[]).slice().sort((a,b)=>a[0]<b[0]?-1:1);
  const iF=inst.map(x=>x[1].foreign??null), iT=inst.map(x=>x[1].trust??null), iD=inst.map(x=>x[1].dealer??null);
  const sF=signStreak(iF), sT=signStreak(iT), sD=signStreak(iD);
  const lastNet=iF.length?iF[iF.length-1]:null;
  const netSub=lastNet!=null?`最新 ${fmtSign1(lastNet)} 億`:"";
  // 融資餘額 連增/連減（用上市融資餘額逐日變化）
  const mgn=(DATA.margin||[]).slice().sort((a,b)=>a[0]<b[0]?-1:1);
  const mV=mgn.map(x=>x[1]??null);
  const sM=signStreak(deltaSeries(mV));
  const lastM=mV.length?mV[mV.length-1]:null;
  const mSub=lastM!=null?`最新 ${fmtInt(lastM)} 億`:"";
  box.innerHTML=
    scard("外資期貨・部位",  pos.sign, pos.count, "淨多",  "淨空",  posSub)
   +scard("外資期貨・加減碼",add.sign, add.count, "加多單","加空單","未平倉逐日增減")
   +scard("外資・現貨",      sF.sign,  sF.count,  "買超",  "賣超",  netSub)
   +scard("投信・現貨",      sT.sign,  sT.count,  "買超",  "賣超",  "")
   +scard("自營・現貨",      sD.sign,  sD.count,  "買超",  "賣超",  "")
   +scard("融資餘額・增減",  sM.sign,  sM.count,  "連續增","連續減",mSub);
}

// ---- 組資料 ----
function build(){
  const grid=document.getElementById("grid");
  const panels=[];
  window.__charts=[];   // 每次重繪重置連動控制器清單
  const CUT=rangeCutoff();
  // 日期 key 有兩種格式（TAIFEX=2025/08/05、TWSE margin=2025-08-05），比較前統一成 dash
  const inRange=d=>!CUT||d.split("/").join("-")>=CUT;

  // ① 期貨三大法人
  {
    const s=series(DATA.futures), k=s.labels.filter(inRange);
    const F=k.map(d=>s.get(d).foreign??null), T=k.map(d=>s.get(d).trust??null), D=k.map(d=>s.get(d).dealer??null);
    const last=F[F.length-1], prev=F[F.length-2];
    panels.push(panel({key:"fut",title:"臺股期貨・三大法人未平倉淨口數",unit:"口",who:"外資",
      valueTxt:fmtInt(last),delta:last-prev,baseline:true,labels:k,
      lines:[{name:"外資",color:cssv("--foreign"),data:F},
             {name:"投信",color:cssv("--trust"),data:T},
             {name:"自營",color:cssv("--dealer"),data:D}]}));
  }
  // ② 三大法人・現貨買賣超（上市）
  if(Array.isArray(DATA.institutions) && DATA.institutions.length){
    const rows=DATA.institutions.filter(x=>inRange(x[0]));
    const k=rows.map(x=>x[0]);
    const F=rows.map(x=>x[1].foreign??null), T=rows.map(x=>x[1].trust??null), D=rows.map(x=>x[1].dealer??null);
    const last=F[F.length-1], prev=F[F.length-2];
    panels.push(panel({key:"inst",title:"三大法人・現貨買賣超（上市）",unit:"億元",who:"外資",
      valueTxt:fmtSign1(last),delta:last-prev,baseline:true,fill:true,labels:k,
      vfmt:v=>fmtSign1(v),yfmt:v=>fmtInt(v),
      lines:[{name:"外資",color:cssv("--foreign"),data:F},
             {name:"投信",color:cssv("--trust"),data:T},
             {name:"自營",color:cssv("--dealer"),data:D}]}));
  }
  // ③ 台指期近月
  {
    const s=series(DATA.price), k=s.labels.filter(inRange);
    const P=k.map(d=>s.get(d));
    const last=P[P.length-1], prev=P[P.length-2];
    panels.push(panel({key:"px",title:"台指期近月收盤價",unit:"點",
      valueTxt:fmtInt(last),delta:last-prev,labels:k,
      yfmt:v=>Math.round(v/1000)+"k",
      lines:[{name:"近月",color:cssv("--price"),data:P}]}));
  }
  // ④ 選擇權外資
  {
    const s=series(DATA.options), k=s.labels.filter(inRange);
    const C=k.map(d=>s.get(d).call??null), U=k.map(d=>s.get(d).put??null);
    const last=C[C.length-1], prev=C[C.length-2];
    panels.push(panel({key:"opt",title:"台指選擇權・外資未平倉淨口數",unit:"口",who:"CALL",
      valueTxt:fmtSign(last),delta:last-prev,baseline:true,labels:k,
      lines:[{name:"CALL",color:cssv("--call"),data:C},
             {name:"PUT",color:cssv("--put"),data:U}]}));
  }
  // ⑤ 上市融資餘額
  {
    const M=DATA.margin.filter(x=>inRange(x[0]));
    const k=M.map(x=>x[0]), V=M.map(x=>x[1]);
    const last=V[V.length-1], prev=V[V.length-2];
    panels.push(panel({key:"mgn",title:"上市融資餘額",unit:"億元",tunit:"億元・日",
      valueTxt:fmtInt(last),delta:last-prev,fill:true,labels:k,
      yfmt:v=>fmtInt(v),
      lines:[{name:"融資餘額",color:cssv("--fill"),data:V}]}));
  }
  // ⑥ 大盤融資維持率（上市+上櫃，市場通用含 ETF 口徑；<160🔴 160–170🟡 ≥170🟢）
  if(Array.isArray(DATA.maintain) && DATA.maintain.length){
    const R=DATA.maintain.filter(x=>inRange(x[0]));
    const k=R.map(x=>x[0]);
    const TOT=R.map(x=>x[1]??null), TW=R.map(x=>x[2]??null), TP=R.map(x=>x[3]??null);
    const last=TOT[TOT.length-1], prev=TOT[TOT.length-2];
    const dot=last==null?"":last<160?"🔴":last<170?"🟡":"🟢";
    panels.push(panel({key:"maint",title:"大盤融資維持率",unit:"%",tunit:"%（上市+上櫃）",
      valueTxt:(last!=null?dot+" "+last.toFixed(2):"—"),
      delta:(last!=null&&prev!=null?last-prev:0),dfmt:v=>v.toFixed(2),labels:k,
      yfmt:v=>Math.round(v)+"%",
      lines:[{name:"整體",color:cssv("--fill"),data:TOT},
             {name:"上市",color:cssv("--foreign"),data:TW},
             {name:"上櫃",color:cssv("--trust"),data:TP}]}));
  }

  panels.forEach(p=>{grid.appendChild(p._el); drawChart(p);});
  window.__panels=panels;
  renderStreaks();
}
// 區間按鈕
function syncRangeUI(){
  document.querySelectorAll("#ranges button").forEach(b=>b.classList.toggle("on",b.dataset.r===RANGE));
  document.getElementById("rlabel").textContent=RANGES[RANGE];
}
document.querySelectorAll("#ranges button").forEach(b=>{
  b.addEventListener("click",()=>{
    RANGE=b.dataset.r;
    try{localStorage.setItem("chipRange",RANGE);}catch(e){}
    syncRangeUI();
    document.getElementById("grid").innerHTML="";
    build();
  });
});
syncRangeUI();

// 四圖連動開關
const linkBtn=document.getElementById("linkBtn");
function syncLinkUI(){linkBtn.classList.toggle("on",window.LINK);linkBtn.setAttribute("aria-pressed",window.LINK?"true":"false");}
linkBtn.addEventListener("click",()=>{
  window.LINK=!window.LINK;
  try{localStorage.setItem("chipLink",window.LINK?"1":"0");}catch(e){}
  syncLinkUI();
});
syncLinkUI();

// 主題切換（淺色／深色）；切換後重繪，讓 SVG 內以 cssv() 讀的色彩（格線/軸/圓點）跟著更新
const themeBtn=document.getElementById("themeBtn");
function syncThemeUI(){themeBtn.textContent=THEME==="dark"?"☀️ 淺色":"🌙 深色";}
themeBtn.addEventListener("click",()=>{
  THEME=THEME==="dark"?"light":"dark";
  document.documentElement.setAttribute("data-theme",THEME);
  try{localStorage.setItem("chipTheme",THEME);}catch(e){}
  syncThemeUI();
  document.getElementById("grid").innerHTML="";build();
});
syncThemeUI();

build();

// 分頁：籌碼總覽 / 主動 ETF 追蹤（ETF 用同源 iframe 嵌 /etf，首次點擊才載入）
const TABLIST=["chip","etf"];
let TAB="chip";
try{ if(TABLIST.includes(localStorage.getItem("chipTab"))) TAB=localStorage.getItem("chipTab"); }catch(e){}
const etfFrame=document.getElementById("etfFrame");
// 高度自動貼齊 iframe 內容（同源可直接量）→ 無內部捲軸、與頁面連續捲動
function sizeEtf(){
  try{const d=etfFrame.contentDocument;
    if(d&&d.body) etfFrame.style.height=Math.max(d.body.scrollHeight,d.documentElement.scrollHeight)+"px";
  }catch(e){}
}
etfFrame.addEventListener("load",()=>{
  sizeEtf();
  try{const d=etfFrame.contentDocument;
    new ResizeObserver(()=>sizeEtf()).observe(d.body);   // 切內頁/篩選使內容變高時自動重量
    d.addEventListener("click",()=>{setTimeout(sizeEtf,80);setTimeout(sizeEtf,320);});
  }catch(e){}
});
function showTab(t){
  TAB=t;
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b.dataset.tab===t));
  document.getElementById("tab-chip").hidden = t!=="chip";
  document.getElementById("tab-etf").hidden  = t!=="etf";
  if(t==="etf"){
    if(!etfFrame.getAttribute("src")) etfFrame.setAttribute("src","/etf");  // lazy load
    sizeEtf();
  }
  try{localStorage.setItem("chipTab",t);}catch(e){}
}
document.querySelectorAll("#tabs button").forEach(b=>{
  b.addEventListener("click",()=>showTab(b.dataset.tab));
});
showTab(TAB);

// 只在「寬度」變化時重繪：手機捲動時網址列收合只改高度，
// 若也重繪會清空 grid → 頁面瞬間變短 → 捲動位置被彈回頂端。
let rt, lastW=innerWidth;
addEventListener("resize",()=>{
  if(TAB==="etf") sizeEtf();          // ETF iframe 高度需跟著視窗高度
  if(innerWidth===lastW) return;
  lastW=innerWidth;
  clearTimeout(rt);rt=setTimeout(()=>{
    document.getElementById("grid").innerHTML="";build();},160);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
