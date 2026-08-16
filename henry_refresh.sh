#!/usr/bin/env bash
# 一鍵重萃 Henry 區 → 重建美股財報頁 → 部署。
# 需求：本機開著、claude CLI 已登入、gh CLI 已登入（push 用）。
# 用法：/Users/mac/chip-dashboard/henry_refresh.sh
#   （財報季每週跑一次即可；Allen 區另走 GHA 全自動，不需這支。）
set -uo pipefail

DB=/Users/mac/Downloads/Evan.agent/vocus/pentimetrics_db
CHIP=/Users/mac/chip-dashboard
JSON="$CHIP/henry_data.json"
LOG="$CHIP/henry_refresh.log"
MODEL="claude-opus-4-8"

echo "===== Henry refresh $(date '+%Y-%m-%d %H:%M') =====" | tee -a "$LOG"

# ① 增量把新 The Trace 進庫（沒有新檔就無變化；失敗不擋，續用現有 DB）
echo "① build_db（增量入庫）…" | tee -a "$LOG"
( cd "$DB" && python3 build_db.py ) >>"$LOG" 2>&1 || echo "  build_db 跳過/失敗，續用現有 DB" | tee -a "$LOG"

# ② 備份現有快照（壞了要能還原）
cp "$JSON" "$JSON.bak"

# ③ 本機呼叫 claude 無介面重萃取（含立場）→ 覆寫 henry_data.json
echo "② claude 重萃取中（數分鐘，log 見 henry_refresh.log）…" | tee -a "$LOG"
if ! claude -p "$(cat "$CHIP/henry_extract_prompt.txt")" \
        --model "$MODEL" \
        --dangerously-skip-permissions >>"$LOG" 2>&1; then
  echo "✗ claude 執行失敗，還原備份、中止。" | tee -a "$LOG"
  mv "$JSON.bak" "$JSON"; exit 1
fi

# ④ 驗證輸出（筆數 / 必填欄位）；不過就還原、不佈爛資料
echo "③ 驗證…" | tee -a "$LOG"
if ! python3 - "$JSON" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert isinstance(d,list) and len(d)>=20, f"筆數太少：{len(d)}"
bad=[x.get("ticker") for x in d if not x.get("ticker") or not x.get("stance")]
assert not bad, f"缺 ticker/stance：{bad}"
asof=max((x.get("src_date","") for x in d), default="")
print(f"OK {len(d)} 檔，資料截至 {asof}")
PY
then
  echo "✗ 驗證未過，還原備份、中止。" | tee -a "$LOG"
  mv "$JSON.bak" "$JSON"; exit 1
fi
rm -f "$JSON.bak"

# ⑤ 重建頁面（同時抓 cover list 最新 Allen 數字）
echo "④ 重建 us_earnings.html…" | tee -a "$LOG"
( cd "$CHIP" && python3 build_us_earnings.py ) | tee -a "$LOG"

# ⑥ commit + push（push 走 gh 認證；無變更就跳過）
echo "⑤ 部署…" | tee -a "$LOG"
cd "$CHIP"
git add henry_data.json us_earnings.html
if git diff --staged --quiet; then
  echo "（無變更，不用部署）" | tee -a "$LOG"; exit 0
fi
git commit -q -m "chore(us-earnings): refresh Henry snapshot $(date +%Y-%m-%d)"
git -c credential.helper='!gh auth git-credential' push \
    https://github.com/timchang1977o-maker/chip-dashboard.git HEAD:main >>"$LOG" 2>&1 \
  && echo "✅ 完成，線上約 1 分鐘後更新。" | tee -a "$LOG" \
  || { echo "✗ push 失敗（檢查 gh 登入）。" | tee -a "$LOG"; exit 1; }
