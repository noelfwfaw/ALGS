"""通行證（阿爾基亞農補給）的领取 of 卡厄思梦境.

入口和 當日行程 / 信箱 走同一条路 —— 主界面右上角 ≡ 菜单，只是菜单项不同：

    主界面 ≡ (1231, 35)
      └→ 菜单面板 →「阿爾基亞農補給」(990, 116) → 通行證页（整屏，41 天一赛季）

通行證页有两套视图，左上那列图标切换（图标没有文字，只能按坐标点）：

    獎勵 (71,104)：等级轨 —— 基本資料 / 特殊資料 两行 × 等级列 01~05…10
    任務 (67,188)：每日任務 / 每週任務 / 賽季任務 是**同一个长列表的分段标题**
                  （点标题只是滚到那一段，不是页签），右侧每行一枚圆形按钮

两套视图底部**同一位置**都有「全部領取」(822,655)，状态判据统一：

    白底 + 橙色圆形 ↓ : 当前视图有得领
    灰底 + 深灰 ↓     : 没得领

「有没有得领」数那枚 ↓ 的饱和像素占比（实测 27.5% → 0.0%），「按钮在不在」
用文字区做模板（两种状态下都是 1.000，所以它只证明按钮在，不掺和状态）。
任务行右侧那枚圆按钮同理：彩色 49.5% = 有得领，灰色 0% = 领过了/没做完。

任务领取**直接生效、不弹窗**（左上 XP 立刻涨，按钮当场变灰）；奖励领取会弹
「獲得道具」，而且比按钮变灰晚半秒 —— `reward_appear()` 是 UI 基类里那个通用
弹窗判据（硬约束 185），不另建素材。

⚠ 2026-11-11 首次实现时的账户是 0 级、当日任务已经全领过，所以「奖励领取出弹窗」
这条分支**没有在真机跑到过**（面板里全是灰的）。奖励一律走底部「全部領取」，
没有按格子去点 —— 可领状态的格子长什么样还没见过，不猜。
"""

from module.base.timer import Timer
from module.chaoszero.assets import (LOBBY_ARK, PASS_CLAIM_ALL, PASS_MENU_ITEM,
                                     PASS_REWARD_VIEW, PASS_TASK_VIEW, PASS_TITLE)
from module.chaoszero.chaoszero_ui import CHAOSZERO_TAP_CENTRE, ChaoszeroUI
from module.chaoszero.page import page_main
from module.logger import logger

# 主界面右上角那三条横线。和 daily.py 是同一个键，那个任务也是从这里进的。
MENU_BTN = (1231, 35)
# 菜单面板里的「阿爾基亞農補給」，在「活動」和「日常任務」中间那一行。
PASS_MENU_POINT = (990, 116)
# 通行證页的返回箭头（左上角那个「<」）。
PASS_BACK = (45, 33)

# 左上那列视图图标：上面那个是等级奖励轨，下面那个是任务列表。
REWARD_VIEW_POINT = (71, 104)
TASK_VIEW_POINT = (67, 188)

# 底部「全部領取」：文字区当"按钮在不在"的模板，圆形 ↓ 的彩色占比当状态。
CLAIM_ALL_POINT = (822, 655)
CLAIM_ALL_ICON = (700, 636, 746, 690)
CLAIM_ALL_GOLD = 0.10

# 任务列表右侧那五枚圆按钮：整列 x 1190~1225，行距 90，第一行 y=208。
TASK_ROW_BUTTON_X = (1190, 1225)
TASK_ROW_Y = (208, 298, 388, 478, 568)
TASK_ROW_GOLD = 0.20


