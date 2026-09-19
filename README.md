# のどっち Mahjong AI

以 [Mortal](https://github.com/Equim-chan/Mortal)（AGPL-3.0）為基礎的日本麻將 AI 開發項目，重點在 **模型蒸餾（distill）訓練**：以強 AI 的對局評測資料為教師訊號，訓練單人專屬風格的麻雀 AI。

## 項目結構

```
libriichi/     Rust 引擎（來源 Mortal 上游，包含 tensor 核心與 mjai 通訊）
mortal/        Python 訓練 / 推理 / 蒸餾訓練（distill.py、dataloader、模型定義）
reviewer/      工具鏈：bigcoach / gokujan API 譜抓取、mjai-reviewer 風格 HTML 回放導出、
               html_runs → distill 資料集建構（api_to_distill / html_to_distill）
docs/          文件（mdbook，來源 Mortal 上游）
exe-wrapper/   Rust 執行檔包裝（含 GUI 啟動器）
```

## 資料集工作流程

1. 抓取強 AI的評測對局（`fetch_api_reviews.py`）
2. 轉換成訓練資料（`api_to_distill.py --no-convert` → `html_to_distill.py --gid …`，merge 進 `mortal/distill/targets.pt`，key 為 `<taskId>_s<seat>`）
3. 以 `distill.py` 進行蒸餾監督訓練
4. 產出 HTML 回放供人工檢視（`render_report/`，含回放 iframe、繁中渲染）

> 注意：大檔案（.venv、模型權重、reviewer/out 等）不納入版本控制，請見 `.gitignore`。

## 授權

- 程式碼：AGPL-3.0-or-later（繼承自 Mortal，Copyright (C) 2021-2022 Equim）
- 圖示與其他素材：CC BY-SA 4.0（來源 Mortal 上游）
