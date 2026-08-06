#!/usr/bin/env python3
"""法人買賣超前十大 pipeline — TWSE T86 三大法人買賣超個股（上市）。

輸出外資／投信各自的「買超前十／賣超前十」，期間 1日／5日／20日，每檔標連買/連賣。
資料源：TWSE `fund/T86`（三大法人買賣超日報，個股），官方免費、無 token。

用法：
    python3 institution_tracker.py              # 增量抓（用 cache 補最近缺的交易日）→ data.json + HTML
    python3 institution_tracker.py --from-cache # 只用既有 cache 重繪，不連網
    python3 institution_tracker.py --days 24    # 保留幾個交易日（預設 24，供 20 日排行＋連買連賣）

外資 = 外陸資買賣超股數(不含外資自營商)（T86 欄 4）
投信 = 投信買賣超股數（T86 欄 10）
只留 4 碼普通股（排除 00xx ETF、6 碼權證）。買賣超以「張」顯示（股數/1000）。
"""
import urllib.request
import json
import datetime
import time
import sys
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT_DIR = ROOT / "chip_reports"
CACHE_PATH = HERE / "institution_cache.json"     # {date: {code: [name, foreign_net_shares, trust_net_shares]}}
DATA_PATH = HERE / "institution_data.json"        # 前端用的排行結果
HTML_PATH = OUT_DIR / "法人買賣超.html"

KEEP_DAYS = 24          # 保留交易日數（>=20 供 20 日排行；多幾天讓連買連賣不被邊界截斷）
PERIODS = [1, 5, 20]
TOPN = 10


def _int(s):
    s = (s or "").strip().replace(",", "")
    if s in ("", "-", "--"):
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


def is_common_stock(code):
    """只留 4 碼普通股：首碼 1-9、四位數字（排除 0050 等 ETF、6 碼權證/TDR）。"""
    return len(code) == 4 and code.isdigit() and code[0] != "0"


def fetch_t86(date_yyyymmdd):
    """抓某日 T86。回 {code: [name, foreign_net, trust_net]}；非交易日回 None。"""
    url = (f"https://www.twse.com.tw/rwd/zh/fund/T86"
           f"?date={date_yyyymmdd}&selectType=ALLBUT0999&response=json")
    req = urllib.request.Request(url, headers=UA)
    raw = urllib.request.urlopen(req, timeout=25).read()
    d = json.loads(raw.decode("utf-8"))
    if d.get("stat") != "OK":
        return None
    rows = d.get("data") or []
    if not rows:
        return None
    out = {}
    for r in rows:
        code = (r[0] or "").strip()
        if not is_common_stock(code):
            continue
        name = (r[1] or "").strip()
        foreign = _int(r[4])    # 外陸資買賣超股數(不含外資自營商)
        trust = _int(r[10])     # 投信買賣超股數
        out[code] = [name, foreign, trust]
    return out


def load_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def refresh(days=KEEP_DAYS):
    """從今天往回掃日曆日，補齊 cache 到 `days` 個交易日；跳過已快取的日期。"""
    cache = load_cache()
    today = datetime.date.today()
    have = set(cache.keys())
    got = 0
    d = today
    attempts = 0
    # 掃回最多 days*2.2 個日曆日（含假日緩衝）
    while got < days and attempts < int(days * 2.2) + 10:
        attempts += 1
        iso = d.isoformat()
        ymd = d.strftime("%Y%m%d")
        if d.weekday() < 5:   # 只試平日
            if iso in have:
                got += 1
            else:
                try:
                    res = fetch_t86(ymd)
                    if res:
                        cache[iso] = res
                        have.add(iso)
                        got += 1
                        print(f"  fetched {iso}: {len(res)} 檔")
                        save_cache(cache)          # 逐日存，斷了也不白抓
                        time.sleep(0.6)
                    else:
                        # 非交易日（休市），不算數、不 sleep 太久
                        time.sleep(0.3)
                except Exception as e:
                    print(f"  {iso} error: {e}; backoff 3s 重試一次")
                    time.sleep(3)
                    try:
                        res = fetch_t86(ymd)
                        if res:
                            cache[iso] = res; have.add(iso); got += 1
                            save_cache(cache); time.sleep(0.6)
                    except Exception as e2:
                        print(f"  {iso} 二次失敗: {e2}，跳過")
        d -= datetime.timedelta(days=1)
    # 只保留最近 days 個交易日，超過的丟掉（避免 cache 無限膨脹）
    keep = sorted(cache.keys())[-days:]
    cache = {k: cache[k] for k in keep}
    save_cache(cache)
    return cache


