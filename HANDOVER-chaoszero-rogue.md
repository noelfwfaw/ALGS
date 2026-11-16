# 卡厄思「自动肉鸽」交接文档（CodeBuddy 接手用）

> 写于 2026-11-15 14:5x，作者：上一班 AI。项目：AzurLaneAutoScript（ALAS 多游戏底座）。
> 这个功能**全部还在工作区里没提交**（见 §13），代码能跑、lint 0，但有几处功能没做完（§6）。
> 设备状态：MuMu 127.0.0.1:16448，停在 `配置隊伍`（队伍页，梦境模式已开，110pt，难度 6），
> 三张存档已在本轮测试里全部分解掉，当前进本会重新开始第一面。

---

## 0. 一句话现状

「进本 → 一路自动打 → 局内所有页面都能处理 → 结算/存档页 → 崩溃治疗 → 下一局」这条主链**已经实机跑通过**（多局连续，未卡死）；
**没做完的是**：① 复制卡牌时选哪张卡（现在按 `跳過`，等于不复制）；② 商店页（删卡）一次都没见过；
③ 冥想自动触发需要配 `RogueSparkFilter` 且「卡已闪但形态不对」才可用（实机只验证到网格页）。

最近一次改动（**未复测**，接手先看 §6.8）：新增 `ROGUE_ITEM` 判据 + 分支 `# 0.045`，用来关掉删档/开箱后的
`獲得道具` 弹窗 —— 它的 `點擊畫面可關閉視窗。` 在 x 600~875，老的 `ROGUE_CLICK_CLOSE` 框（505~775）对不上，
这是「删完档卡住」的直接原因。

---

## 1. 必读（按顺序，别跳）

1. `.workbuddy/memory/MEMORY.md` —— 全项目长期约定（单模拟器多游戏、1280x720、`toolkit/python.exe` 3.7.6、adb 必须与应用同一命令…）。
2. `.workbuddy/memory/2026-11-15.md` —— 本功能当天的全部实测记录（最重要，最新在最下面）。
   另外 `.workbuddy/memory/2026-11-14.md` 是入口链/判据/路线读图那天的记录。
3. `.workbuddy/skills/alas-multigame-dev/SKILL.md` —— 框架机制（三套时钟、`appear()` 语义、错误阶梯、任务注册流程）。
   同目录 `references/hard-rules.md` 是跨游戏硬约束，**已排到第 216 条**（216 = 长跑必须持续汇报进度）。
4. `.workbuddy/skills/chaoszero-roguelike/SKILL.md` —— 本功能专用手册，30+ 节全是本机实测：
   入口五页、局内判据、事件库、灵光 OCR、冥想、存档页、崩溃治疗…… 改代码前先查这里。

读文件别用 `Get-Content`（会把 UTF-8 中文变乱码）：
`toolkit\python.exe -u .workbuddy\probe_logtail.py <文件> <行数> head|tail` → 写 `.workbuddy/tail.txt`，再用 read 工具看。

---

## 2. 硬约束（违反就等于返工）

- 每次点击都要有判据；**不许 sleep 串**；等待只能用 `loop(timeout=)` / `wait_until_appear|disappear|still`。
- **不许串击**（用户 2026-11-14 明确要求）：认不出的页面不要按固定坐标连点。
- 资源 PNG **必须是整张 1280x720 帧**，因为框架的 `load_image` 会用 `area` 去裁剪文件；只存小图会得到全黑模板。
- 判据优先用「颜色量 + 实测阈值」，其次模板；卡面立绘每期都换，别拿卡图做模板。
- 改完代码必须 `toolkit\python.exe -m dev_tools.alas_lint --severity high`（0 problems），豁免要写 `# alas-lint: allow` + 理由。
- 错误阶梯：做完 `return` / `task_stop()`；没做完 `task_delay()` + `TaskFailed`；**不许 `raise ScriptEnd`**，`RequestHumanTakeover` 只在必须人工时用（它会 exit(1)）。
- 新任务要 argument.yaml → task.yaml（menu/page/tasks）→ `SCHEDULER_PRIORITY`（`>` 字符串）→ `config_updater` → i18n → algs.py；新页面要 page.py 的 link + UI 类 `pages` 元组。（本任务已全部注册好，见 §9。）
- **测试一律用短测试**（用户 2026-11-15）：「打到第一个信标点就撤退」，别打整局（一局 25 分钟）。
- 长跑（>1 分钟）**每 1-2 分钟汇报一次**：现在在哪一步、看到什么、下一步命令验证什么（hard-rules 216）。

---

## 3. 环境与命令

