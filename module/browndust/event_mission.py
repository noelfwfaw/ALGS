"""
活动任务 (Brown Dust II) —— 活动页「任务」木牌里的助力任务，有就领，没有就不领。

Measured on the real device, 2026-10-29, season 「BROKEN BONDS」:

    page_main --右侧活动横幅--> page_event --底部第五块木牌「任务」--> page_event_mission
    page_event_mission --右下「全部领取」--> REWARD --点画面--> page_event_mission
    page_event_mission --左上角箭头--> page_event --左上角箭头--> page_main

关于这一页有五件事是量出来的：

1. **入口是活动页底部第五块木牌，点的是木牌下面那行白字**（`EVENT_TAB_MISSION`
   (840,643)-(894,666)，中心 (867,654)）。点木牌图标也行，但白字更稳 —— 剧情那块
   木牌实测就是"点字能进、点图标偶尔被吞"。点下去是**约 3 秒的黑屏加载**（连拍
   实测 t1~t3 全黑、t4 已经是 0.970），不是整包重载，进出都是这个量级 —— 所以
   30 秒超时只是留给模拟器卡顿的余量。

2. **检查点是右下角那颗「全部领取」**（`EVENT_MISSION_CLAIM`
   (867,523)-(1045,573)）。它有两种状态：有奖励可领时是亮蓝底白字，领空之后变
   深蓝底灰字 —— 实测模板分 1.000 / 0.960，两态都能匹配上，所以它能当"到没到
   这一页"的判据，不能当"还有没有奖励"的判据。位置也帮了忙：邮箱页那颗
   「全部领取」是同一个胶囊、同样四个字，但画在 (1007,642)，跟这块差着 140 像素，
   `appear(offset=(30,30))` 搜不到它（别的页面最高 0.404）。

3. **"有没有东西可领"数亮度**：可领时这颗按钮里 `luma>200` 有 796 个像素（区域
   均值 (114,121,187)），领空之后是 **0**（均值 (76,75,117)）。跟日常任务页的
   「全部获得」、邮箱的「全部领取」是同一个套路 —— 模板分在两态之间只差 0.04，
   根本分不开。

4. **结算页是横在中间的一条半透明带，按钮露在带子下面**：`HUNT_REWARD` 在结算
   页上 0.979，在列表上 0.11~0.13。所以"页面还在"不能当"领完了"的证据，必须
   等这条带子消失（`BrowndustUI.ui_reward_clean()`）。

5. **领完的那一条会从列表里消失**：实测「进行赛季活动战斗 5/5」领完就从列表里
   没了，下面的行往上顶，而一屏本来就放不下全部任务。所以行号、行数、位置都不能
   当判据，只问"这一页还有没有东西可领"。

6. **REWARD 淡入 / 道具飞入动画里会有一帧匹配不上 `HUNT_REWARD`**（稳定帧
   12:27:45 真机量得 0.980）。2026-11-10 12:26 事故：领奖后只隔 2.8 秒就打了
   `[Event mission claimed] 1`，日志里**既没有 `reward screen, tap to go back`
   也没有那一下 Click** —— `mission_dismiss_reward()` 把单帧假阴性当成"结算页
   关掉了"直接返回，一次都没点。接着返回箭头被遮罩吞掉，下一步 `ui_goto` 在
   遮罩下认不出任何页面（`ui_reward_clean` 故意不让页面判据透过结算页），
   空转 60 秒 → `GameStuckError`。所以"关掉了"必须是**连续几帧都没有 REWARD**，
   不是"这一帧没看到"；离开这一页之前还要再确认一次遮罩不在。

「全部领取」只领**已完成**的任务，没做完的照旧灰着，按下去不会误领 —— 所以
这个任务不需要知道活动有几条任务、也不需要读任何文字。

用户的原话：「我说的就是领取奖励，有就领，没有就不领。」
"""
from module.base.button import Button
from module.base.timer import Timer
from module.browndust.assets import (EVENT_MISSION_CLAIM, EVENT_TAB_MISSION,
                                     HUNT_REWARD)
