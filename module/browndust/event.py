"""
活动 (Brown Dust II) —— 一期的五件事，一个任务跑完。

这个文件放着总入口 `BrowndustEvent` 和它的第一步（剧情）。其余四步在各自的文件里，
都是不继承 `BrowndustUI` 的 mixin，靠 `BrowndustEvent` 把它们拼起来：

    event_battle.py   EventBattle      普通战斗 / 挑战战斗（共用每天 5 次 AP）
    world_boss.py     EventWorldBoss   魔兽追踪者（从最低难度往上推）
    event_mission.py  EventMission     活动「任务」木牌里的助力任务奖励
    shop.py           EventShop        活动商店按优先级兑换

为什么是一个任务而不是五个（用户原话：「属于魔兽的不要分开，合并在一个任务里」）：
活动页底部那排木牌本来就是同一页上的六块牌子，以前每块牌子是一个独立任务，各自
"回大厅 → 点横幅 → 进活动页 → 点木牌 → 做完 → 回大厅"，冷启动一次、活动页进五次。
合并之后一次启动、一次进活动页，五步连着做完才回大厅。

下面是「剧情」这一步量出来的东西，其余四步的实测记录在各自模块的 docstring 里。

活动剧情 —— 每期活动的「剧情」页逐个跳过。

Measured on the real device, 2026-10-29, season 「BROKEN BONDS」:

    page_main  --右侧那面活动横幅-->  page_event
    page_event --左上「行程」-->  活动行程面板（本周有哪些内容、还剩几天）
    page_event --底部「剧情」-->  page_event_story（亲密度剧集列表）
    page_event_story --某集的「查看」-->  剧情播放（全屏立绘 + 台词）
    page_event_story --右上角跳过 -->  「跳过对话」确认框 --确认-->  REWARD --点画面--> 回到列表

关于这一页有六件事是量出来的，不是猜的：

1. **入口每期都换皮**：横幅上的名字和美术都是当期活动的，只有位置固定（大厅右侧
   竖排第二格）。所以检查点取的是横幅下面那行小字（这一期是「魔兽追踪者解锁」），
   它同时也在横幅的可点区域内 —— 直接点它就进活动页，不用再建一个 .BUTTON。
   换期就重新导出 `EVENT_ENTRY`，见 skill 8.6。

2. **活动页那张「行程」是这一期的时间表**：一张 CONTENT × WEEK 的甘特图，每行
   一个内容（剧情 / 普通战斗 / 挑战战斗 / 魔兽追踪者），条子上写着开始日期；
   标题右边那枚徽标「活动 还剩N天」才是"还剩多久"。徽标是白字压深色胶囊，
   OCR 阈值 170 一次读通（150 会多读一个 `@`，见 `EVENT_DAYS_AREA`）。
   注意底部小字：所有内容按 **KST 9:00 开始、8:59 结束**，正好是本游戏
   08:00 的日刷新。

3. **剧集列表一次只放出一集的「查看」**：其余行是灰的，锁着的那几行写
   「完成先前剧情后解锁」，右侧只有一颗没有文字的灰 ▶。所以"还有没有得看"
   就是"还找不找得到 `STORY_VIEW`"，不需要读任何文字，也不需要知道这一期几集。
   跳完一集，下一集立刻解锁（实测 01→02→03 连着解锁，不是每天一集）。
   全部看完之后，"查看"那枚白胶囊会被换成一颗只有双箭头的「回顾」图标
   （深色底、没有胶囊背景，实测 `STORY_VIEW` 只到 0.226），六行一个样 ——
   全跑完再进来就是这个样子，任务照常认"没有可看的"、什么都不点。

4. **剧情不能靠点屏幕推进**：实测点 `(640,400)`（对话框下面一点）连点三次，
   台词一句没动；点 `(640,372)`（对话框里面）一下就换了下一句。所以"自动看剧情"
   这条路是通的，但要精确点在框里 —— 而框的位置随版式变（旁白是一枚居中的
   小条，对白是底部一整条带人名），这就是为什么这里直接跳过而不是读下去。

5. **右上角那排按钮**：喇叭、截图、记录、⏭（跳过）、ⓧ3（三倍速）。跳过是
   `(1044, 45)`，一个固定的 UI 位置，但它画在**每段剧情都不一样的背景**上：
   模板在三个场景之间只到 0.83，在别的页面上也有 0.59 的干扰，靠不住。
   所以它是纯坐标点，判据在别处 —— "列表页的检查点消失了"就等于"剧情已经把
   画面拿走了"（见 `EVENT_STORY_SKIP`）。

6. **跳过要确认，而确认框的高度不固定**：弹窗里有一段本集剧情简介，行数多少
   决定弹窗多高，`确认` 的 y 就会上下走（和兑换码那个 Android alert 同一个坑）。
   所以确认框认的是标题「跳过对话」，点的是 `STORY_CONFIRM` 这颗按钮自己的
   模板，两边都不写死坐标。确认之后弹 REWARD（「获得N种」+ 道具），文案是
   「点击画面即可返回。」，**点那条 V 形色带没用**（实测 `(640,360)` 点不掉），
   要点色带外面的空白（`EVENT_STORY_REWARD_TAP`）。

还有一条不是陷阱但很容易看错：REWARD 是半透明覆盖，`STORY_TITLE` 透过它照样
0.962 —— 所以"回到列表了"必须在奖励层关掉之后再问，不能先问列表。
"""
import re