```bat
:: 解释器（唯一）
toolkit\python.exe                     :: Python 3.7.6

:: adb（不在 PATH；连接和截图必须在同一条命令里）
toolkit\Lib\site-packages\adbutils\binaries\adb.exe connect 127.0.0.1:16448 && ^
toolkit\Lib\site-packages\adbutils\binaries\adb.exe -s 127.0.0.1:16448 exec-out screencap -p > .workbuddy\shots\x.png

:: 点击（adb 的第一次 tap 常被吞，重要操作点两次）
... -s 127.0.0.1:16448 shell input tap 640 300

:: 静态检查
toolkit\python.exe -m dev_tools.alas_lint --severity high
toolkit\python.exe -m py_compile module\chaoszero\rogue.py module\chaoszero\assets.py
toolkit\python.exe -m dev_tools.check_button_templates
toolkit\python.exe -m dev_tools.check_fork_integrity      :: 已知 1 条历史 FAIL：config/alas.json 第20行控制字符，与本功能无关

:: 单任务跑（正式入口）
toolkit\python.exe -m dev_tools.run_task ChaoszeroRogue --no-boot --config chaoszero --serial 127.0.0.1:16448
:: ⚠ 实测 `--config chaoszero` 有时会卡在初始化（日志停在 early_ocr_import）；
::    探针里用 `AlGS(config_name='TEST')` + overridden 两个字段反而是稳的。

:: 全游戏回归
toolkit\python.exe -m dev_tools.patrol_games
```

探针（全部在 `.workbuddy/`，已 gitignore，可随便改）：

- `.workbuddy/probe_rogue_drive.py` —— 主驱动探针。`PROBE 分钟数`，环境变量：
  `ROGUE_TASK=1` 走真实 `ui.run()`（含入口链+多局循环），否则只 `rogue_run()`；
  `ROGUE_DELETE=<n>` 覆盖 `ChaoszeroRogue_RogueDelete`；`ROGUE_RUNS=<n>` 覆盖局数；
  `ROGUE_BIAS_REST=1` 给休息节点 +100 分（专测休息页）；`ROGUE_SAVE_KEEP` 等可自行加。
  日志 `.workbuddy/drive.log`，每 20 秒存一帧 `.workbuddy/shots/drive_NNN.png`。
- `.workbuddy/probe_logtail.py <file> <n> head|tail` → `.workbuddy/tail.txt`（读中文日志唯一可靠办法）。
- `.workbuddy/probe_filter.py <file> <关键词...>` → `.workbuddy/filter.txt`（只打印命中条数）。
- `.workbuddy/probe_taps.py x y [x y...]` —— MaaTouch 点击 + 截图 `.workbuddy/shots/taps_now.png`。
- `.workbuddy/probe_<页面>_asset.py` —— 造模板的模板：复制整帧到 `assets/chaoszero/chaoszero/<NAME>.png`，打印可粘贴的 `Button(...)` 行 + 帧库打分。
- `.workbuddy/probe_stop_beacon.py` —— 「打到第一个航点就停、然后撤退」的短测试骨架，**优先用它改**。
- `.workbuddy/probe_meditate.py` / `probe_rest_verify.py` —— 安全区域/冥想的专项探针。

日志一律写 UTF-8 文件再 read；控制台中文是 GBK 乱码。PowerShell 里 `python -c "..."` 带引号必炸，写 `.py`。

---

## 4. 代码地图

```
module/chaoszero/
  rogue.py          主任务（约 3400 行，状态机 + 所有判据 + 撤退出本 + 治疗）
  rogue_cards.py    灵光三选一：逐行 OCR + 卡牌库认卡 + 按关键词/数值挑列
  rogue_cards.json.gz  卡牌形态库（39 角色 / 520 卡 / 939 形态，由 E7BOT 生成）
  rogue_events.py   事件选项卡决策：选项标题 OCR → 反查事件 → 按奖励类型打分
  rogue_events.json.gz 事件库（406 事件 / 1533 选项，含 pack/chaos/size）
  rogue_route.py    2D 路线读图（节点/立卡识别、合并、打分、规划）
  rogue_ocr.py      繁体单行 OCR（PP-OCRv3 chinese_cht ONNX，只在本功能里用）
module/chaoszero/assets.py          新增 50+ 个 ROGUE_* 模板（全帧 PNG）
bin/ocr_models/                     chinese_cht_PP-OCRv3_rec_infer.onnx + ppocr_keys_v1.txt
dev_tools/gen_chaoszero_rogue_db.py   重新生成事件库（会复用缓存，只发 1 个列表请求）
dev_tools/gen_chaoszero_rogue_cards.py 重新生成卡牌库
```

`rogue.py` 里按顺序大概是：常量区（§8 的表）→ 颜色/模板判据 → 入口链 → 路线规划 → 卡牌/事件决策 → 撤退 → 治疗 → `rogue_run()` 主循环 → `run()`。

主循环 `rogue_run()` 的**分支顺序是有原因的**（§7），改顺序前先读注释。

---

## 5. 已经实机验证过的（可以信）

