#!/usr/bin/env python3
"""把 chip_tracker.py 產出的 chip_reports/籌碼儀表板.html 包成 GitHub Pages 首頁。

只做兩件事：
  1. 在 <head> 注入 PWA 標籤（manifest / apple-touch-icon / theme-color），
     讓手機可「加到主畫面」變成 App 圖示。
  2. 寫成 repo 根目錄的 index.html，供 Pages 直接服務。

chip_tracker.py 本身維持與私有 repo 同步（不改），所有 Pages 專屬的東西都在這裡加。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "chip_reports" / "籌碼儀表板.html"
OUT = ROOT / "index.html"

PWA_HEAD = """
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#0e1218">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="籌碼">
<link rel="apple-touch-icon" href="icon-180.png">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="icon" href="favicon.ico">
"""


def main():
    html = SRC.read_text(encoding="utf-8")
    anchor = "</title>"
    if anchor not in html:
        raise SystemExit("找不到 </title>，無法注入 PWA 標籤")
    if "manifest.webmanifest" not in html:
        html = html.replace(anchor, anchor + PWA_HEAD, 1)
    OUT.write_text(html, encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
