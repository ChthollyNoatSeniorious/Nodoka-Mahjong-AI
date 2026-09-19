# 本地 Mortal 跑谱工具（支持自定义 .pth）

对标 <https://mjai.ekyu.moe> 的跑谱功能：输入**天凤 URL** 或**雀魂牌譜链接/文件**，指定**坐席**，
用**你自己的 `.pth` 模型**复盘，并看到**每一打的 AI 权重（Q 值 / 概率）**。
报告界面就是官方 mjai.ekyu.moe 的同款 UI。

## 支持的输入

| 输入 | 用法 | 说明 |
|------|------|------|
| **天凤 URL** | `-u "https://tenhou.net/0/?log=...&tw=2"` | 直接抓取，`?tw=N` 自动作为坐席 |
| **雀魂牌譜链接** | `-u "https://game.maj-soul.com/1/?paipu=..."` | **免登录**：经牌谱服务抓取并转成 Tenhou JSON；坐席从链接 `_a<账号>` 自动识别 |
| **雀魂牌譜文件** | `-i log.json -a 2` | 用 `downloadlogs.js` 油猴脚本自行导出 |
| **tenhou.net/6 JSON** | `-i file.json -a 2` | 任意本地牌谱 |

## 组成

| 路径 | 说明 |
|------|------|
| `mjai-reviewer-master/` | 官方 Rust 后端（[killerducky/mjai-reviewer](https://github.com/killerducky/mjai-reviewer)）：抓取/转换牌谱 → 调用 Mortal → 生成 HTML 报告 |
| `mortal-wrapper/` | 把 `mortal/mortal.py`（review 模式）包装成 exe，供 mjai-reviewer 以 `--mortal-exe` 调用 |
| `review.py` | 一键启动器 |
| `mjsoul_fetch.py` | 雀魂链接 → Tenhou JSON（调用公开匿名牌谱服务，免雀魂账号） |
| `downloadlogs.js` | 雀魂牌谱导出油猴脚本（Equim 官方，离线方案用） |
| `tensoul-main/` | [tensoul](https://github.com/Equim-chan/tensoul)：雀魂日志 → tenhou.net/6 转换器（需雀魂账号，备用） |
| `out/` | 生成的报告与中间文件 |

推理引擎复用本项目 `mortal/mortal.py` 的 **review 模式**：mjai-reviewer 以
`MORTAL_REVIEW_MODE=1`、`MORTAL_CFG=<config>` 调用 `<mortal-exe> <坐席>`，通过 stdin/stdout
交换 mjai 事件，`mortal.py` 回填每张牌的 `q_values`、`shanten` 等，结尾输出 `model_tag`
与 GRP `phi_matrix`（顺位概率矩阵）。

## 首次构建

```powershell
cd reviewer\mortal-wrapper        ; cargo build --release
cd ..\mjai-reviewer-master        ; cargo build --release
```

> 若编译被 Windows **Smart App Control** 拦截（`os error 4551`），以管理员运行
> `CiTool.exe -r` 刷新代码完整性策略即可（无需重启）；或关闭 Smart App Control。

## 用法

```powershell
# 雀魂牌譜链接（免登录，坐席自动识别）
python reviewer\review.py -u "https://game.maj-soul.com/1/?paipu=260914-...._a263619576"

# 天凤牌譜链接
python reviewer\review.py -u "https://tenhou.net/0/?log=2019050417gm-0029-0000-4f2a8622&tw=2"

# 雀魂 json 文件（自行导出）+ 指定坐席
python reviewer\review.py -i "C:\logs\mjsoul.json" -a 2

# 换模型 / 只看部分局 / 输出 JSON / 不打开浏览器
python reviewer\review.py -u "..." -m "2024v4best\2024v4best.pth"
python reviewer\review.py -u "..." -k "E1,E3"
python reviewer\review.py -u "..." --json -o out\result.json
python reviewer\review.py -u "..." --no-open --show-rating
```

| 参数 | 说明 |
|------|------|
| `-u/--url` | 天凤 URL 或雀魂牌譜链接 |
| `-i/--in-file` | 本地牌谱文件（tenhou.net/6 / mjlog JSON） |
| `-a/--player-id` | 坐席 0-3（0=起家/东，1=下家，2=对家，3=上家） |
| `-n/--player-name` | 用玩家名指定坐席 |
| `-m/--model` | 自定义 `.pth`（默认 `mortal/output/my_finetuned_model/mortal.pth`） |
| `-o/--out-file` | 报告输出路径（默认 `reviewer/out/report.html`） |
| `--lang` | 报告语言，默认 `zh` |
| `-k/--kyokus` | 只复盘指定局，如 `E1,E4,S3.1` |
| `--json` | 输出 JSON 而非 HTML |
| `--no-open` | 不自动打开浏览器 |
| `--show-rating` | 报告里显示 rating |
| `--paipu-service` | 雀魂牌谱抓取服务地址（默认 `https://ninklang.tech`） |

## 雀魂牌谱获取的三条路

1. **牌譜链接（推荐，免账号）** —— `-u "…?paipu=…"`，本工具调用
   [ninklang.tech](https://ninklang.tech/) 的公开匿名桌面接口，服务端用后台账号抓取并转换。
   受每 IP / 每日额度限制，适合个人使用。
2. **自建/自备服务** —— 若有牌谱服务 API Key，可设环境变量
   `MORTAL_PAIPU_SERVICE_URL` / `MORTAL_PAIPU_API_KEY`（`mjsoul_fetch.py` 的接口格式
   与之兼容，可后续接上 `Bearer` 流程）。
3. **完全离线** —— 浏览器装 Tampermonkey，粘贴 `downloadlogs.js`，在雀魂牌谱页按 **S**
   导出 json，再用 `-i` 复盘；或使用 `tensoul-main/`（需雀魂账号密码）。

## 报告里能看到什么

- 每一步（摸打/副露/立直/和了）的**期望动作 vs 实际动作**；
- 每个候选动作的 **Q 值与 softmax 概率**（即"AI 的权重"），可看到 AI 认为哪张最好；
- **一致率 / rating**（加 `--show-rating`）；
- 每一局的**顺位概率矩阵**（GRP，来自 `phi_matrix`）；
- 内置牌谱播放器（官方同款）。
