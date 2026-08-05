# 台股籌碼儀表板（公開・免登入）

外資期/選未平倉 · 台指期近月 · 上市融資餘額。資料全部來自 **TAIFEX / TWSE 官方免費端點**（無 token、無帳密），每個交易日盤後自動更新。

- **網站**：GitHub Pages（見 repo 的 Pages 設定）
- **加到主畫面**：手機瀏覽器開網站 → 分享 → 「加入主畫面」，會變成獨立 App 圖示，全螢幕、免登入。

## 架構

| 檔案 | 作用 |
|------|------|
| `dashboard/chip_tracker.py` | 抓 TAIFEX/TWSE 官方資料 + 產 HTML（純 stdlib，無依賴） |
| `dashboard/chip_data.json` | 近 2 年資料快取（增量更新） |
| `chip_reports/籌碼儀表板.html` | chip_tracker 產出的完整頁面 |
| `build_page.py` | 注入 PWA 標籤 → 根目錄 `index.html`（Pages 首頁） |
| `manifest.webmanifest` / `icon-*.png` | 「加到主畫面」用的 App 資訊與圖示 |
| `.github/workflows/daily.yml` | 平日 16:10 TW 盤後：抓資料→重繪→commit（觸發 Pages 部署） |

## 本機重繪

```bash
python3 dashboard/chip_tracker.py     # 抓資料 + 產 chip_reports/*.html
python3 build_page.py                 # 產 index.html（含 PWA 標籤）
python3 make_icons.py                 # 重新產圖示（改設計時才需要）
```

> chip_tracker.py 與私有主 repo（evan-portfolio-dashboard）保持同步；Pages 專屬的東西只加在 build_page.py / manifest / 圖示，不動 chip_tracker.py。