| 功能 | 判据 / 关键点 | 证据 |
| --- | --- | --- |
| 入口五页链 | 大厅 `卡厄思`(1215,322) → 两卡页 `(330,420)` → 世界列表（标签模板 + 左右滑） → 世界详情 `進入` → 队伍页 `進入`(1200,657) → 确认弹窗 進入(845,596) | 12-18 秒走完，`rogue_enter_team()` |
| 世界选择 | `RogueWorld` 五个世界，标签模板 + 列表可左右拖，最多回拖 2 次、右滑 3 次 | 降臨的混沌（需右滑）实机走通 |
| 梦境模式开关 | 队伍页右上 (1010,35)，开=紫页+110pt，关=原色+100pt | 双向切换实机验过 |
| 局内页判据 | 见 §8 表 | 每一条都写了实测分离度 |
| 战斗 | 不强制点托管；战斗页只等，4 秒静止才点 (950,300)/(860,430)/(760,250) 关敌人面板 | 多局自动打完 |
| 灵光三选一（同卡不同形态） | 繁体 OCR 读三段描述 → 认卡（5/5）→ 按 `RogueSparkFilter` 关键词挑列（5/5），无配置时挑数值最高的一列 | 实机 `Flash card X, take column N` |
| 神闪页 | 标题可能没有；底部 `靈光一閃：<神名>` OCR 判页；神闪卡选不出来就退回 `RoguePick` | 三种不同底色/神名都过 |
| 传令兵（开局三选一） | 场景立绘 `ROGUE_HERALD` + 卡片亮 ∨ 判选中；`RogueHerald` 默认 1（最左，3 场怪物 HP=1） | 点卡 → 点 ∨ 两步 |
| 人物灵光选人 | `請選擇欲獲得【靈光一閃】的戰鬥員。`；暗的立绘点不动（已全闪），挑对比度最高的亮卡 | 选中后 `確認` 变橙 |
| 复制卡牌选人 | `請選擇要複製卡牌的戰鬥員。` 同一套立绘逻辑 | 选人+確認通过 |
| 事件选项卡 | 每卡下沿一条「又宽又稀」的亮边框定位 → 点卡 → 点金色 ∨；已有选中时先确认 | 2/3 卡、航点单卡都过 |
| 事件决策 | 选项标题 OCR(y-125~y-95) → 反查事件（必须每张都对上）→ 按图分域（common 12 + 本图 pack）→ 打分；负分/认不出就退回 `RoguePick` | `食欲` 选中第 2 项(40) 而不是最左(6) |
| 掷骰 | 整页只点一下骰子；`重新擲骰` 永不点（每天 20 点很珍贵） | 实机 |
| 装备页 | 两种形态：①选装备 ②选战斗员槽位；盲点梯 `EQUIP_TAPS`，16 次后按 `返回` | 实机装备成功（HP+60 生效） |
| 删卡页 | 位置盲删最前一格（基础卡总在最前）+ 选中后橙色 `移除`；`RogueDelete`=每局最多删几张 | 实机删过 3 次 |
| 安全区域（休息点） | 训练格模板判页；默认点 `休息`(400,540) → 确认框橙色 `確認`(830,513) → `離開`；`訓練` 永不点 | 实机 HP 2539→2616 |
| 冥想 | 冥想格 (1120,428) 可用才点（三条件：在休息页 + 没有确认框 + `無法使用` 不在）→ 说明框確認(845,483) → 网格选卡 → 再次靈光一閃(1173,670) → 離開 时才出三选一 | 网格页+全链实机走通；自动触发未验 |
| 局内撤退 | ☰ (1229,30) → `撤退`(1135,668) → 确认(845,455) → `探索結果` 紫色 下一步(1122,662) → 整局结算 紫色 確認(1122,660) | 实机多次 |
| 存档页删档 | 标题 OCR `存檔資料收集完成`；垃圾桶 (427/837/1237, 582)；**一次只删一张**，删完弹 `獲得道具` 要关掉（`# 0.045`） | 手动三张全删成功；脚本链路未复测 |
| 崩溃治疗 | 游戏自己弹 `觸發精神異常`（绿色 `治療中心` + 紫色 `下一步`）→ 諮商紀錄 卡位 (537/917,276/526) → 紫色 `消除記憶`(760,669) → 确认 → `批准`(640,351) / ▼(1197,625) → 返回(45,37) | 三个崩溃角色全治好，花费 70,000 金币 |
| 断线恢复 | `卡厄思連線意外中斷。是否要繼續進行？` 模板，只点 `繼續進行`(815,508)，绝不点 `撤退` | 模板 1086 帧分离 OK；点下去能不能生效未验（客户端冻结时按钮也不响应） |
| 多局循环 | `RogueRuns` 局数、`RogueLoop` 是否接着跑 | 2 局连续实机通过 |

---

## 6. 没做完 / 有问题的（**接手先看这里**）

### 6.1 复制卡牌：点了角色就按 `跳過`，等于没复制（用户已报）

