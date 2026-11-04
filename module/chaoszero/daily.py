"""日常领取：當日行程的「全部領取」+ 信箱的「全部領取」。

两个入口都藏在主界面右上角那三条横线里（不是顶栏那排图标）：

    主界面右上角菜单键 (1231, 35)
      ├→ 菜单面板：活動 / 阿爾基亞農補給 / 日常任務 / 優尼格拉姆 / 夥伴 /
      │            保管箱 / 成就 / 圖鑑 / 商店
      │   → 「日常任務」(990, 168) 打开的是「作戰」总览，标签停在上次那页，
      │     还要点左侧第二个标签「當日行程」(65, 153)
      │   → 左下「全部領取」→「獲得道具」→ 点一下关掉
      └→ 菜单一开，屏幕**最右侧会多出一列竖排按钮**（信封/主页/铃铛/S/?/齿轮/电源），
         信封 (1231, 203) 就是信箱
          → 「全部領取」→「獲得道具」→ 点一下关掉

两枚「全部領取」都是**橙色 = 还有得领、灰白 = 今天领完了**，所以"没东西可领"是
正常结束，不是失败。最右侧那列竖排按钮只有菜单打开时才画出来，别拿它当大厅判据
（我在大厅截图上找过信封，那里根本没有）。

这个任务只负责领、不负责做：當日行程里那些任务由 模擬 / 方舟都市 去完成，
所以调度排在它们后面。
"""

import numpy as np

from module.base.timer import Timer
from module.chaoszero.assets import (DAILY_CLAIM, DAILY_MENU_ITEM, DAILY_TITLE,
                                     LOBBY_ARK, MAIL_CLAIM, MAIL_TITLE, REWARD_HINT)
from module.chaoszero.chaoszero_ui import CHAOSZERO_TAP_CENTRE, ChaoszeroUI
from module.chaoszero.page import page_main
from module.logger import logger

# 主界面右上角那三条横线。它右边那颗橙色 N 是未读角标，别点上去。
MENU_BTN = (1231, 35)
# 菜单打开以后，屏幕最右侧那一列竖排按钮里的信封（信箱）。
MAIL_BTN = (1231, 203)
# 「日常任務」打开的其实是「作戰」总览页，落到哪个标签看它上次停在哪，
# 所以进去以后还要点一下左侧那排里的第二个（日历 = 當日行程）。
DAILY_TAB = (65, 153)
# 两个面板的关闭键不在同一个高度：作戰那个在 (1208, 82)，信箱那个在 (1202, 67)。
DAILY_CLOSE = (1217, 82)
MAIL_CLOSE = (1202, 67)

# 两枚「全部領取」里橙色像素的占比：还有得领时 55~83%，领完了 0%。
DAILY_CLAIM_AREA = (138, 548, 431, 600)
MAIL_CLAIM_AREA = (51, 626, 309, 678)
CLAIM_ORANGE = 0.2