from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import (EVENT_ENTRY, EVENT_SCHEDULE, EVENT_SCHEDULE_CLOSE,
                                     STORY_CONFIRM, STORY_REWARD, STORY_SKIP_CONFIRM,
                                     STORY_TITLE, STORY_VIEW)
from module.browndust.browndust_ui import BrowndustUI, page_event, page_event_story
from module.browndust.event_battle import EventBattle
from module.browndust.event_mission import EventMission
from module.browndust.shop import EventShop
from module.browndust.world_boss import EventWorldBoss
from module.exception import (EmulatorNotRunningError, GameBugError, GameNotRunningError,
                              GamePageUnknownError, GameStuckError, GameTooManyClickError,
                              RequestHumanTakeover, ScriptError)
from module.logger import logger
from module.ocr.ocr import Ocr

# 一步走不通时，哪些异常可以吞掉、哪些必须往上抛。
#
# 吞掉的这几种都表示"这一步的页面没走到/没认出来"：`ui_goto` 认不出当前页抛
# `GamePageUnknownError`，点太多下抛 `GameTooManyClickError`，模板对不上抛
# `ScriptError`。吞掉之后下一步照做 —— 魔兽打不动的时候，剧情和商店没有任何理由
# 跟着不做。
EVENT_STEP_SKIP = (ScriptError, GamePageUnknownError, GameBugError, GameTooManyClickError)
# 这几种说明"机器/游戏已经不在可工作的状态"，继续往下点只会把错误滚大：
# 卡死要重开、游戏没开要拉起、需要人工要停下来问。
EVENT_STEP_FATAL = (GameStuckError, GameNotRunningError, EmulatorNotRunningError,
                    RequestHumanTakeover)

# 剧情播放界面右上角的「跳过」。位置在所有剧情、所有场景上都一样，但背景每段
# 都不一样（酒馆内部 / 野外 / 战场），模板匹配在三个场景之间只到 0.83 —— 而
# 干扰分有 0.59，那个余量经不起换期换美术。所以这里只借它的位置，判据是
# "列表页的检查点不见了"（见 `event_story()`）。
EVENT_STORY_SKIP = Button(area=(1030, 34, 1058, 56), color=(0, 0, 0),  # alas-lint: allow - a click point on a fixed UI element drawn over art that changes every scene, there is no image to match
                          button=(1044, 45, 1044, 45), name='EVENT_STORY_SKIP')