- 现象：「复制卡牌那里，点了角色后，就直接跳过了，也就是没有选卡牌，没有进行复制」。
- 现状：`# 4.15` 分支只处理选人页；选人后弹出的**选卡页**没有被识别，落到 `# 2.1` 白色 `跳過` 分支 → 按 `跳過` → 这次复制白给。
- 需要：一张选卡页截图（标题/布局/确认按钮位置），然后照 `# 4.3 删卡页` 的写法做一个 `ROGUE_COPY_CARD` 判据 + 选卡 + 确认。
  选哪张卡：可以用 `rogue_cards` 认卡（选卡页通常带卡名/描述）挑「目标卡」；认不出就选第一张，**别按跳過**。
- 进这一页最快的方式：面末 boss 后的随机复制，或事件里的复制事件（`CARD_COPY_HAVE_SELECT` 系列）。

### 6.2 商店页：一次都没见过

用户规则：**商店只做删卡**，中立卡不买、装备不买；商店和休息不冲突（休息点带不带商店不影响）。
`dev_tools/samples/chaoszero_rogue/` 和 `.workbuddy/shots/` 里都没有商店帧 → 需要用户导一张（或跑一局专门去商店）。

### 6.3 冥想自动触发未验

`rogue_meditate_needed()` = `MED_READY and self.meditate_need`；`meditate_need` 只在「灵光三选一里这张卡**有闪形态**但没有一列符合 `RogueSparkFilter`」时置 True。
所以：不配 `RogueSparkFilter` 永远不会冥想（这是当前默认行为，安全）。配置示例：
`喘氣 = 上膛,痛苦`（一行一张卡，`卡名 = 关键词1,关键词2`，繁体字，数字/百分号读不到别写数字）。

### 6.4 `RogueSaveKeep` 默认值

- 语义：`1/2/3` = 只留该队伍位次的存档（另外两张分解）；`0` = **三个全删**（测试期用）。
- 现在默认 `1`。真刷存档时应让用户明确「刷谁」，因为队伍位次 ≠ 角色；建议后续把配置改成「角色名」而不是位次。
- 删档不是纯损失：分解返 單元幣（实测 21650TB→488、23270TB→465、22070TB→441）。

### 6.5 一局结束的落点不止队伍页

实测三种：
1. `配置隊伍` 队伍页（最常见）；
2. `卡厄思` 两卡页（`卡厄思顯現` / `零號系統`）；
3. 大厅。

`run()` 现在只认 **大厅 / 队伍页**（`TEAM_TITLE`）。落到 `卡厄思` 两卡页时会 `The run did not get back to the lobby, stop here` 提前收工。
修法：把「两卡页（`ROGUE_MODE_ENTRY`）」「世界列表（`ROGUE_WORLD_LIST`）」也算合法落点，`run()` 里当 entry 起点即可（`rogue_enter_team()` 本来就认识这两页）。

### 6.6 缺少「打到第几个信标就停」的能力（用户已抱怨）

用户原话：「脚本没有识别到了哪关的能力……一路打到通关」。
现在只有 `ROGUE_CHECKPOINT`（航点结算页 `結算`）与 `waypoints` 计数，**但没有用它做停机**。
建议加 `RogueStopBeacon: 0`（0=不停）：`waypoints >= n` 时主动 `rogue_quit()`，专门给短测试/控制时长用。

### 6.7 `RogueDelete` 是位置盲删

卡名 OCR 不可靠（`劍光`→`光-`、`劍幕`→`鯽薑`），基础卡也没有 E7BOT 立绘，所以只能「删最前面那张」。
游戏里基础卡（劍光×2/劍幕）总在最前，所以对「删掉前三张基础卡」是有效的；但删第四张就会删到别的卡。
`RogueDelete` 是**每局上限**，不是「删几张就停」，页面出现几次就删几次直到上限。

### 6.8 刚改、还没实机复测的

- `ROGUE_ITEM`（`獲得道具` 弹窗）+ 分支 `# 0.045`：删档（垃圾桶=分解）后必弹这一页，旧的 `ROGUE_CLICK_CLOSE`
  框对不上它的提示文字位置（在 x 600~875）。模板 7 帧 1.0000 / 其余 ≤0.5349，阈值 0.85。
  **这是「删存档没做好」的直接原因**，按逻辑点一下画面就关，但本轮没再遇到弹窗所以没复测。
- `rogue_save_handle()` 的「一次删一张」写法：每帧只删一个未保留的存档，删完图标消失（判据
  `rogue_save_trash_visible()`），全删完才按紫色 `下一步`。逻辑正确性靠手工链路反推，未跑通脚本链路。

### 6.9 `RogueSaveKeep` 语义已改，注意文档与代码一致

`0` 从「三个都留」改成 **「三个全删」**（测试期用）。`1/2/3` = 只留该队伍位次的存档，其余分解。
`argument.yaml` 注释、`zh-CN.json` 的 help、`rogue_save_handle()` docstring 已同步；其它三语是引用式 i18n，不用改。