class ChaoszeroDaily(ChaoszeroUI):
    """日常领取 —— 當日行程 + 信箱。"""

    # ---------------------------------------------------------------- 页面判据

    def daily_appear(self):
        """Returns: bool: 「當日行程」面板开着。"""
        return bool(self.appear(DAILY_TITLE, offset=(20, 20)))

    def mail_appear(self):
        """Returns: bool: 「信箱」面板开着。"""
        return bool(self.appear(MAIL_TITLE, offset=(20, 20)))

    def menu_appear(self):
        """Returns: bool: 右上角的菜单面板开着。"""
        return bool(self.appear(DAILY_MENU_ITEM, offset=(20, 20)))

    def reward_appear(self):
        """Returns: bool: 「獲得道具」那个奖励窗开着。"""
        return bool(self.appear(REWARD_HINT, offset=(20, 20)))

    def ui_claimable(self, area):
        """
        Whether a 全部領取 button still has something to hand out.

        Args:
            area (tuple): x1, y1, x2, y2 of the button.

        Returns:
            bool: If the button is orange (= claimable).
        """
        image = self.image_crop(area).astype(int)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        orange = np.count_nonzero((r > 200) & (g > 110) & (g < 190) & (b < 90))
        return bool(orange > CLAIM_ORANGE * image.shape[0] * image.shape[1])

    # ---------------------------------------------------------------- 通用

    def claim_and_close(self, button, area, timeout=30):
        """
        Press one 全部領取 and settle whatever it opens.

        當日行程 does **not** raise a 「獲得道具」 window: the milestone icons just
        get their ticks and the button turns grey (measured 2026-11-04). The
        mailbox does pop the window. So the claim counts as done on either
        signal - the window showing up, or the button going grey - and a press
        that changes nothing is repeated instead of being taken for a claim
        (the first of two taps was eaten that day).

        Pages:
            in: 有那个按钮的面板
            out: 同一个面板

        Args:
            button (Button): The 全部領取 button of the page.
            area (tuple): x1, y1, x2, y2 of that button, for the orange check.
            timeout (int): Seconds.

        Returns:
            bool: If the claim went through.
        """
        timeout = Timer(timeout, count=3).start()
        press = Timer(2.5, count=2)
        tap = Timer(2, count=2)
        seen = False

        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                seen = True
                if tap.reached():
                    tap.reset()
                    self.tap_point(*CHAOSZERO_TAP_CENTRE)
                continue
            if seen:
                logger.info('Reward window closed')
                return True
            if not self.ui_claimable(area):
                logger.info('Claim took, the 全部領取 button is grey now')
                return True
            if press.reached():
                press.reset()
                self.device.click_record_clear()
                self.device.click(button)  # alas-lint: allow - the caller checked the page and the button, and the orange check above re-runs every frame
        else:
            if not seen:
                logger.warning('The claim did not take, the button is still orange')
                return False
            logger.info('The reward window stayed open, but the claim went through')
            return True

    def panel_quit(self, close_point, still_open, timeout=30):
        """
        Close a full-screen panel with its X and make sure the lobby is back.

        Pages:
            in: 任意面板
            out: page_main

        Args:
            close_point (tuple): Where that panel's X is.
            still_open (callable): Returns True while the panel is still up.
            timeout (int): Seconds.

        Returns:
            bool: If the lobby is back.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(2, count=2)

        for _ in self.loop(timeout=timeout):
            if self.ui_page_appear(page_main):
                return True
            if retry.reached():
                retry.reset()
                if still_open():
                    self.device.click_record_clear()
                    self.tap_point(*close_point)
        else:
            logger.warning('The panel did not close')

        return self.ui_quit_to_main()

    # ---------------------------------------------------------------- 當日行程

    def daily_open(self, timeout=60):
        """
        Walk from the lobby to the 當日行程 panel.

        主界面可能正处于闲置态（UI 全收起来），那一下点击只会唤醒界面，
        所以"菜单没开"就继续点菜单键，不要判失败。

        Pages:
            in: page_main
            out: 當日行程

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the panel is open.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(3, count=2)
        # 「日常任務」打开的是「作戰」总览，标签会停在上次看的那一页，
        # 所以点完菜单还要再点一次左侧的「當日行程」。
        opened = False

        for _ in self.loop(timeout=timeout):
            if self.daily_appear():
                logger.info('當日行程 is open')
                return True
            if not retry.reached():
                continue
            retry.reset()
            self.device.click_record_clear()

            if self.appear(DAILY_MENU_ITEM, offset=(20, 20)):
                logger.info('Menu, open 日常任務')
                self.device.click(DAILY_MENU_ITEM)
                opened = True
            elif self.appear(LOBBY_ARK, offset=(20, 20)):
                opened = False
                logger.info('Lobby, open the top-right menu')
                self.tap_point(*MENU_BTN)
            elif opened:
                logger.info('作戰 hub, switch to 當日行程')
                self.tap_point(*DAILY_TAB)
            else:
                logger.info('Lobby is idle, tap to wake it up')
                self.tap_point(*MENU_BTN)
        else:
            logger.warning('Can not open 日常任務')
            return False

    def daily_claim(self, timeout=30):
        """
        Press 全部領取 on 當日行程 and close the reward window.

        Pages:
            in: 當日行程
            out: 當日行程

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If nothing is left to claim, or the claim went through.
        """
        # daily_open() 的模板判据在面板还在淡入时就放行，半透明帧会把橙色读暗，
        # 错判成「没东西可领」静默跳过。先用均值比色等一帧完全画好的。
        self.wait_until_settled(DAILY_TITLE, timeout=5)

        if not self.ui_claimable(DAILY_CLAIM_AREA):
            logger.info('Nothing to claim on 當日行程')
            return True

        if self.appear(DAILY_CLAIM, offset=(20, 20)):
            logger.info('Claim the daily track')
            return self.claim_and_close(DAILY_CLAIM, DAILY_CLAIM_AREA,
                                        timeout=timeout)

        logger.warning('The 全部領取 button is not on screen')
        return False

    # ---------------------------------------------------------------- 信箱

    def mail_open(self, timeout=60):
        """
        Walk from the lobby to the 信箱 panel.

        The envelope sits in the vertical column that only exists on the right
        edge **while the menu is open**, so the menu has to be opened first.

        Pages:
            in: page_main
            out: 信箱

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the mailbox is open.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(3, count=2)

        for _ in self.loop(timeout=timeout):
            if self.mail_appear():
                logger.info('信箱 is open')
                return True
            if not retry.reached():
                continue
            retry.reset()
            self.device.click_record_clear()

            if self.appear(DAILY_MENU_ITEM, offset=(20, 20)):
                logger.info('Menu, open 信箱')
                self.tap_point(*MAIL_BTN)
            else:
                logger.info('Lobby, open the top-right menu')
                self.tap_point(*MENU_BTN)
        else:
            logger.warning('Can not open 信箱')
            return False

    def mail_claim(self, timeout=30):
        """
        Press 全部領取 on 信箱 and close the reward window.

        Pages:
            in: 信箱
            out: 信箱

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If nothing is left to claim, or the claim went through.
        """
        # 同 daily_claim()：信箱面板滑进来的时候，别拿半透明帧读颜色。
        self.wait_until_settled(MAIL_TITLE, timeout=5)

        if not self.ui_claimable(MAIL_CLAIM_AREA):
            logger.info('No unclaimed mail')
            return True

        if self.appear(MAIL_CLAIM, offset=(20, 20)):
            logger.info('Claim all mail')
            return self.claim_and_close(MAIL_CLAIM, MAIL_CLAIM_AREA,
                                        timeout=timeout)

        logger.warning('The mail 全部領取 button is not on screen')
        return False

    # ---------------------------------------------------------------- 入口

    def run(self):
        """
        Task: 日常领取 —— 當日行程 + 信箱，两处都点「全部領取」。

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Daily claim', level=1)

        if not self.ui_page_appear(page_main):  # alas-lint: allow - "not at the lobby" is the question; ui_quit_to_main() is bounded
            logger.info('Not at the lobby, walk back first')
            self.ui_quit_to_main()

        # 1. 當日行程
        if self.daily_open():
            self.daily_claim()
            self.panel_quit(DAILY_CLOSE, self.daily_appear)
        else:
            logger.warning('Skip 當日行程, it did not open')

        # 2. 信箱。第一步走砸了也照做：两处的奖励是分开的。
        if self.mail_open():
            self.mail_claim()
            self.panel_quit(MAIL_CLOSE, self.mail_appear)
        else:
            logger.warning('Skip 信箱, it did not open')

        self.config.task_delay(server_update=True)
