# AlGS

**A**las-based **G**ame **S**cheduler —— 一个模拟器装多个游戏，勾选任务按顺序跑完的集成脚本。

底座是 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 的框架层（碧蓝航线业务代码已全部剥离）。保留的是这套框架真正值钱的部分：整屏截图 + 非识别区涂黑的识别方式、状态循环、界面 A* 寻路、OCR、配置/GUI 生成链、任务优先级调度、异常与错误现场归档。

## 支持的游戏

### 苍雾世界（Hazeworld）

包名 `com.feimo.hazeworld.bilibili`，命名空间 `hazeworld`。

| 任务 | 做什么 |
|---|---|
| `HazeworldMail` | 邮件「领取全部」 |
| `HazeworldRoom` | 指挥室：全部收集 + 远征（2 支队伍各自选任务与时长，到期领取并再次派遣） |
| `HazeworldExercise` | 演习：用当天演习券打完竞技场（默认代理作战，可切手动观战） |
| `HazeworldFriend` | 好友「一键点赞」 |
| `HazeworldTask` | 每日 / 每周 / 每月任务：任务奖励 + 积分条宝箱 |
| `HazeworldPass` | 通行证：领取任务拿经验升级，再领等级奖励 |
| `HazeworldSupport` | 支援角色：领取每个支援角色的友情币（绿币，每日上限 50000） |
| `HazeworldCore` | 核心制造：扫荡当天开放的关卡（周一到周日分别配类型与场数） |

任务顺序由 `module/config/config_manual.py` 的 `SCHEDULER_PRIORITY` 决定（重启 > 收菜 > 日活 > 出击）。每个任务成功返回后自己调 `task_delay()` 排下一次运行，日常任务的默认排期是 `Scheduler.ServerUpdate`（05:00）。

**领任务和通行证一天进四次**：这两个页面的内容不是只在 05:00 刷新——任务在玩家在线期间陆续完成，什么时候领完全由玩家决定，只按日刷新跑一次会让一整天攒下的任务堆到第二天早上。所以它们排的是固定的四个上线时间 **05:00 / 12:00 / 18:00 / 23:00**：`module/hazeworld/hazeworld_ui.py` 的 `CLAIM_TIMES` 与 `Scheduler.ServerUpdate` 同格式，`task_delay(server_update=CLAIM_TIMES)` 取其中最近的一个，跨天和服务器时区由框架自己处理。两个任务共用这四个时间点，`SCHEDULER_PRIORITY` 里 `HazeworldTask` 排在 `HazeworldPass` 前面，所以每个时段只启动一次游戏、连着跑完两个任务。

**演习不是日常任务**：演习券每小时恢复 1 张、上限 15 张，只按日刷新跑一次会让计数器在后半天一直满着（每天 24 张只花掉 15 张）。所以它排的是"最多等 12 小时，同时向 05:00 对齐"——`task_delay(server_update=True, minute=720)` 取两者中较近的那个，最终稳定在 **05:00 与 17:00** 各跑一次：24 张全部花完，且 05:00 那次和日任务共用一次启动。

**远征按小时排期**：派遣到期要再进一次游戏领取并重新派出，所以 `HazeworldRoom` 的延迟不是日刷新，而是 `task_delay(minute=小时数 × 60 + 5)`——选 4 小时就 4 小时后回来。两队各自配置，`Team1Task` / `Team1Hours` 与 `Team2Task` / `Team2Hours` 独立：任务有 5 个（训练 / 防卫 / 攻击 / 火力 / 支援），时长有 4 / 8 / 12 小时。队伍已派出时脚本只领取、不重置时长（面板上时长是锁住的）。

**领取远征会弹「远征探索」结果框**：「点击领取」不是原地结算，而是把整块面板盖住，弹出一个显示奖励的框，上面两个键是「取消」和「再次派遣」。脚本按「取消」关掉它，再照配置重新派遣——按「再次派遣」会沿用上一次的时长，配置改过之后排期就和游戏对不上了。这个框是淡入的，点完领取的下一帧两个键都还没画出来，所以领取循环在最后一次点击之后还会再看 4 秒（`RESULT_SETTLE`），看见就关掉；不关的话后面每一次点击都落在框上，最终会撞框架的连点保护（`GameTooManyClickError`）。

**任务积分条要单独领**：每日 / 每周 / 每月三个页签下方各有一条积分进度条，攒满后还能再点一次开宝箱，三页的积分条互相独立。`HazeworldTask` 会先领列表里的任务奖励，再点积分条上的宝箱，最后确认奖励弹窗。

**通行证先做任务再领奖**：通行证升级靠任务给的经验，只领等级奖励不会升级。所以 `HazeworldPass` 的顺序固定为「任务页 → 领取任务 → 奖励页 → 一键领取」，`ClaimTask` / `ClaimAll` 可分别关闭。