---

## 7. `rogue_run()` 分支顺序（改顺序会踩坑）

```
# 0.    大厅 / 队伍页 → 这一局结束，return
# 0.005 航点结算页（結算）→ waypoints += 1（只计数，不点）
# 0.01  崩溃页 → 治疗（RogueCure）
# 0.02  断线恢复弹窗 → 只点 繼續進行
# 0.05  梦境模式说明页 → 确认
# 0.055 冥想选卡网格
# 0.045 獲得道具 弹窗（新）
# 0.06  整页说明弹窗（精神異常）
# 0.065 卡牌详情覆盖层（查看詳情）→ 只点 關閉(530,670)，绝不点 靈光一閃(1035,671)
# 0.066 牌堆列表覆盖层（所有牌堆）→ ✕(1203,40)，绝不点卡
# 0.07  敌人详情面板（战斗被暂停）
# 0.1   点击风暴保护（framework 12 次同名点击会重启客户端）
# 0.05  二次确认对话框的橙色 確認
# 1.    战斗页（只等）
# 1.4   带神闪的灵光三选一（底部 靈光一閃：<神名>）
# 1.5   灵光三选一（同一张卡的不同闪形态，必须选）
# 2.    橙色主按钮（確認/繼續進行/獲得/進入）
# 2.01  探索結果 / 整局结算 / 存档页（紫色按钮；存档页先走 rogue_save_handle）
# 2.02  塔罗命运页
# 2.1   只有 跳過/下一步 的页面 ← 复制选卡页现在被这里吞掉（§6.1）
# 4.    剧情 ▼（必须排在传令兵之前：同场景立绘）
# 4.2   传令兵三选一
# 4.5   地图 2D 全图（只能预览，不能移动）→ 点 (100,669) 回 3D
# 4.1   人物灵光选人
# 4.15  复制卡牌选人
# 4.3   删卡页
# 4.7   安全区域（休息/冥想）
# 4.8   地图节点提示卡（先点卡身 (640,600)，再点 ∨ (640,692)）
# 5.    地图（读路线 + 选可达立卡 + 点平台体）
# 4.6   装备页
# 6.    掷骰（只点一下骰子）
# 6.1   白色 跳過/下一步
# 6.5   事件选项卡
# 7.    點擊畫面可關閉視窗 弹窗
# 6.8   演出帧 / 认不出的局内页（4 秒静止才动，SCENE_PATCH 交替点 2 次）
# 7.    认不出 + 没有血条：不串击，最多点底部白色圆点（2~4 个且分散），否则静止 20 秒后撤退
```

编号有重复（历史原因），**以注释和位置为准**。

几个必须记住的顺序原因：
- 剧情 ▼ 必须在传令兵之前（同一张神殿背景，`ROGUE_HERALD` 在塔罗页也 0.999）。
- 灵光三选一必须在白色 `跳過` 之前（那页没有跳過，不选战斗不往下走）。
- 神闪对话框是半透明覆盖层，所以 `# 0.05 確認` 要排在 `# 1.4/1.5` **之前**（否则会在同页反复选卡）。
- 删卡/休息/人物灵光的 `stage` **绝不能按画面变化重置**（选中卡会发光/抬升，帧帧在变），只在判据失效时清。

---

## 8. 判据速查表（都在 `module/chaoszero/rogue.py` 常量区）

模板类（`assets/chaoszero/chaoszero/*.png`，`appear(offset=, similarity=)`）：