# 点掉 REWARD 的地方：那条 V 形色带**自己点不动**，要落在色带下面的空白上。
# 实测 (640,360) 在色带正中，点两次都不动；(200,620) 一次就回去了。
EVENT_STORY_REWARD_TAP = Button(area=(180, 600, 220, 640), color=(0, 0, 0),  # alas-lint: allow - the reward screen says 点击画面即可返回, there is no button to match
                                button=(200, 620, 200, 620), name='EVENT_STORY_REWARD_TAP')

# 「活动 还剩N天」。白字压在深色胶囊上：阈值 170 读回「活动还剩6天」，
# 150 会多读一个 `@`（→「@活动还剩6天」），框再放宽一点会读成「Q勐还因」。
EVENT_DAYS_AREA = (508, 169, 652, 194)
EVENT_DAYS_THRESHOLD = 170
# 读徽标的时限。字通常第二帧就有，读不到就再读一帧；3 秒足够十来次尝试。
EVENT_DAYS_TIMEOUT = 3
# 行程面板的板面。用来等"面板真的关完了"（X 消失时它还在淡出，淡出期间
# 游戏会吞掉点击）。
EVENT_PANEL_AREA = (380, 140, 900, 600)

# 整个剧情阶段的上限。一期六集，每集 查看→跳过→确认→奖励→列表 约 8~10 秒，
# 加上跳转和淡入，90 秒内一定走完；给 300 秒是留给模拟器卡顿和网络。
EVENT_STORY_TIMEOUT = 300
# 点了「查看」之后，剧情把列表盖住的时限。
EVENT_STORY_VIEW_TIMEOUT = 15
# 跳过点了没反应时重试的间隔（第一次不用等，见 `event_story()` 里的 Timer）。
EVENT_STORY_SKIP_INTERVAL = 2
# 跳过之后等「跳过对话」弹窗。实测一秒内就出来，给 8 秒是防转场卡顿。
EVENT_STORY_DIALOG_TIMEOUT = 8
# 点掉「确认」之后等奖励层。实测 1~2 秒才淡入；没人给奖励的季就白等这几秒，
# 反正一天一次。
EVENT_STORY_REWARD_TIMEOUT = 6
# 点一下奖励层之后等它消失。**入场的动画期间游戏不认这一下**（实测第一下要
# 0.6 秒后才点就吞了），所以这里只等 4 秒就让循环再点一次，而不是等满 8 秒。
EVENT_STORY_REWARD_TAP_TIMEOUT = 4
# 剧集列表整块（右侧那列 Episode 底板）。用来等"新解锁那一行画完了没有"。
STORY_LIST_AREA = (600, 60, 1180, 620)
# 等列表稳下来的时限。一次淡入约 0.3~0.6 秒，给 3 秒足够。
EVENT_STORY_SETTLE = 3
# 「查看」在哪一行是不固定的：只有"下一集"那一行有它，前几集跳完就换成两枚
# 小图标，所以它随着进度一路往下走（实测每行约 90 像素，第 1 行 y≈100、
# 第 6 行 y≈565）。模板按第 3 行抠的，搜索窗口必须放开到 ±340 才够整列 ——
# 第一版给的是 ±200，第 6 集就是因此被漏掉的（2026-10-29 第三次实机）。
# 而 `Button.match()` 命中之后会把 `button` 的点击区一起挪到命中处，所以
# 放大窗口不会点错行 —— 这是框架本来就设计好的用法。
STORY_VIEW_OFFSET = (20, 340)
# 一次最多跳几集。正常是这一期全部（这一期 6 集）；上限只是防"列表永远有查看"
# 这种想不出来的循环，真撞上了说明判断写错了，不该无限点下去。
EVENT_STORY_MAX = 12

# 行程面板打开的时限。面板是纯本地的，10 秒还没出来就是真没开。
EVENT_SCHEDULE_TIMEOUT = 10


