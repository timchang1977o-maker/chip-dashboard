#!/usr/bin/env python3
"""把 tracker 產出的 chip_reports/*.html 包成 GitHub Pages 頁面。

做三件事：
  1. 在 <head> 注入 PWA 標籤（manifest / apple-touch-icon / theme-color）。
  2. 在 .wrap 頂端注入共用頂部導覽（籌碼總覽 ↔ 法人買賣超），當前頁高亮。
  3. 寫成 repo 根目錄的 index.html / institutions.html，供 Pages 直接服務。

tracker 本身（chip_tracker.py / institution_tracker.py）維持與私有 repo 同步、不改，
所有 Pages 專屬（PWA、跨頁導覽）都集中在這裡加。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CR = ROOT / "chip_reports"

PWA_HEAD = """
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#eef1f5">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="籌碼">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="icon" href="favicon.ico">
"""

NAV_STYLE = """
<style id="topnav-style">
.topnav{display:flex;gap:6px;margin:0 2px 12px;flex-wrap:wrap}
.topnav a{font:600 13px var(--font,-apple-system,"PingFang TC",sans-serif);
  color:var(--muted,#6b7686);text-decoration:none;padding:7px 14px;border-radius:10px;
  border:1px solid var(--hair,#e4e8ee);background:var(--panel,#fff);letter-spacing:.2px;
  box-shadow:var(--shadow,0 1px 2px rgba(20,30,50,.05));transition:color .12s,background .12s}
.topnav a:hover{color:var(--ink,#1a2230)}
.topnav a.on{background:var(--fill,#3d7bf0);color:#fff;border-color:var(--fill,#3d7bf0)}
</style>
"""

# (來源 bare html, 輸出檔, 此頁 key)
PAGES = [
    ("籌碼儀表板.html", "index.html", "chips"),
    ("法人買賣超.html", "institutions.html", "inst"),
]

TABS = [("index.html", "chips", "📊 籌碼總覽"),
        ("institutions.html", "inst", "🏦 法人買賣超")]


def nav_html(current):
    links = ""
    for href, key, label in TABS:
        cls = ' class="on"' if key == current else ""
        links += f'<a href="{href}"{cls}>{label}</a>'
    return f'<nav class="topnav">{links}</nav>'


def build_one(src_name, out_name, current):
    src = CR / src_name
    if not src.exists():
        print("skip（找不到來源）:", src)
        return
    html = src.read_text(encoding="utf-8")
    # Pages 專屬：ETF 分頁在 Render 指向同源 /etf（需登入）；Pages 站沒有該路由，
    # 改指本 repo 內的自含靜態頁 etf.html（免登入）。tracker 原始碼維持與私有 repo 同源。
    html = html.replace('.setAttribute("src","/etf")', '.setAttribute("src","etf.html")')
    html = html.replace('href="/etf"', 'href="etf.html"')
    if "manifest.webmanifest" not in html and "</title>" in html:
        html = html.replace("</title>", "</title>" + PWA_HEAD, 1)
    if 'class="topnav"' not in html and '<div class="wrap">' in html:
        html = html.replace('<div class="wrap">',
                             '<div class="wrap">\n' + NAV_STYLE + nav_html(current), 1)
    (ROOT / out_name).write_text(html, encoding="utf-8")
    print("wrote", ROOT / out_name)


def main():
    for src_name, out_name, current in PAGES:
        build_one(src_name, out_name, current)


if __name__ == "__main__":
    main()
