#!/usr/bin/env python3
"""
台股大盤融資維持率（上市 + 上櫃）。

公式：整體維持率 = Σ(個股融資餘額張 × 1000 × 收盤價) ÷ 融資金額餘額 × 100
- 上市：TWSE MI_MARGN（個股融資張數 + 融資金額總計）＋ STOCK_DAY_ALL / MI_INDEX 收盤價
- 上櫃：TPEx margin/balance（個股 + summary 融資金總計）＋ dailyQuotes 收盤價
- 停牌/無成交缺收盤價的個股跳過分子（低估極小，7/9 實測缺 1+10 檔）
- 只算融資端，不含融券保證金——與 HiStock 等市場慣用「大盤融資維持率」同口徑

⚠️ 口徑＝市場通用「大盤融資維持率」＝含 ETF 全體融資股票市值 ÷ 融資金額餘額（2026-08-01）：
   分子含 ETF、分母用證交所／櫃買公佈的融資金額統一數值。與玩股網公布值對齊——
   07/31 實測上市 169.81%，與玩股網「大盤融資維持率 169.81%」一字不差。
   （舊版曾對齊「財經 M 平方」排除 ETF 口徑，比含 ETF 低 ~6pp；M 平方已停止公布，
    2026-08-01 改回含 ETF 的市場通用口徑，severity_dot 門檻同步上移回標準值。）
   2026-08-08 起 history 同時存「去 ETF」口徑（*_exetf：市值排除 00 開頭 ETF、分母不變），
   供籌碼儀表板並列比較；主口徑仍為含 ETF（警戒線以含 ETF 為準）。

歷史存 dashboard/tw_margin_history.json，由 chip-daily workflow 每日更新後 commit
（2026-08-24 korea-leverage 停用後改掛過來；Pages repo 也有一份自己跑），
web/app.py 與 portfolio.py 只讀不抓（latest_from_history）。
"""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "tw_margin_history.json"
UA = {"User-Agent": "Mozilla/5.0 (tw-margin tracker)"}
TIMEOUT = 30


def _num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _get_json(url):
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def fetch_twse(datestr):
    """回傳 (per_stock {code: 融資餘額張}, 融資金額餘額仟元)；當日無資料回 (None, None)。"""
    d = _get_json(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
                  f"?date={datestr}&selectType=ALL&response=json")
    if d.get("stat") != "OK":
        return None, None
    tables = d.get("tables") or []
    fin_amt = None
    per_stock = {}
    for t in tables:
        fields = t.get("fields") or []
        data = t.get("data") or []
        if "項目" in fields:  # 信用交易統計總表
            for row in data:
                if str(row[0]).startswith("融資金額"):
                    fin_amt = _num(row[5])  # 今日餘額(仟元)
        elif len(fields) > 10 and data:  # 個股表
            for row in data:
                bal = _num(row[6])  # 融資今日餘額(張)
                if bal and bal > 0:
                    per_stock[str(row[0]).strip()] = bal
    if fin_amt is None or not per_stock:
        return None, None
    return per_stock, fin_amt


def fetch_twse_prices(datestr):
    """收盤價 {code: px}。先試輕量 openapi（僅最新日），日期不合再抓 MI_INDEX。"""
    try:
        rows = _get_json("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL")
        if rows and rows[0].get("Date"):
            roc = rows[0]["Date"]  # 1150709
            west = f"{int(roc[:3]) + 1911}{roc[3:]}"
            if west == datestr:
                return {r["Code"]: _num(r["ClosingPrice"]) for r in rows
                        if _num(r.get("ClosingPrice"))}
    except Exception as e:
        print(f"[warn] STOCK_DAY_ALL: {e}", file=sys.stderr)
    d = _get_json(f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                  f"?date={datestr}&type=ALLBUT0999&response=json")
    if d.get("stat") != "OK":
        return None
    for t in d.get("tables") or []:
        fields = t.get("fields") or []
        if "收盤價" in fields and "證券代號" in fields:
            ci, cp = fields.index("證券代號"), fields.index("收盤價")
            return {str(r[ci]).strip(): _num(r[cp]) for r in (t.get("data") or [])
                    if _num(r[cp])}
    return None


def fetch_tpex(datestr):
    """回傳 (per_stock {code: 融資餘額張}, 融資金額餘額仟元, prices)；無資料回 (None,)*3。"""
    slash = f"{datestr[:4]}/{datestr[4:6]}/{datestr[6:]}"
    d = _get_json(f"https://www.tpex.org.tw/www/zh-tw/margin/balance"
                  f"?date={slash}&response=json")
    tables = d.get("tables") or []
    if not tables or not tables[0].get("data"):
        return None, None, None
    t = tables[0]
    per_stock = {}
    for row in t["data"]:
        bal = _num(row[6])  # 資餘額(張)
        if bal and bal > 0:
            per_stock[str(row[0]).strip()] = bal
    fin_amt = None
    for row in t.get("summary") or []:
        if any("融資金" in str(c) for c in row):
            fin_amt = _num(row[6])  # 今日餘額(仟元)
    q = _get_json(f"https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
                  f"?date={slash}&response=json")
    qt = (q.get("tables") or [{}])[0]
    prices = {}
    for row in qt.get("data") or []:
        px = _num(row[2])
        if px:
            prices[str(row[0]).strip()] = px
    if fin_amt is None or not per_stock or not prices:
        return None, None, None
    return per_stock, fin_amt, prices