from module.browndust.browndust_ui import page_event, page_event_mission
from module.browndust.page import MISSION_BACK
from module.logger import logger

# 活动页底部第五块木牌「任务」。`EVENT_TAB_MISSION` 只当"到了活动页、这块木牌画
# 出来了"的判据，点击点写死 —— `appear()` 带回来的匹配偏移会改写点击位置，魔兽
# 那块木牌就是被偏移推到了下边缘、点下去游戏一声不响（硬约束 136）。
MISSION_TAB = Button(area=(840, 643, 894, 666), color=(0, 0, 0),  # alas-lint: allow - the template is EVENT_TAB_MISSION, this is only the click point
                     button=(867, 654, 867, 654), name='EVENT_MISSION_TAB')
# 底部那排木牌的面积，用来等入场动画画完（木牌最后才画）。
MISSION_TAB_AREA = (760, 620, 980, 690)

# 「全部领取」可不可点：数这颗按钮里 luma>200 的像素。实测可领 796、领空 0。
MISSION_CLAIM_LUMA = 200
MISSION_CLAIM_PIXELS = 100

# 结算页的点击点：道具下面那行「点击画面即可返回。」再往下的空白带。跟日常任务页
# 的 `TASK_REWARD_TAP`、邮箱页是同一个位置 —— 这一带在三张页面上都落在面板外面。
MISSION_REWARD_TAP = Button(area=(600, 680, 640, 720), color=(0, 0, 0),  # alas-lint: allow - the reward screen says 点击画面即可返回, there is no button to match
                            button=(620, 700, 620, 700), name='EVENT_MISSION_REWARD_TAP')

# 点木牌到这一页画出来实测约 3 秒（连拍 t1~t3 全黑、t4 已经到位）。给 30 秒是
# 留给模拟器卡顿和首次加载的余量，正常不会用满。
MISSION_ENTER_TIMEOUT = 30
# 退出实测 0.6 秒就回到活动页，给 10 秒已经是十几倍余量。
MISSION_BACK_TIMEOUT = 10
# 点「全部领取」到结算页出现，实测一下就出来，给 10 秒防网络卡。
MISSION_REWARD_TIMEOUT = 10
# 点掉结算页之后再等回列表。
MISSION_RESULT_TIMEOUT = 30
# 结算页是"点一下才走"，节流一下，免得被框架判成连点。
MISSION_TAP_INTERVAL = 2
# 领完一次之后再问还有没有。正常一次就领空；多给两次是防"领完之后又解锁了新的"。
MISSION_CLAIM_TRIES = 3
# 判定"结算页已经关掉"要连续几帧都看不到 REWARD。动画帧会有一两帧掉到 0.85
# 之下，单帧否定会把还盖着的遮罩当成列表页（12:26 真机事故）。
MISSION_REWARD_SETTLE = 3