**刷核心不带关卡参数**：核心制造的关卡由游戏记住"你上次选的那一关"，脚本只负责选类型（左侧五个色条）和把体力一次花完（`SweepCount=0` 时点 `MAX`）。这样游戏出了新关卡也不用改脚本；不想刷满就把 `SweepCount` 填成具体场数。单场消耗不写死，读的是右下角 `作战准备` 上的数字。

**体力不够就不点扫荡**：游戏对"体力不够"的扫荡既不报错也不关弹窗，按下去什么都不发生，结算永远不来——脚本以前会在这儿等满 5 分钟再抛 `GameStuckError`。现在扫荡前先用 OCR 读右上角体力条和单场消耗，按 `体力 ÷ 消耗` 决定要不要刷、刷几场（`SweepCount` 超过体力能负担的场数时自动降到能打的场数），一个数字都读不到时不拦（宁可白跑一趟，也不要因为一次误读浪费一天）。万一真的被游戏拒绝，等待结算的循环 30 秒后看到扫荡按钮还在，就把这次当作"没刷"收尾，不再卡死。

**每天开放的类型不同**：周一到周日各配一组 `类型 + 场数`（`HazeworldCore.Monday` … `Sunday`），脚本按服务器时间取当天的那一组，没配的那天就跳过不跑。刷新点是 05:00，所以 05:00 之前仍算前一天。

新增任务时要连带补 `module/config/i18n/{zh-CN,zh-TW,en-US,ja-JP}.json` 的 `name` / `help`，否则 GUI 里显示的是 `Group.Key.name` 这种占位符。

## 目录

```
algs.py            AlGS 调度器：继承 GameScheduler，登记每个游戏任务
alas.py            框架层调度器：任务队列、异常处理、错误归档
module/base/       状态循环基类、Button/Template、Timer、装饰器、几何工具
module/device/     截图（DroidCast/nemu_ipc/maatouch/adb…）、点击滑动、应用启停、卡死检测
module/ocr/        Ocr / Digit / DigitCounter / Duration
module/ui/         通用界面图（Page + A* 寻路）、ui_click/goto/ensure、Switch/Scroll/Navbar
module/config/     yaml → args.json/menu.json/config_generated.py/i18n 生成链与调度器
module/hazeworld/  苍雾世界：页面图、素材、任务模块
assets/hazeworld/  识别素材（只保留识别区、其余涂黑）
module/webui/      WebUI（多实例进程管理、设置页、实时日志）
dev_tools/         button_extract、uiautomator2_screenshot 等制作工具
```

## 运行

```bat
start_algs.bat
```

或手动：

```bash
toolkit\Lib\site-packages\adbutils\binaries\adb.exe connect 127.0.0.1:16640
toolkit\python.exe gui.py --host 127.0.0.1 -p 22267
```

打开 http://127.0.0.1:22267 。

> **必须先 connect 再启动**：Windows 上模拟器自带的 adb server 会占用 5037 端口，若由框架自己起 server，`connect` 可能返回 `cannot resolve host` 导致 transport offline。启动脚本已经处理。

## 加一个游戏

1. `module/config/server.py`：游戏名加入 `VALID_SERVER`，包名登记进 `VALID_PACKAGE`。
2. `assets/<game>/<module>/*.png`：1280×720 截图，PS 里选中识别区、反选填充黑色，存盘。涂黑的会变成 `Button`（点它），整屏保留的会变成 `Template`（`TEMPLATE_` 前缀，只作比对）。
3. 跑 `toolkit\python.exe -m dev_tools.button_extract` 生成 `assets.py`。生成后必须人工核对坐标，缺图时会静默回落。
4. 写 `module/<game>/<game>_ui.py`：`Page(check_button)` + `link()` 建界面图，UI 子类指定 `page_main`。一个 `Page` 可以收多个检测点（传列表，任一命中即为本页）——侧边图标盖在动画场景上、或者带角标时会抖，两个检测点互为备份更稳。子页面要先声明，父页面的 `link()` 才能引用。
5. `argument.yaml` / `task.yaml` 加选项组与任务（任务必须含 `Scheduler` 组）。
6. 跑 `toolkit\python.exe -m module.config.config_updater` 重新生成配置与 GUI。
7. `algs.py` 里加同名方法（任务名的蛇形命名法）。
8. `SCHEDULER_PRIORITY` 插入任务名。

详细规范见仓库内的开发约定：铁律（禁止 sleep 串联、状态循环骨架、只用正面条件）、素材制作（1280×720 截图 + 非识别区涂黑 + `button_extract`）、界面图与检测点选法、多游戏命名空间切换设计。

## 注意

- 分辨率固定 1280×720，不支持真机。
- `assets.py`、`args.json`、`config_generated.py` 都是生成产物，不要手改。
- 切游戏必须走 `module.config.server.set_server()`（会同时清资源缓存）。

## License

GNU General Public License v3.0，见 `LICENSE`。框架版权归 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 作者所有，本仓库为 GPL-3.0 下的衍生作品。
