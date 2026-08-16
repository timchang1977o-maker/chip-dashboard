# Henry 區資料更新 SOP（henry_data.json 重萃取）

美股財報頁的 **Henry · Pentimetrics 區**資料來自 `henry_data.json`（快照，非自動）。
Allen 區走 cover list、GHA 每日自動；Henry 區需下列人工重萃取（因 pentimetrics_db 只在本機、
是付費內容不進公開 repo，且散文需 LLM 判讀，不能 regex）。

## 何時做
- 財報季每週一次，或你匯入一批新 The Trace 之後。
- 觸發語：跟 Claude 說「**更新 Henry 財報頁**」。

## 步驟
1. **新文進庫**（你既有流程）：`cd /Users/mac/Downloads/Evan.agent/vocus/pentimetrics_db && python3 build_db.py`（增量）。
2. **重萃取數據**：派子代理跑「Prompt A」→ 覆寫 `/Users/mac/chip-dashboard/henry_data.json`。
3. **補立場**：派子代理跑「Prompt B」→ 就地補 `stance` + `stance_evidence`。
4. **重建＋部署**：
   ```
   cd /Users/mac/chip-dashboard && python3 build_us_earnings.py
   git add henry_data.json us_earnings.html
   git commit -m "chore(us-earnings): refresh Henry snapshot"
   git -c credential.helper='!gh auth git-credential' push https://github.com/timchang1977o-maker/chip-dashboard.git HEAD:main
   ```
   （push 用 gh 認證，內嵌 PAT 已失效。）

## Prompt A（數據萃取）— 重點
從 pentimetrics.db paragraphs 掃每檔「最新一筆有量化市場共識的財報段落」，抽：
ticker/company/quarter/actual_rev/cons_rev/buyside_rev/actual_eps/cons_eps/guide/view/src_date/src_label。
**只抄原文數字、缺值 null、不推算**；金額保留原文單位幣別；SPCX 等紀念股/未上市/非美股排除；
只有券商預覽無實際財報的（如未到財報日的 NVDA/MU）不收。輸出 JSON 陣列，依 src_date 新→舊。

## Prompt B（立場判定）— 重點
逐檔回源文（用 src_label/src_date 定位該篇）依 **Henry 本人評語**判 stance（六選一：
看多／中性偏多／中性／中性偏空／偏空／追蹤），附 stance_evidence（原文片語≤40字）。
**不可因數字 beat 就判看多**（Henry 常 beat 卻評中性/中性偏上）。就地補進 henry_data.json。

完整 prompt 見 git 歷史對應 commit 或 memory `project_chip_dashboard`。