| 常量 | 页面 | area | 阈值 |
| --- | --- | --- | --- |
| `ROGUE_MENU` | 大厅右侧 `卡厄思` | (1108,302,1188,343) | 0.92 |
| `ROGUE_MODE_ENTRY` | 两卡页 `卡厄思顯現` | (300,550,500,600) | 0.92 |
| `ROGUE_WORLD_LIST` / `ROGUE_WORLD_*` | 世界列表/五个世界名 | 见 assets | 0.85-0.92 |
| `ROGUE_WORLD_ENTER` | 世界详情 `進入` | (1120,632,1252,672) | 0.92 |
| `TEAM_TITLE` | 队伍页（梦境开也是它） | (75,8,235,60) | 0.9 |
| `ROGUE_TURN` | 战斗页（蓝 ✓） | (1100,556,1185,628) | 0.85 |
| `ROGUE_STORY` | 剧情 ▼ | (1188,608,1214,638) | 0.85 |
| `ROGUE_MAP_BTN` | 3D 地图（小地图缩放按钮） | (486,458,526,496) | 0.9 |
| `ROGUE_PREVIEW` | 2D 路线预览 | (20,640,210,710) | 0.9 |
| `ROGUE_FATE` | 塔罗页 | (515,655,790,692) | 0.9 |
| `ROGUE_FLASH` | 灵光三选一标题 | (500,78,780,116) | 0.85 |
| `ROGUE_GOD` | 神闪页（辅助，主用 OCR） | (505,620,648,656) | 0.80 |
| `ROGUE_HERALD` | 传令兵场景 | (300,60,800,140) | 0.9 |
| `ROGUE_MEMBER` | 人物灵光选人 | (430,650,855,685) | 0.85 |
| `ROGUE_COPY` | 复制卡牌选人 | (430,648,860,686) | 0.85 |
| `ROGUE_REMOVE` | 删卡页标题 | (105,12,430,58) | **0.93** |
| `ROGUE_REST` | 安全区域（训练格） | (1040,118,1180,186) | 0.9 |
| `ROGUE_MEDITATE_OFF` | 冥想 `無法使用` | (1000,432,1165,466) | 0.9 |
| `ROGUE_MEDITATE` | 冥想选卡网格标题 | (130,18,470,52) | 0.9 |
| `ROGUE_CURE_APPROVE` | 治疗 `批准` | (618,335,673,367) | 0.85 |
| `ROGUE_CONSULT` / `ROGUE_CURE_NONE` | 諮商紀錄 / 无人可治 | (115,649,227,681) / (612,476,882,540) | 0.9 |
| `ROGUE_DICE` / `ROGUE_DICE_TAP` | 掷骰（两种标题：`擲骰` / `分析`） | (600,92,690,125) / (588,432,696,472) | 0.9 |
| `ROGUE_PROMPT` | 节点提示卡 | (478,528,802,700) | 0.9 |
| `ROGUE_EQUIP` | 装备页 | (600,78,690,112) | 0.9 |
| `ROGUE_MODAL` | 精神異常 弹窗 | (560,60,725,145) | 0.9 |
| `ROGUE_CLICK_CLOSE` | `點擊畫面可關閉視窗` | (505,655,775,686) | 0.9 |
| `ROGUE_ITEM` | **`獲得道具` 弹窗（新）** | (572,254,708,300) | 0.85 |
| `ROGUE_DETAIL` / `ROGUE_DECK` | 查看詳情 / 所有牌堆 | (575,36,706,74) / (145,16,346,60) | 0.85 |
| `ROGUE_PANEL` | 敌人详情（不可靠，半透明） | (452,100,560,136) | 0.95 |
| `ROGUE_RESUME` | 断线恢复弹窗 | (250,440,1030,545) | 0.92 |
| `ROGUE_CHECKPOINT` | 航点结算页 `結算` | (1040,20,1140,62) | 0.85 |
| `ROGUE_DREAM_ON/OFF/OK/NOTICE` | 梦境开关/确认/说明 | 见 assets | 0.9 |
| `ROGUE_INFO_MENU` / `ROGUE_RETREAT` / `ROGUE_RETREAT_TITLE` | 局内 ☰ / 撤退 / 面板标题 | 见 assets | 0.9 |

颜色量类：橙色主按钮 `PRIMARY_AREA(1013,633,1260,696)`；白色药丸 `SECONDARY_AREA(620,600,1270,700)` + 填充≥0.6/亮度≥180；紫色按钮 `PURPLE_AREA(950,600,1270,700)`；对话框 `DIALOG_AREA(640,420,1060,510)`；事件卡边框 `OPTION_BAND(150,650,1150,700)`；删卡「移除」`REMOVE_OK_AREA`；治疗 `消除記憶` 紫色 `b>140..`；存档垃圾桶亮像素。

固定点：`LOBBY_ROGUE(1215,322)`、`MODE_CARD(330,420)`、`WORLD_CARD(715,470)`、`TEAM_ENTER_POINT(1200,657)`、`DREAM_POINT(1010,35)`、`HERALD_POINTS/HERALD_CHECK`、`MEMBER_POINTS/MEMBER_OK_POINT`、`SAVE_TRASH(427/837/1237,582)`、`REST_POINTS(400,540)/(1085,435)`、`MEDITATE_*`、`INFO_MENU_POINT(1228,40)`、`RESUME_CONTINUE_POINT(815,508)`、`DETAIL_CLOSE_POINT(530,670)`、`DECK_CLOSE_POINT(1203,40)`、`CUTSCENE_POINT(640,300)`、`ZOOM_POINT(100,669)`、`ROUTE_OPEN_POINT(509,470)`、`ROUTE_CLOSE_POINT(95,672)`、`NODE_FALLBACK(1020,380)`。

---