def streak(daily_nets):
    """由最新往回數同號連續天數。回 (+N=連買N, -N=連賣N, 0=無/當日0)。"""
    if not daily_nets:
        return 0
    last = daily_nets[-1]
    if last == 0:
        return 0
    sign = 1 if last > 0 else -1
    n = 0
    for v in reversed(daily_nets):
        if (v > 0 and sign > 0) or (v < 0 and sign < 0):
            n += 1
        else:
            break
    return sign * n


def build_rankings(cache):
    dates = sorted(cache.keys())                       # 舊→新
    # 每檔每日淨額（股數），外資/投信分開；name 取最後出現的
    codes = {}
    for iso in dates:
        for code, (name, f, t) in cache[iso].items():
            e = codes.setdefault(code, {"name": name, "f": {}, "t": {}})
            e["name"] = name
            e["f"][iso] = f
            e["t"][iso] = t

    def daily_list(series):
        return [series.get(iso, 0) for iso in dates]

    result = {"generated": dates[-1] if dates else "", "dates": dates,
              "foreign": {}, "trust": {}}

    for who, key in (("foreign", "f"), ("trust", "t")):
        for p in PERIODS:
            window = dates[-p:] if p <= len(dates) else dates
            rows = []
            for code, e in codes.items():
                series = e[key]
                net = sum(series.get(iso, 0) for iso in window)     # 期間累計（股數）
                if net == 0:
                    continue
                st = streak(daily_list(series))                     # 當前連買/連賣（全窗口）
                rows.append({
                    "code": code, "name": e["name"],
                    "net": round(net / 1000),                        # 張
                    "streak": st,
                })
            buy = sorted([r for r in rows if r["net"] > 0], key=lambda r: -r["net"])[:TOPN]
            sell = sorted([r for r in rows if r["net"] < 0], key=lambda r: r["net"])[:TOPN]
            result[who][str(p)] = {"buy": buy, "sell": sell}
    return result