class EventMission:
    """
    Claim every finished mission on the event's 「任务」 page.

    Pages:
        in: page_event
        out: page_event
    """

    def event_mission_run(self):
        """
        Pages:
            in: page_event
            out: page_event
        """
        # 上一步（活动战斗 / 魔兽追踪者）结束时可能还压着一个结算页，活动任务页的
        # 检查点照样在它底下匹配（0.957），`ui_goto` 会以为"已经到这一页"然后
        # 拿着一个点不动的屏幕继续干活。结算页只盖在活动任务页上，先点掉再谈导航。
        if self.appear(HUNT_REWARD, offset=(20, 20)):
            logger.info('[Event mission] a leftover reward screen, tap it away')
            self.mission_dismiss_reward()

        if self.mission_enter():
            claimed = self.mission_claim_all()
            logger.attr('Event mission claimed', claimed)
            self.mission_back()

    def mission_enter(self):
        """
        活动页点底部第五块木牌「任务」进页面。

        Pages:
            in: page_event
            out: page_event_mission

        Returns:
            bool: 有没有进去。
        """
        self.ui_goto(page_event)
        # 活动页有入场动画，底部那排木牌最后才画出来；画之前点等于点在背景上。
        if not self.wait_until_appear(EVENT_TAB_MISSION, offset=(20, 20), timeout=10):
            logger.warning('[Event mission] the 任务 tab did not show up')
            return False
        # 木牌从第一帧就能匹配到 1.00（淡入不改变模板匹配的分），但那时它还在淡入，
        # 点下去游戏不认（剧情那块木牌实测如此）。等这块真的画稳再点。
        self.wait_until_still(MISSION_TAB_AREA, timeout=5)

        for _ in range(2):
            self.device.click(MISSION_TAB)  # alas-lint: allow - the tab was matched right above, the claim button below is the proof
            if self.wait_until_appear(EVENT_MISSION_CLAIM, offset=(20, 20),
                                      timeout=MISSION_ENTER_TIMEOUT):
                return True
            # 30 秒还没到，只有两种可能：这一下被吞了（还停在活动页），或者页面
            # 正在加载。用"木牌两秒内还能不能匹配到"把它们分开 —— 匹配不到就是
            # 在加载，这时候绝不能在这个画面上再点一下：那一下会落到下一页的某个
            # 位置上，而下一页是什么还没人知道。
            if not self.wait_until_appear(EVENT_TAB_MISSION, offset=(20, 20), timeout=2):
                if self.wait_until_appear(EVENT_MISSION_CLAIM, offset=(20, 20),
                                          timeout=MISSION_ENTER_TIMEOUT):
                    return True
                logger.warning('[Event mission] left the event page but the 任务 page did not show up')
                return False
            logger.info('[Event mission] still on the event page, tap the tab again')

        logger.warning('[Event mission] cannot open the 任务 page')
        return False

    def mission_claim_all(self):
        """
        按「全部领取」直到这一页不再提供任何奖励。

        「全部领取」只领**已完成**的任务，没做完的照旧灰着，所以不用读任务文字，
        也不用知道这一期有几条。

        Pages:
            in: page_event_mission
            out: page_event_mission

        Returns:
            int: 按了几次（= 领了几批）。
        """
        claimed = 0
        # 面板是滑入/淡入的，按钮最后才画出来；领完之后这一页也要重画（领掉的行
        # 消失、下面的行往上顶）。单帧读到暗就判空会漏领整页，所以统一交给
        # `ui_bright_settled()` 连续观察一段窗口。
        for i in range(MISSION_CLAIM_TRIES):
            if not self.ui_bright_settled(EVENT_MISSION_CLAIM, MISSION_CLAIM_LUMA,
                                          MISSION_CLAIM_PIXELS):
                break
            logger.info(f'[Event mission] claim all ({i + 1})')
            self.device.click(EVENT_MISSION_CLAIM)  # alas-lint: allow - the button being bright is checked right above, the reward screen below is the proof it took
            # 先记上再判结果：按钮已经按下去了，这一批奖励就已经进包，哪怕结算页
            # 没点掉，也不能当成"没领到"报出去。
            claimed += 1
            if not self.mission_close_reward():
                logger.warning('[Event mission] the claim did not come back to the list')
                break

        if not claimed:
            logger.info('[Event mission] nothing to claim today')
        return claimed

    def mission_close_reward(self):
        """
        走完 REWARD 结算页，回到活动任务列表。

        Pages:
            in: page_event_mission（结算页正在弹出来）
            out: page_event_mission

        Returns:
            bool: 回没回到列表。
        """
        if not self.wait_until_appear(HUNT_REWARD, offset=(20, 20),
                                      timeout=MISSION_REWARD_TIMEOUT, settle=2):
            if self.ui_page_appear(page_event_mission, offset=(20, 20)):
                # 按钮亮着但一条奖励都没给（比如只剩"进行中"的任务）时不会弹
                # 结算页，直接回到列表。
                logger.info('[Event mission] no reward screen, already back to the list')
                return True
            logger.warning('[Event mission] neither the reward screen nor the list came back')
            return False

        return self.mission_dismiss_reward()

    def mission_dismiss_reward(self):
        """
        点掉 REWARD 结算页，等回活动任务列表。

        结算页上写着「点击画面即可返回」，没有按钮可以 appear，所以点的是那条
        空白带；"点到了没有"由下面的列表自己回答（`ui_reward_clean` 要它不再
        透过结算页匹配）。

        ❗退出判据不能是"这一帧没看到 REWARD"：结算页淡入、道具飞入的动画帧
        上 `HUNT_REWARD` 会掉到 0.85 之下，而 `ui_page_appear()` 里的
        `ui_reward_clean()` 用的正是同一帧 —— 一假阴性就两边都成立，于是
        一次都没点就宣布"回到列表"（12:26 真机事故）。必须连续几帧都不在，
        才允许问列表页回来没有。

        Returns:
            bool: 结算页走掉了没有。
        """
        # 故意不 .start()：未启动的 Timer 第一次 reached() 就是 True。
        # `mission_close_reward()` 已经用 settle=2 等过动画，第一下可以立刻按；
        # 按不动再由 2 秒节流补按（硬约束 153）。
        tap = Timer(MISSION_TAP_INTERVAL)
        clean = 0
        for _ in self.loop(timeout=MISSION_RESULT_TIMEOUT):
            if self.appear(HUNT_REWARD, offset=(20, 20)):
                clean = 0
                if tap.reached():
                    tap.reset()
                    logger.info('[Event mission] reward screen, tap to go back')
                    self.device.click(MISSION_REWARD_TAP)  # alas-lint: allow - the reward screen has no button, it says 点击画面即可返回
                continue
            clean += 1
            if clean < MISSION_REWARD_SETTLE:
                continue
            # 结算页散掉了，列表还没画回来时这一行会返回 False，下一帧再问。
            if self.ui_page_appear(page_event_mission, offset=(20, 20)):
                return True
            clean = 0

        logger.warning('[Event mission] the reward screen did not go away')
        return False

    def mission_back(self):
        """
        退出活动任务页，回活动页。

        这一步单独写、不直接 `ui_goto_main()`，是因为活动页和活动任务页的返回键
        是同一个像素：交给 `ui_goto` 去猜"现在是哪一页"，猜错也就是多点一下，但
        日志会变得看不懂（实测第一次就是 `page_event -> page_main` 连点两次）。
        这里明说"先等回活动页"，最后一步再交给 `ui_goto_main()`。

        ❗离开之前先确认 REWARD 结算页不在。它是一层「点击画面即可返回」的
        遮罩，压着的时候返回箭头会被吞掉；而 `ui_page_appear()` 在遮罩下
        故意不认页面，下一步 `ui_goto` 就会认不出任何页、空转 60 秒（12:26
        真机事故）。点一下没反应不等于失败，按 10 秒窗口重试一轮（153）。

        Returns:
            bool: 回到活动页了没有。
        """
        for _ in range(2):
            if self.appear(HUNT_REWARD, offset=(20, 20)):
                logger.info('[Event mission] leftover reward screen, tap it away')
                if not self.mission_dismiss_reward():
                    # 遮罩点不掉就别再白点返回箭头，交给 `ui_additional()` 的
                    # 全局兜底，免得这里连着空等 80 秒。
                    break
            self.device.click(MISSION_BACK)  # alas-lint: allow - leaving the page, the event tab below confirms it
            if self.wait_until_appear(EVENT_TAB_MISSION, offset=(20, 20),
                                      timeout=MISSION_BACK_TIMEOUT):
                self.wait_until_still(MISSION_TAB_AREA, timeout=5)
                return True
            logger.info('[Event mission] still on the 任务 page, retry the back arrow')

        logger.warning('[Event mission] cannot leave the 任务 page')
        return False