class EventStory:
    """
    Skip every 剧情 episode the current season has to offer.

    活动的第一步，**不消耗任何资源**（看完就解锁下一集），所以它排在最前面：
    后面几步里最难的那一步（魔兽一场三四分钟）失败时，剧情也已经拿到了。

    Pages:
        in: page_event
        out: page_event
    """

    def event_story_run(self):
        """
        活动页 → 剧情页 → 跳完所有集 → 回活动页。

        Pages:
            in: page_event
            out: page_event
        """
        self.ui_goto(page_event)
        days = self.event_days_left()
        if days is not None:
            logger.attr('Event', f'{days} day(s) left')

        watched = self.event_story()
        if watched:
            logger.info(f'[Event story] {watched} episode(s) skipped')
        else:
            # 和"跳过了 0 集"分开写：这一期早就看完了，日志应该是看得出来的一行。
            logger.info('[Event story] nothing to watch today')
        # `event_story()` 出来时停在剧集列表上，回活动页交给外层下一步的 `ui_goto`。

    def event_days_left(self):
        """
        Open 「行程」 and read the 「活动 还剩N天」 badge.

        The panel is the season's timetable: one row per content (剧情 / 普通战斗 /
        挑战战斗 / 魔兽追踪者), one column per week, and a bar wherever that
        content is running. Only the badge is read here — the bars would need the
        current date to mean anything, and the task does not schedule by them yet.

        Pages:
            in: page_event
            out: page_event

        Returns:
            int, None: Days left, or None if the panel or the text could not be
                read. Never a reason to stop the task by itself.
        """
        if not self.wait_until_appear(EVENT_SCHEDULE, offset=(20, 20), timeout=5):
            logger.warning('The 行程 button is not on the event page, skip the period check')
            return None

        logger.info('Open 行程')
        self.device.click(EVENT_SCHEDULE)  # alas-lint: allow - guarded by the appear() above, the close button below is the proof it opened
        if not self.wait_until_appear(EVENT_SCHEDULE_CLOSE, offset=(20, 20),
                                      timeout=EVENT_SCHEDULE_TIMEOUT):
            logger.warning('The 行程 panel did not open')
            return None

        # 面板是分两层画的：底板和 X 先出来，徽标里的字晚一帧才画上去。实测
        # 只等一次"画面不动"会读到空串（2026-10-29 两次实机都是这样），所以
        # 这里读不到就下一帧再读，读到为止 —— 有界，最多 `EVENT_DAYS_TIMEOUT` 秒。
        ocr = Ocr(EVENT_DAYS_AREA, lang='cnocr', letter=(255, 255, 255),
                  threshold=EVENT_DAYS_THRESHOLD, name='EVENT_DAYS')
        days = None
        for _ in self.loop(timeout=EVENT_DAYS_TIMEOUT):
            text = str(ocr.ocr(self.device.image))
            match = re.search(r'(\d+)\s*天', text)
            if match:
                days = int(match.group(1))
                logger.info(f'The event has {days} day(s) left')
                break
        else:
            logger.warning('Could not read the days left from the 行程 panel')

        self.device.click(EVENT_SCHEDULE_CLOSE)  # alas-lint: allow - it appeared above and is verified to disappear below
        # 「X 不见了」不等于「面板没了」：面板还在淡出，这期间游戏会吞掉点击。
        # 实测只等 X 消失就点底部页签，这一下被吞，`ui_goto` 白等 5 秒再点第二次
        # （2026-10-29 第二次实机）。等面板那块区域自己画完。
        self.wait_until_disappear(EVENT_SCHEDULE_CLOSE, offset=(20, 20),
                                  timeout=EVENT_SCHEDULE_TIMEOUT, settle=2)
        self.wait_until_still(EVENT_PANEL_AREA, timeout=EVENT_SCHEDULE_TIMEOUT)
        return days

    def event_story(self):
        """
        Watch-and-skip every unlocked episode.

        The loop is a state machine over the five screens this flow has, in the
        order they are drawn: the 「跳过对话」 dialog and the REWARD overlay both
        sit **on top of** the episode list, so they are asked about first.

        `watching` is what makes the skip click justifiable: it is set when 查看
        was pressed and cleared when 确认 was pressed, and while it is set the
        only thing on screen that can accept a tap is the story itself. The list
        disappearing is the measured half of that (the transition takes about a
        second), and it is what keeps the fixed-point skip click honest.

        Pages:
            in: page_event
            out: page_event_story

        Returns:
            int: How many episodes were skipped.
        """
        self.ui_goto(page_event_story)
        logger.hr('Event story', level=2)

        watched = 0
        watching = False
        skip = Timer(EVENT_STORY_SKIP_INTERVAL).start()
        for _ in self.loop(timeout=EVENT_STORY_TIMEOUT):
            # 弹窗优先：它们盖在列表上，列表的检查点照样匹配
            if self.appear(STORY_SKIP_CONFIRM, offset=(20, 20)):
                logger.info('Skip confirmation, press 确认')
                self.device.click(STORY_CONFIRM)  # alas-lint: allow - the dialog title is matched right above, the disappear below is the proof
                watching = False
                self.wait_until_disappear(STORY_SKIP_CONFIRM, offset=(20, 20),
                                          timeout=EVENT_STORY_DIALOG_TIMEOUT, settle=2)
                # 确认之后奖励层要一两秒才淡入。**这段必须等**：不等的话列表
                # （和新解锁那一行的「查看」）先露出半秒，循环会当成"还有一集"
                # 去点它，而这一点正好落在淡入中的奖励层上 —— 2026-10-29 第一次
                # 实机就是这么跳过一次、又在列表动画里误判"没有下一集"的。
                if not self.wait_until_appear(STORY_REWARD, offset=(20, 20),
                                              timeout=EVENT_STORY_REWARD_TIMEOUT):
                    logger.info('No reward screen, go on with the list')
                continue

            if self.appear(STORY_REWARD, offset=(20, 20)):
                logger.info('Reward screen, tap to go back')
                self.device.click(EVENT_STORY_REWARD_TAP)  # alas-lint: allow - the reward banner is matched right above, it says 点击画面即可返回
                self.wait_until_disappear(STORY_REWARD, offset=(20, 20),
                                          timeout=EVENT_STORY_REWARD_TAP_TIMEOUT, settle=2)
                continue

            if self.ui_page_appear(page_event_story):
                if self.appear(STORY_VIEW, offset=STORY_VIEW_OFFSET):
                    if watched >= EVENT_STORY_MAX:
                        logger.warning(f'Watched {watched} episodes, stop here')
                        break
                    logger.info(f'Episode {watched + 1}, press 查看')
                    self.device.click(STORY_VIEW)  # alas-lint: allow - it is matched right above and has to disappear below
                    watched += 1
                    watching = True
                    skip.reset()
                    # 列表被盖住才是"点进去了"。没盖住不算数：下一轮重新判，
                    # 查看 还在就再点一次，不在就往下走 —— 不在这里死等。
                    if not self.wait_until_disappear(STORY_TITLE, offset=(20, 20),
                                                     timeout=EVENT_STORY_VIEW_TIMEOUT):
                        logger.warning('The story did not start')
                    continue

                # 列表在，但没找到「查看」。**不能立刻下结论**：刚跳过一集之后，
                # 新解锁那一行是从灰色淡入、按钮比底板晚一帧才画出来的，实测
                # 第一帧的 `STORY_VIEW` 只有 0.6 出头。等列表自己画完再看一次。
                self.wait_until_still(STORY_LIST_AREA, timeout=EVENT_STORY_SETTLE)
                if self.appear(STORY_VIEW, offset=STORY_VIEW_OFFSET):
                    continue
                logger.info('No episode left to watch')
                break

            # 不在列表上、也没有弹窗：剧情在播。
            if watching and skip.reached():
                skip.reset()
                logger.info('Story is playing, press 跳过')
                self.device.click(EVENT_STORY_SKIP)  # alas-lint: allow - the list is gone and 查看 was pressed, there is no button to match on a background that changes every scene
                self.wait_until_appear(STORY_SKIP_CONFIRM, offset=(20, 20),
                                       timeout=EVENT_STORY_DIALOG_TIMEOUT)
        else:
            logger.warning('The event story did not finish in time')

        return watched