# ----------------------------- HTML -----------------------------
_TEMPLATE = r"""<!doctype html>
<html lang="zh-Hant" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>法人買賣超前十大</title>
<style>
:root{
  --bg:#eef1f5; --panel:#ffffff; --ink:#1a2230; --muted:#6b7686; --hair:#e4e8ee;
  --grid:#eef1f5; --axis:#aab2be; --sub:#8b95a4;
  --up:#d0342c; --down:#1f9d57;               /* 台股慣例：紅買綠賣 */
  --foreign:#2f6df0; --trust:#e8912b; --fill:#3d7bf0;
  --buybg:rgba(208,52,44,.09); --sellbg:rgba(31,157,87,.10);
  --shadow:0 1px 2px rgba(20,30,50,.05),0 6px 20px rgba(20,30,50,.06);
  --font:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang TC","Noto Sans TC",sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0e1218; --panel:#161c26; --ink:#e8edf4; --muted:#8b97a8; --hair:#242c38;
    --grid:#1c232e; --axis:#3a4552; --sub:#7c8798;
    --up:#ff5a4d; --down:#25c274; --foreign:#4d89ff; --trust:#f0a53a; --fill:#4d89ff;
    --buybg:rgba(255,90,77,.13); --sellbg:rgba(37,194,116,.13);
    --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.35);
  }
}
:root[data-theme="light"]{
  --bg:#eef1f5; --panel:#ffffff; --ink:#1a2230; --muted:#6b7686; --hair:#e4e8ee;
  --grid:#eef1f5; --axis:#aab2be; --sub:#8b95a4;
  --up:#d0342c; --down:#1f9d57; --foreign:#2f6df0; --trust:#e8912b; --fill:#3d7bf0;
  --buybg:rgba(208,52,44,.09); --sellbg:rgba(31,157,87,.10);
  --shadow:0 1px 2px rgba(20,30,50,.05),0 6px 20px rgba(20,30,50,.06);
}
:root[data-theme="dark"]{
  --bg:#0e1218; --panel:#161c26; --ink:#e8edf4; --muted:#8b97a8; --hair:#242c38;
  --grid:#1c232e; --axis:#3a4552; --sub:#7c8798;
  --up:#ff5a4d; --down:#25c274; --foreign:#4d89ff; --trust:#f0a53a; --fill:#4d89ff;
  --buybg:rgba(255,90,77,.13); --sellbg:rgba(37,194,116,.13);
  --shadow:0 1px 2px rgba(0,0,0,.3),0 6px 20px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--font);
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums;
  padding:max(14px,env(safe-area-inset-top)) 14px calc(24px + env(safe-area-inset-bottom));}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;
  gap:6px 14px;margin:2px 2px 14px}
h1{font-size:20px;font-weight:700;letter-spacing:.3px;margin:0}
.sub{color:var(--muted);font-size:12.5px}
.sub b{color:var(--ink);font-weight:600}
.controls{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0 2px 14px}
.seg{display:inline-flex;gap:3px;background:var(--panel);border:1px solid var(--hair);
  border-radius:10px;padding:3px;box-shadow:var(--shadow)}
.seg button{border:0;background:transparent;color:var(--muted);font-family:var(--font);
  font-size:12.5px;font-weight:600;padding:5px 14px;border-radius:8px;cursor:pointer;
  letter-spacing:.2px;transition:background .12s,color .12s}
.seg button:hover{color:var(--ink)}
.seg button.on{background:var(--fill);color:#fff}
.pill{border:1px solid var(--hair);background:var(--panel);color:var(--muted);
  font-family:var(--font);font-size:12.5px;font-weight:600;padding:8px 13px;border-radius:10px;
  cursor:pointer;box-shadow:var(--shadow);letter-spacing:.2px}
.pill:hover{color:var(--ink)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:840px){.grid{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--hair);border-radius:14px;
  padding:14px 15px 12px;box-shadow:var(--shadow);min-width:0}
.ptitle{font-size:15px;font-weight:700;letter-spacing:.2px;margin:0 0 2px;display:flex;
  align-items:center;gap:8px}
.ptitle .dot{width:10px;height:10px;border-radius:3px;display:inline-block}
.ptitle.foreign .dot{background:var(--foreign)} .ptitle.trust .dot{background:var(--trust)}
.ptitle .pnote{color:var(--sub);font-size:11.5px;font-weight:500;margin-left:auto}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:8px}
@media (max-width:520px){.cols{grid-template-columns:1fr}}
.side-h{font-size:12px;font-weight:700;letter-spacing:.3px;margin:2px 2px 6px;
  display:flex;align-items:center;justify-content:space-between}
.side-h.buy{color:var(--up)} .side-h.sell{color:var(--down)}
.side-h span{color:var(--sub);font-weight:500;font-size:10.5px}
table{width:100%;border-collapse:collapse}
td{padding:5px 4px;border-bottom:1px solid var(--hair);vertical-align:middle}
tr:last-child td{border-bottom:0}
.rk{color:var(--sub);font-size:11px;width:16px;text-align:center}
.nm{line-height:1.2}
.nm b{font-size:13px;font-weight:600}
.nm .cd{color:var(--sub);font-size:10.5px;margin-left:1px}
.net{text-align:right;font-weight:700;font-size:13px;white-space:nowrap}
.net.buy{color:var(--up)} .net.sell{color:var(--down)}
.net .u{color:var(--sub);font-weight:500;font-size:10px;margin-left:1px}
.stk{text-align:right;white-space:nowrap;width:64px}
.badge{display:inline-block;font-size:10.5px;font-weight:700;padding:2px 6px;border-radius:6px;letter-spacing:.2px}
.badge.b{color:var(--up);background:var(--buybg)}
.badge.s{color:var(--down);background:var(--sellbg)}
.badge.none{color:var(--sub);background:transparent;font-weight:500}
.empty{color:var(--sub);font-size:12px;padding:10px 2px}
footer{color:var(--muted);font-size:11.5px;text-align:center;margin-top:18px;line-height:1.6}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>法人買賣超前十大</h1>
    <div class="sub">資料截至 <b>__GEN__</b> · <span id="plabel">近 1 日</span> · 上市（TWSE T86，官方免費）</div>
  </header>
  <div class="controls">
    <div class="seg" id="periods">
      <button data-p="1">1日</button><button data-p="5">5日</button><button data-p="20">20日</button>
    </div>
    <button id="themeBtn" class="pill" type="button" title="切換淺色／深色主題">🌙 深色</button>
  </div>
  <div class="grid" id="grid"></div>
  <footer>
    買賣超單位＝張（股數/1000），<span style="color:var(--up)">紅=買超</span> / <span style="color:var(--down)">綠=賣超</span> ·
    連買/連賣＝該法人每日淨額同號連續天數 · 僅上市 4 碼普通股（排除 ETF/權證）<br>
    外資＝外陸資買賣超（不含外資自營商）· 投信＝投信買賣超 · 數字取自 TWSE 官方，未經加工
  </footer>
</div>
<script>
const DATA = /*__DATA__*/;
let P = "1";
try{ if(["1","5","20"].includes(localStorage.getItem("instP"))) P=localStorage.getItem("instP"); }catch(e){}
const PLABEL={"1":"近 1 日","5":"近 5 日","20":"近 20 日"};

let THEME="light";
try{ if(localStorage.getItem("chipTheme")==="dark") THEME="dark"; }catch(e){}
document.documentElement.setAttribute("data-theme",THEME);

const fmt = n => (n<0?"-":"")+Math.abs(n).toLocaleString("en-US");
function badge(st){
  if(st>0) return `<span class="badge b">連買${st}</span>`;
  if(st<0) return `<span class="badge s">連賣${-st}</span>`;
  return `<span class="badge none">—</span>`;
}
function rows(list, side){
  if(!list||!list.length) return `<div class="empty">無資料</div>`;
  return `<table>${list.map((r,i)=>`
    <tr>
      <td class="rk">${i+1}</td>
      <td class="nm"><b>${r.name}</b><span class="cd">${r.code}</span></td>
      <td class="net ${side}">${fmt(r.net)}<span class="u">張</span></td>
      <td class="stk">${badge(r.streak)}</td>
    </tr>`).join("")}</table>`;
}
function panel(who, title, cls){
  const d = DATA[who][P] || {buy:[],sell:[]};
  return `<div class="panel">
    <div class="ptitle ${cls}"><span class="dot"></span>${title}
      <span class="pnote">${PLABEL[P]}買賣超</span></div>
    <div class="cols">
      <div><div class="side-h buy">買超前十<span>張</span></div>${rows(d.buy,"buy")}</div>
      <div><div class="side-h sell">賣超前十<span>張</span></div>${rows(d.sell,"sell")}</div>
    </div>
  </div>`;
}
function build(){
  document.getElementById("grid").innerHTML =
    panel("foreign","外資","foreign") + panel("trust","投信","trust");
  document.getElementById("plabel").textContent = PLABEL[P];
  document.querySelectorAll("#periods button").forEach(b=>b.classList.toggle("on",b.dataset.p===P));
}
document.querySelectorAll("#periods button").forEach(b=>{
  b.addEventListener("click",()=>{P=b.dataset.p;try{localStorage.setItem("instP",P);}catch(e){}build();});
});
const themeBtn=document.getElementById("themeBtn");
function syncTheme(){themeBtn.textContent=THEME==="dark"?"☀️ 淺色":"🌙 深色";}
themeBtn.addEventListener("click",()=>{
  THEME=THEME==="dark"?"light":"dark";
  document.documentElement.setAttribute("data-theme",THEME);
  try{localStorage.setItem("chipTheme",THEME);}catch(e){}
  syncTheme();
});
syncTheme();
build();
</script>
</body>
</html>
"""


def build_html(data):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = _TEMPLATE.replace("/*__DATA__*/", json.dumps(data, ensure_ascii=False))
    html = html.replace("__GEN__", data.get("generated", ""))
    HTML_PATH.write_text(html, encoding="utf-8")
    print("wrote", HTML_PATH)


def main():
    args = sys.argv[1:]
    days = KEEP_DAYS
    if "--days" in args:
        days = int(args[args.index("--days") + 1])
    if "--from-cache" in args:
        cache = load_cache()
        if not cache:
            raise SystemExit("cache 為空，請先不加 --from-cache 跑一次")
    else:
        print(f"抓 T86，目標 {days} 個交易日…")
        cache = refresh(days)
    data = build_rankings(cache)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"排行完成：{len(data['dates'])} 交易日，generated={data['generated']}")
    build_html(data)


if __name__ == "__main__":
    main()