class ChaoszeroPass(ChaoszeroUI):
    """
    Claim the pass task rewards and the unlocked pass level rewards.

    Pages:
        in: page_main
        out: page_main
    """

    # ---------------------------------------------------------------- 页面判据

    def pass_appear(self):
        """Returns: bool: 通行證页开着（左上角「阿爾基亞農補給」标题）。"""
        return bool(self.appear(PASS_TITLE, offset=(20, 20)))

    def pass_claim_gold(self):
        """
        Whether the bottom 「全部領取」 has something to hand out right now.

        Returns:
            bool: If that button is coloured (= claimable in this view).
        """
        return self.ui_colored_ratio(CLAIM_ALL_ICON) > CLAIM_ALL_GOLD

    def pass_row_gold(self, y):
        """
        Whether one task row's round button is coloured.

        Args:
            y (int): Row centre.

        Returns:
            bool: If that row has something to claim.
        """
        x1, x2 = TASK_ROW_BUTTON_X
        return bool(self.ui_colored_ratio((x1, y - 17, x2, y + 17)) > TASK_ROW_GOLD)

    def pass_gold_rows(self):
        """
        Which of the five visible task rows have a coloured button.

        Returns:
            list[int]: Row centres, top to bottom.
        """
        return [y for y in TASK_ROW_Y if self.pass_row_gold(y)]

    # ---------------------------------------------------------------- 进出

    def pass_open(self, timeout=40):
        """
        Walk from the lobby to the 通行證 page.

        Pages:
            in: page_main
            out: 通行證

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the page is open.
        """
        timeout = Timer(timeout, count=3).start()
        # ❗两个键各用一个 1 秒节流，别共用一个长的：共用一个 6 秒的节流时，
        # 点完 ≡ 之后要等满 6 秒才轮到点「阿爾基亞農補給」（2026-11-11 20:33 日志：
        # 09.361 点 ≡ → 15.265 才点菜单项，白白等了 5.9 秒）。
        # 节流只防"同一个键连点"，状态判定每帧都做。
        menu = Timer(1, count=2)
        item = Timer(4, count=2)
        # 点完菜单项到页面画出来这一段（实测 1.5 秒），期间既看不见菜单项、
        # 也还看不见通行證标题，别把这当成"没打开"再去点 ≡ —— 会在加载中的
        # 页面上多按一下（2026-11-11 20:40 改快节流后当场踩到）。
        loading = Timer(8, count=1)

        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                continue
            if self.pass_appear():
                logger.info('通行證 is open')
                return True
            if self.appear(PASS_MENU_ITEM, offset=(20, 20)):
                # 菜单项只在菜单开着时存在，点下去菜单就开始收，天然不会连点。
                if item.reached():
                    item.reset()
                    loading.reset()
                    # ❗菜单还在淡入时点这一下会被**吞掉**：实测点完 4 秒仍停在菜单上，
                    # 重试那一下才生效，白等好几秒。等它静止再点，一次就中。
                    self.wait_until_still(PASS_MENU_ITEM.area, timeout=2)
                    self.device.click_record_clear()
                    logger.info('Menu, open 阿爾基亞農補給')
                    self.device.click(PASS_MENU_ITEM)
                continue
            if not loading.reached():
                continue
            if not menu.reached():
                continue
            menu.reset()
            self.device.click_record_clear()
            if self.appear(LOBBY_ARK, offset=(20, 20)):
                logger.info('Lobby, open the top-right menu')
            else:
                logger.info('Unknown screen, open the top-right menu')
            self.tap_point(*MENU_BTN)
        else:
            logger.warning('Can not open the 通行證 page')
            return False

    def pass_switch(self, point, button, name, timeout=8):
        """
        Switch between the 任務 and 獎勵 views with the icons on the left rail.

        The icons carry no text and their selected state is only a shade of grey,
        so the press is a coordinate and the check is the **content** it opens:
        任務 leaves the 「每日任務」 card on the left, 獎勵 leaves 「基本資料」.
        Templates of those two cards score 1.000 on their own view and <=0.30
        on the other, so a 0.85 match is decisive.

        Args:
            point (tuple): Where that icon is.
            button (Button): The card that only that view shows.
            name (str): 任務 / 獎勵, for the log.
            timeout (int): Seconds.

        Returns:
            bool: If that view is on screen.
        """
        timeout = Timer(timeout, count=2).start()
        retry = Timer(2, count=2)

        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                continue
            if self.appear(button, offset=(20, 20)):
                return True
            if retry.reached():
                retry.reset()
                self.device.click_record_clear()
                logger.info(f'Switch to the {name} view')
                self.tap_point(*point)
        else:
            logger.warning(f'Can not switch to the {name} view')
            return False

    def pass_quit(self, timeout=25):
        """
        Close the 通行證 page with its back arrow.

        Pages:
            in: 通行證
            out: page_main

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the lobby is back.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(2, count=2)

        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                self.device.click(CHAOSZERO_TAP_CENTRE)  # alas-lint: allow - only reached inside `if self.reward_appear()`, the 「獲得道具」 window is on screen
                continue
            if self.appear(LOBBY_ARK, offset=(20, 20)):
                return True
            if retry.reached():
                retry.reset()
                self.tap_point(*PASS_BACK)
        else:
            logger.warning('The 通行證 page did not close')
            return False

    # ---------------------------------------------------------------- 领取

    def pass_claim_all(self, expect_reward=False, timeout=20):
        """
        Press the bottom 「全部領取」 until it goes grey, and settle the popup.

        Task rewards apply on the spot (no window at all). Level rewards pop the
        generic 「獲得道具」, and that window shows up about half a second
        **after** the button goes grey - the same trap as 當日行程 / 信箱
        (2026-11-11), so `expect_reward` keeps waiting for it instead of leaving
        it to `pass_quit()`, whose back arrow would close the page underneath it.

        Pages:
            in: 通行證（任意视图）
            out: 同一个视图

        Args:
            expect_reward (bool): This view pops a 「獲得道具」 window.
            timeout (int): Seconds.

        Returns:
            bool: If a claim went through (False = nothing was claimable).
        """
        # 刚切完视图那两帧按钮可能还是半透明的，先等判定区静止再读颜色 ——
        # 读早了会把"还没画出来"当成"没得领"（当帧否定，硬约束 153）。
        self.wait_until_still(CLAIM_ALL_ICON, timeout=2)
        if not self.pass_claim_gold():
            return False

        logger.info('Claim all on the 通行證')
        timeout = Timer(timeout, count=3).start()
        press = Timer(2.5, count=2)
        tap = Timer(2, count=2)
        # 按钮变灰以后最多再等 5 秒的奖励窗；只有 `expect_reward` 用。
        grey = Timer(5, count=1)
        seen = False

        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                seen = True
                if tap.reached():
                    tap.reset()
                    self.device.click(CHAOSZERO_TAP_CENTRE)  # alas-lint: allow - only reached inside `if self.reward_appear()`
                continue
            if seen:
                logger.info('Reward window closed')
                return True

            if self.pass_claim_gold():
                grey.clear()
                if press.reached():
                    press.reset()
                    self.device.click_record_clear()
                    self.tap_point(*CLAIM_ALL_POINT)
                continue

            if not expect_reward:
                logger.info('Claim took, the 全部領取 button is grey now')
                return True
            if not grey.started():
                grey.start()
            if grey.reached():
                logger.info('Claim took, no reward window showed up')
                return True
        else:
            if not seen:
                logger.warning('The 全部領取 button is still coloured, the claim did not take')
                return False
            logger.info('The reward window stayed open, but the claim went through')
            return True

    def pass_claim_rows(self, timeout=8):
        """
        Claim the task rows individually.

        「全部領取」 claims everything it can, so this only catches a row it left
        behind - and it is also where the row state is read, which is what the
        log line reports.

        Pages:
            in: 通行證 · 任務
            out: 通行證 · 任務

        Args:
            timeout (int): Seconds to wait for the buttons to turn grey.

        Returns:
            int: How many rows were claimed.
        """
        gold = self.pass_gold_rows()
        if not gold:
            logger.info('No pass task left to claim on the visible rows')
            return 0

        logger.info(f'Claim {len(gold)} pass task(s) one by one')
        for y in gold:
            self.tap_point((TASK_ROW_BUTTON_X[0] + TASK_ROW_BUTTON_X[1]) // 2, y)

        # 任务领取是立即生效的，点完当场变灰；等它变灰就是"确实领到了"的凭据。
        timeout = Timer(timeout, count=2).start()
        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                continue
            if not self.pass_gold_rows():
                logger.info('Pass task buttons are grey now')
                return len(gold)
        logger.warning('Some pass task buttons are still coloured')
        return len(gold)

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('卡厄思通行证', level=1)

        # 别用 `ui_ensure(page_main)`：停手二十秒后游戏把整个 UI 收成一张全屏立绘，
        # `ui_get_current_page()` 认不出来会直接 CRITICAL 退出（2026-11-11 20:38 实测）。
        # 和 daily.py 一样先走 `ui_quit_to_main()`，它认识那一屏。
        if self.pass_appear():
            logger.info('Already on the 通行證 page')
        elif not self.ui_page_appear(page_main):  # alas-lint: allow - "not at the lobby" is the question; ui_quit_to_main() is bounded
            logger.info('Not at the lobby, walk back first')
            self.ui_quit_to_main()

        if not self.pass_open():
            self.config.task_delay(minute=15)
            return

        tasks = rows = levels = 0
        if self.pass_switch(TASK_VIEW_POINT, PASS_TASK_VIEW, '任務'):
            tasks = int(self.pass_claim_all())
            rows = self.pass_claim_rows()
        if self.pass_switch(REWARD_VIEW_POINT, PASS_REWARD_VIEW, '獎勵'):
            levels = int(self.pass_claim_all(expect_reward=True))

        self.pass_quit()
        logger.info(f'Pass claimed: 全部領取 {tasks}, 任务行 {rows}, 等级奖励 {levels}')
        # 任务每天 05:00 刷新，每周任务周一刷新，赛季任务整季一次；每天跑一次就够。
        self.config.task_delay(server_update=True)