## 9. 配置项（`module/config/argument/argument.yaml` → `ChaoszeroRogue:`）

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `RogueWorld` | `霧之城市` | 进哪个图（5 个） |
| `RogueDreamMode` | `開啟` | 开启/关闭/保持不变（紫页 110pt 上限，刷存档要开） |
| `RoguePick` | 1 | 三选一兜底位置 |
| `RogueHerald` | 1 | 开局传令兵选第几张（默认最左=3 场怪物 HP=1） |
| `RogueRoute` | `均衡` | 路线口径：均衡/优先进攻/优先事件 |
| `RogueAvoidElite` | true | 避开精英 |
| `RogueMeditate` | true | 允许在休息点优先冥想 |
| `RogueCure` | true | 崩溃页自动去治疗 |
| `RogueMember` | 1 | 人物灵光选第几位（暗的会自动跳过） |
| `RogueDelete` | 3 | 每局最多删几张卡（0=不删；位置盲删最前一张） |
| `RogueSparkFilter` | 空 | 灵光形态关键词表，一行 `卡名 = 关键词1,关键词2`（繁体；空=按数值挑最高） |
| `RogueEventPick` | true | 事件选项查表挑（关闭=永远按 `RoguePick`） |
| `RogueSaveKeep` | 1 | 存档页留哪个位次（0=三个全删，测试用） |
| `RogueLoop` | true | 打完是否接着下一局 |
| `RogueRuns` | 1 | 跑几局（0=不限） |

注册状态（**已完成，别重复做**）：`argument.yaml` / `args.json` / `menu.json` / `task.yaml`(Scheduler + ChaoszeroRogue) / `config_generated.py` / `config_manual.py`（`SCHEDULER_PRIORITY` 里 ChaoszeroRogue 在最后）/ 四份 i18n / `algs.py` 的 `chaoszero_rogue()`。

---

## 10. 短测试怎么做（重要，别再打整局）

1. 把设备停在 **队伍页**（`配置隊伍`）或大厅。
2. 用 `.workbuddy/probe_rogue_drive.py` 或 `probe_stop_beacon.py` 进本。
3. 到**第一个航点（信标）**就够了：`ROGUE_CHECKPOINT` 命中即视为「这局有存档」。
   到点后**主动撤退**（☰ → 撤退 → 确认），不要继续打。
4. 撤退链：`探索結果`(紫色下一步) → 整局结算(紫色確認) → `存檔資料收集完成` → 删档 → 下一步 → 队伍页。
5. 测某一页就用 `probe_test_page.py` 的思路：spy 目标判据，命中即 `raise Found` 跳出，然后 `ui.rogue_quit(timeout=90)`。

一个完整「进本→第一信标→撤退→删档→回队伍页」的手工走法（adb 全部单条命令）：

```bat
tap 1229 30          :: ☰ 卡厄思資訊
tap 1135 668         :: 撤退
tap 845 455          :: 確認
tap 1122 662         :: 探索結果 下一步
tap 1122 660         :: 整局結算 確認（等 3~5 秒）
tap 427 582          :: 存档1 垃圾桶（分解）
tap 640 300          :: 若有 獲得道具 弹窗，点一下关掉
tap 837 582          :: 存档2
tap 1237 582         :: 存档3
tap 1120 660         :: 下一步 → 队伍页
```
注意：adb 的**第一次 tap 常被吞**，关键按钮点两次；紫色 `確認` 有时要等 3-5 秒才出现。

---

## 11. 坑清单（血泪，别再踩）

1. **模板 PNG 必须是整帧 1280x720**，否则 `load_image` 裁出来是全黑，`matchTemplate` 会对所有页面返回 1.0。
2. `Button.match` 的 `offset` 是「在 area 外扩多少像素去找」，不是二值 `area=`；`appear()` 没有 `area=` 参数。
3. 客户端断线 = **整屏冻结**：只有角色待机会动，所有点击无效。别把它当成「缺判据」去加分支；认 `ROGUE_RESUME`，或重启客户端。
4. framework 看门狗：15 次点击窗口里同名 12 次 / 两名各 6 次 → `GameTooManyClickError` 并重启客户端。所以每个循环都要有 try 上限 + `click_record_clear()`（滑动扫描尤其要清）。
5. `Timer(n, count=1)` 新建后**第一次 `reached()` 就是 True**；「等 X 秒没出现就放弃」必须先 `.reset()`（休息确认框就是在 0.2 秒内被误判放弃的）。
6. 点击「选中卡片」会改变画面 → **不要用画面签名变化重置 stage**，只在判据失效时清。
7. 存档页：点垃圾桶 = **分解**，不是真删（返 單元幣）；删完会弹 `獲得道具` 挡住整页 → 一次只删一张。
8. `探索結果` / 整局结算 / 存档页用的都是同一颗紫色按钮，只能靠**标题 OCR** 区分。
9. `py_compile` / lint 通过 ≠ 实机正确；本功能 90% 的 bug 是「判据在实机页面上不命中」。
10. 中文日志别在控制台看（GBK 乱码），用 `probe_logtail.py` 落地成 UTF-8。
11. `appear()` 会 `stuck_record_add`；长时间只点一个坐标会被判定卡住 → `GameStuckError`。
12. 休息页的确认框会压暗整页 → 训练格判据失效，所以「确认框」必须在判据**外面**处理（已修）。
13. 节点提示卡是**两步**：先点卡身，再点 ∨（同一位置连点两次也行）。
14. 装备页两种布局，槽位在 x≈960/1065/1152、y≈222/380/538；点空白处 `確認` 不会亮。
15. `.workbuddy/` 全部 gitignore，探针随便写；`dev_tools/samples/`、`dev_tools/probe_*.py` 也已忽略。
16. `獲得道具` 弹窗的关闭提示在 x 600~875（`ROGUE_ITEM` area 572,254,708,300），**不是** `ROGUE_CLICK_CLOSE`
    的 505~775；两个都要留，别互相替代。