class BrowndustEvent(BrowndustUI, EventStory, EventBattle, EventWorldBoss,
                     EventMission, EventShop):
    """
    这一期活动的全部日常，一个任务跑完。

    顺序按「先挣后花」和「失败代价从小到大」排，不是随手写的：

        剧情        不花任何资源，跳完就解锁下一集，所以排第一 —— 后面最难的那步
                    挂了，这一趟至少把剧情拿到了
        活动战斗    花活动 AP，产出活动币
        魔兽追踪者  独立次数，一场三四分钟，整趟里最慢也最可能失败
        活动任务    领做完的助力任务奖励 —— 得等上面几步把任务做出来才有得领
        活动商店    花币，必须排在"给币的那几步"后面

    单步失败不中断整趟（`EVENT_STEP_SKIP`）：活动战斗认不出页面时，魔兽、领奖、
    商店照做。只有"卡死 / 游戏没了 / 要人工"才往上抛（`EVENT_STEP_FATAL`）。

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        self.ui_goto_main()
        # 大厅右侧那面横幅是这一期的活动入口。它的模板分一直在抖（实测 0.85~0.94
        # 来回跳，横幅底下压着一层跟着大厅动画变的光），所以给 15 秒而不是 5 秒。
        if not self.wait_until_appear(EVENT_ENTRY, offset=(20, 20), timeout=15):
            # 换期、活动结束、或者横幅被大厅弹窗压着。前两种不该让调度器停摆，
            # 第三种下一轮自己会好（`ui_additional()` 会关弹窗），所以只报 warning。
            logger.warning('The event banner is not on the lobby, nothing to do')
            self.device.save_screenshot(genre='event_no_banner')
            self.config.task_delay(server_update=True)
            return

        self.ui_goto(page_event)

        for name, step in self.event_steps():
            logger.hr(f'Event · {name}', level=2)
            # 一步可能要看几十秒的 OCR 和重载（活动战斗和魔兽都要重载整个游戏，
            # 14~17 秒一次），这期间一个点击都没有 —— 明说"我还在盯屏幕"，免得
            # 框架的卡死计时器把这当成卡住（硬约束 13）。
            self.device.stuck_record_clear()
            try:
                step()
            except EVENT_STEP_FATAL:
                raise
            except EVENT_STEP_SKIP as e:
                # 一步走不通不该把整趟带走：魔兽打不动的时候，剧情和商店没有
                # 任何理由跟着不做。下一步自己会 `ui_goto(page_event)` 重新归位。
                logger.warning(f'[Event] {name} did not work out, go on with the rest: {e!r}')

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def event_steps(self):
        """
        按执行顺序列出这五步。

        每一步都只接受"当前在活动页"作为入口，出口也回到活动页（做法是让下一步
        自己 `ui_goto(page_event)`，而不是每一步都硬回一次）—— 所以中间某一步
        抛异常停在半路，下一步照样能从任意页面走回来。

        Returns:
            list: [(名字, 方法)]，名字只用来分节打日志。
        """
        return [
            ('剧情', self.event_story_run),
            ('活动战斗', self.event_battle_run),
            ('魔兽追踪者', self.event_world_boss_run),
            ('活动任务', self.event_mission_run),
            ('活动商店', self.event_shop_run),
        ]