def fetch_foreign_twse(datestr):
    """上市外資買賣超（元）＝外資及陸資+外資自營商 之買賣超合計；無資料回 None。"""
    try:
        d = _get_json(f"https://www.twse.com.tw/rwd/zh/fund/BFI82U"
                      f"?dayDate={datestr}&type=day&response=json")
    except Exception as e:
        print(f"[warn] BFI82U {datestr}: {e}", file=sys.stderr)
        return None
    if d.get("stat") != "OK":
        return None
    net, hit = 0.0, False
    for row in d.get("data") or []:
        if str(row[0]).startswith("外資"):  # 外資及陸資(不含外資自營商) + 外資自營商
            v = _num(row[3])  # 買賣超(元)
            if v is not None:
                net += v
                hit = True
    return net if hit else None


def fetch_foreign_tpex(datestr):
    """上櫃外資買賣超（元）＝彙總表「外資及陸資合計」買賣超；無資料回 None。"""
    slash = f"{datestr[:4]}/{datestr[4:6]}/{datestr[6:]}"
    try:
        d = _get_json(f"https://www.tpex.org.tw/www/zh-tw/insti/summary"
                      f"?date={slash}&type=Daily&response=json")
    except Exception as e:
        print(f"[warn] tpex insti {datestr}: {e}", file=sys.stderr)
        return None
    for tb in d.get("tables") or []:
        for row in tb.get("data") or []:
            if str(row[0]).replace("　", "").strip() == "外資及陸資合計":
                return _num(row[3])  # 買賣超(元)
    return None


def _is_etf(code):
    """台股 ETF/ETN 代號一律 00 開頭（0050、006208、00631L、00878…）；一般股票不會。"""
    return str(code).strip().startswith("00")


def _collateral(per_stock, prices):
    """分子＝Σ(融資張 × 1000 × 收盤價)。回 (含ETF市值, 去ETF市值, 缺價檔數)。
    - 含ETF＝市場通用／玩股網口徑
    - 去ETF＝財經 M 平方口徑（市值排除 00 開頭 ETF，分母仍用證交所統一融資金額）"""
    tot, ex, miss = 0.0, 0.0, 0
    for code, bal in per_stock.items():
        px = prices.get(code)
        if px is None:
            miss += 1
            continue
        val = bal * 1000 * px
        tot += val
        if not _is_etf(code):
            ex += val
    return tot, ex, miss


def compute_ratio(datestr):
    """算單日維持率；資料未發布/休市回 None。"""
    tw_stock, tw_fin = fetch_twse(datestr)
    if tw_stock is None:
        return None
    tw_px = fetch_twse_prices(datestr)
    if not tw_px:
        return None
    tp_stock, tp_fin, tp_px = fetch_tpex(datestr)
    if tp_stock is None:
        return None
    tw_col, tw_ex, tw_miss = _collateral(tw_stock, tw_px)
    tp_col, tp_ex, tp_miss = _collateral(tp_stock, tp_px)
    tw_fin_ntd = tw_fin * 1000
    tp_fin_ntd = tp_fin * 1000
    # 外資買賣超（同日，上市+上櫃）——次要資料，抓不到存 None、不擋維持率
    f_tw = fetch_foreign_twse(datestr)
    f_tp = fetch_foreign_tpex(datestr)
    entry = {
        "twse_ratio": round(tw_col / tw_fin_ntd * 100, 2),
        "tpex_ratio": round(tp_col / tp_fin_ntd * 100, 2),
        "total_ratio": round((tw_col + tp_col) / (tw_fin_ntd + tp_fin_ntd) * 100, 2),
        # 去 ETF（M 平方口徑：市值排除 ETF，分母仍用證交所統一融資金額）
        "twse_ratio_exetf": round(tw_ex / tw_fin_ntd * 100, 2),
        "tpex_ratio_exetf": round(tp_ex / tp_fin_ntd * 100, 2),
        "total_ratio_exetf": round((tw_ex + tp_ex) / (tw_fin_ntd + tp_fin_ntd) * 100, 2),
        "twse_fin_e8": round(tw_fin_ntd / 1e8, 1),
        "tpex_fin_e8": round(tp_fin_ntd / 1e8, 1),
        "miss": tw_miss + tp_miss,
        "foreign_twse_e8": round(f_tw / 1e8, 1) if f_tw is not None else None,
        "foreign_tpex_e8": round(f_tp / 1e8, 1) if f_tp is not None else None,
        "foreign_total_e8": round((f_tw + f_tp) / 1e8, 1)
        if (f_tw is not None and f_tp is not None) else None,
    }
    return entry


