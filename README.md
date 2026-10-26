# AlGS

**A**las-based **G**ame **S**cheduler —— 一个模拟器装多个游戏，勾选任务按顺序跑完的集成脚本。

底座是 [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) 的框架层（碧蓝航线业务代码已全部剥离）。保留的是这套框架真正值钱的部分：整屏截图 + 非识别区涂黑的识别方式、状态循环、界面 A* 寻路、OCR、配置/GUI 生成链、任务优先级调度、异常与错误现场归档。

## 支持的游戏

### 苍雾世界（Hazeworld）

包名 `com.feimo.hazeworld.bilibili`，命名空间 `hazeworld`。

| 任务 | 做什么 |
|---|---|
| `HazeworldMail` | 邮件「领取全部」 |
| `HazeworldRoom` | 指挥室：全部收集 + 远征（领取 / 再次派遣） |
| `HazeworldFriend` | 好友「一键点赞」 |
| `HazeworldTask` | 每日 / 每周 / 每月任务「一键领取」 |
| `HazeworldPass` | 通行证「一键领取」 |

任务顺序由 `module/config/config_manual.py` 的 `SCHEDULER_PRIORITY` 决定（重启 > 收菜 > 日活 > 出击）。每个任务成功返回后自己调 `task_delay()` 排下一次运行，默认排到 `Scheduler.ServerUpdate`（05:00）。

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
2. `assets/<game>/<module>/*.png`：1280×720 截图，PS 里选中识别区、反选填充黑色，存盘。
3. 跑 `toolkit\python.exe -m dev_tools.button_extract` 生成 `assets.py`。
4. 写 `module/<game>/<game>_ui.py`：`Page(check_button)` + `link()` 建界面图，UI 子类指定 `page_main`。
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