17. 一局结束可能出现 `戰鬥資料儲存中` 动画（约 5 秒）才到存档页，判据 `rogue_save_appear()` 用标题 OCR，
    动画面 OCR 会读空 → 日志出现 `Can not read the save page title`，属于正常重试，下一帧就会读到。

---

## 12. 下一步建议顺序

0. **先复测存档链**（§6.8）：进本 → 第一个信标 → 撤退 → 存档页 → 三张全删（`RogueSaveKeep=0`）→ 下一步 → 队伍页。
   这一段现在只手工走通过，脚本链路（`# 0.045` 关弹窗 + 一次删一张）没跑过，而它是「刷存档」的前提。
1. **修复制选卡**（§6.1）：要一张选卡页截图 → 新判据 + 选卡 + 确认，宁可认不出选第一张也别按 `跳過`。
2. **补 `RogueStopBeacon`**（§6.6）：让「打到第 N 个信标就撤」可配，短测试和控时长都靠它。
3. **修 run() 落点**（§6.5）：接受 `卡厄思` 两卡页 / 世界列表，多局循环才不会莫名停。
4. **商店页**（§6.2）：拿到截图后照删卡页写，只点删卡，绝不买。
5. **`RogueSaveKeep` 改成角色名**（§6.4），并用一次实机确认「留 1 删 2」。
6. 回归：`ROGUE_TASK=1 ROGUE_RUNS=2` 跑两局整链，再 `dev_tools.patrol_games`。

---

## 13. Git / 工作区状态 + 本轮花费

全部未提交（含 starsavior 的旧改动，**别一起提交**）。本功能相关：
```
M  algs.py  config/template.json  module/chaoszero/assets.py
M  module/config/argument/{argument.yaml,args.json,menu.json,task.yaml}
M  module/config/config_generated.py  module/config/config_manual.py
M  module/config/i18n/{zh-CN,zh-TW,en-US,ja-JP}.json
M  requirements-in.txt                 :: 加了 onnxruntime==1.14.1（繁体 OCR 用）
?? module/chaoszero/{rogue.py,rogue_cards.py,rogue_ocr.py,rogue_route.py,rogue_events.py}
?? module/chaoszero/{rogue_cards.json.gz,rogue_events.json.gz}
?? dev_tools/gen_chaoszero_rogue_{db,cards}.py
?? bin/ocr_models/
?? assets/chaoszero/chaoszero/ROGUE_*.png   (~60 个)
?? assets/chaoszero/chaoszero/中文名*.png   (用户导出的截图，模板做好后可清理)
```

- 提交时只 `git add` 上面这些；`module/starsavior/*` 与 `assets/starsavior/*` 是别人的在改，别动。
- `assets/chaoszero/chaoszero/ROGUE_HERALD_1/2/3.png`、`ROGUE_MAP_MINI.png` 已不再被引用，可删。
- 本轮实际花费/损失：
  - 采购：**0**（没买东西、没抽卡）；
  - 提煉/卖装备：**0**；
  - 治疗 3 个崩溃角色：花 70,000 金币（用户同意，治完继续刷）；
  - 删存档：手动删了 3 张（`RogueSaveKeep=0` 测试，分解返 單元幣 247/441/465/488）；
  - 有一次误触 `補充戰利品認證卡牌`（60 埃忒耳）弹窗，已按「取消」，**没有购买**。

---

## 14. 想快速确认「还能不能跑」

```bat
toolkit\python.exe -m dev_tools.alas_lint --severity high        :: 应 0 problems
toolkit\python.exe -m py_compile module\chaoszero\rogue.py module\chaoszero\rogue_cards.py ^
    module\chaoszero\rogue_route.py module\chaoszero\rogue_events.py module\chaoszero\rogue_ocr.py
:: 离线判据自检（不需要设备）
toolkit\python.exe -u .workbuddy\probe_crash_judge.py            :: 崩溃页/諮商页/消除記憶
toolkit\python.exe -u .workbuddy\probe_event_index.py            :: 事件查表
toolkit\python.exe -u .workbuddy\probe_flash_column.py           :: 灵光挑列
:: 实机短测
toolkit\python.exe -u .workbuddy\probe_stop_beacon.py            :: 打到第一信标→撤退→删档
```

有任何判据不命中，先查 `.workbuddy/skills/chaoszero-roguelike/SKILL.md` 对应章节，那里记了每条阈值的实测数字和失败现场。