def load_history():
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(hist):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(hist.items())), f, ensure_ascii=False, indent=1)


def update_history(max_back=10):
    """補齊「今天往回 max_back 天」窗口內所有缺漏的交易日；回傳最新 datestr。

    2026-09-05 改版：原本只補最新一天（找到就 break），一旦連續數日沒跑到
    （TWSE 擋雲端 IP、或 workflow 被停用）就會留下永久空洞——8/21~9/4 那個
    十天大洞就是這樣來的。改成掃整個窗口、補所有缺日，之後能自動追回。
    休市日 compute_ratio 第一個請求就回 None，成本低。
    """
    hist = load_history()
    today = date.today()
    changed = False
    for i in range(max_back, -1, -1):          # 由舊到新
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        if ds in hist:
            continue
        entry = compute_ratio(ds)
        time.sleep(2)
        if entry:
            hist[ds] = entry
            changed = True
    if changed:
        save_history(hist)
    return max(hist) if hist else None


def _trailing_streak(seq):
    """seq 由舊到新（可含 None）。回傳末端「連續同號」的 (sign, count)。
    遇 None / 0 / 反號即停。count == 全部非 None 筆數時代表可能更長（受歷史窗長限制）。"""
    sign, cnt = 0, 0
    for v in reversed(seq):
        if v is None:
            break
        s = 1 if v > 0 else (-1 if v < 0 else 0)
        if s == 0:
            break
        if sign == 0:
            sign, cnt = s, 1
        elif s == sign:
            cnt += 1
        else:
            break
    return sign, cnt


def latest_from_history():
    """只讀 history 不打 API——web / portfolio 用。回傳含前日比較與連續天數的 dict 或 None。"""
    hist = load_history()
    if not hist:
        return None
    days = sorted(hist)
    cur = hist[days[-1]]
    out = {
        "date": f"{days[-1][4:6]}/{days[-1][6:]}",
        "fin_total_e8": round(cur["twse_fin_e8"] + cur["tpex_fin_e8"], 1),
        **cur,
    }
    if len(days) >= 2:
        prev = hist[days[-2]]
        out["prev_total_ratio"] = prev["total_ratio"]
        out["d1"] = round(cur["total_ratio"] - prev["total_ratio"], 2)
        out["fin_d1_e8"] = round(out["fin_total_e8"]
                                 - (prev["twse_fin_e8"] + prev["tpex_fin_e8"]), 1)

    # 融資餘額連續增減：對每日餘額取日變化，數末端同號連續天數
    fins = [hist[d]["twse_fin_e8"] + hist[d]["tpex_fin_e8"] for d in days]
    fin_chg = [round(fins[i] - fins[i - 1], 1) for i in range(1, len(fins))]
    fsign, fcnt = _trailing_streak(fin_chg)
    out["fin_streak_sign"] = fsign
    out["fin_streak"] = fcnt
    out["fin_streak_capped"] = fcnt > 0 and fcnt == len(fin_chg)

    # 外資買賣超連續買/賣：直接對每日淨額數同號連續天數
    fx = [hist[d].get("foreign_total_e8") for d in days]
    xsign, xcnt = _trailing_streak(fx)
    n_avail = sum(1 for v in fx if v is not None)
    out["foreign_streak_sign"] = xsign
    out["foreign_streak"] = xcnt
    out["foreign_streak_capped"] = xcnt > 0 and xcnt == n_avail
    return out


def severity_dot(ratio):
    # 含 ETF 市場通用口徑門檻（160 為市場公認警戒線）：
    # 🔴 <160　🟡 160–170　🟢 ≥170
    if ratio is None:
        return "⚪"
    if ratio < 160:
        return "🔴"
    if ratio < 170:
        return "🟡"
    return "🟢"


def fin_streak_text(twm):
    """融資連續增/減字串，如「連3日增」；無連續回空字串。"""
    n = twm.get("fin_streak") or 0
    if not n:
        return ""
    word = "增" if twm.get("fin_streak_sign", 0) > 0 else "減"
    return f"連{n}{'+' if twm.get('fin_streak_capped') else ''}日{word}"


def foreign_dot(net):
    if net is None:
        return "⚪"
    return "🟢" if net > 0 else ("🔴" if net < 0 else "⚪")


def foreign_streak_text(twm):
    """外資連續買超/賣超字串，如「連5日賣超」；無資料回空字串。"""
    n = twm.get("foreign_streak") or 0
    if not n:
        return ""
    word = "買超" if twm.get("foreign_streak_sign", 0) > 0 else "賣超"
    return f"連{n}{'+' if twm.get('foreign_streak_capped') else ''}日{word}"


if __name__ == "__main__":
    # 手動執行：更新最新一天並印出
    ds = update_history()
    print(f"latest: {ds}")
    print(json.dumps(latest_from_history(), ensure_ascii=False, indent=2))
