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

两枚「全部領取」都是**彩色 = 还有得领、灰白 = 今天领完了**，所以"没东西可领"是
正常结束，不是失败。判据只数**饱和度**、不认具体色相：客户端换皮时按钮的
颜色会变（今天是橙的，改版改成蓝的绿的一样成立），只数橙色会在换皮那天把
"有得领"读成"没得领"。最右侧那列竖排按钮只有菜单打开时才画出来，别拿它当
大厅判据（我在大厅截图上找过信封，那里根本没有）。

这个任务只负责领、不负责做：當日行程里那些任务由 模擬 / 方舟都市 去完成，
所以调度排在它们后面。
"""

from module.base.timer import Timer
from module.chaoszero.assets import (DAILY_CLAIM, DAILY_MENU_ITEM, DAILY_TITLE,
                                     LOBBY_ARK, MAIL_CLAIM, MAIL_TITLE)
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

# 两枚「全部領取」的判定区。2026-11-11 维护后 當日行程 的版面变了：按钮往下
# 挪了 30px（(138,548,431,600) → (142,574)-(340,630)），也不再和「100」
# 里程碑挤在同一行，所以这里只框那颗胶囊本身。
# ❗版面一改，`DAILY_CLAIM.png` 就必须一起重截，否则模板对不上，任务会空手关面板：
# 2026-11-11 19:41 + 18:54 两次就是这么丢的（`ui_claimable` 判「有得领」、
# `appear(DAILY_CLAIM)` 判「不在」，13ms 内放弃）。
DAILY_CLAIM_AREA = (140, 570, 345, 636)
MAIL_CLAIM_AREA = (51, 626, 309, 678)

# 「有得领」= 按钮是**彩色**的。占比由 `ChaoszeroUI.ui_colored_ratio()` 算
# （饱和像素 max-min > 60 的占比，不认色相），这里只是这两枚按钮的阈值。
# 实测（1280x720，astype(int) 之后算）：當日行程 有得领 68.9% / 领完 0.0%；
#                                       信箱     有得领 91.1% / 领完 0.0%。
CLAIM_COLORED = 0.35

# 按钮在不在，用**亮度**模板判（`match_luma`）：同一颗胶囊有彩色/灰白两态，
# 同一张模板对两态分别是 1.000 / 0.963（彩色模板直接对灰白态 `match` 只有
# 0.754，不够 0.85）。大厅、作戰 hub 等其它页面最高 0.134。
CLAIM_SIMILARITY = 0.85
# 面板滑入要一两秒，刚认出来那一帧按钮可能还没画到位。等按钮出现再下结论，
# 别拿单帧否定（硬约束 153）。
CLAIM_APPEAR_TIMEOUT = 8


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

    def ui_claimable(self, area):
        """
        Whether a 全部領取 button still has something to hand out.

        The button is drawn in an accent colour (orange today) while it has
        rewards to hand out, and in plain grey once the day is done. Counting
        the saturation instead of one specific hue keeps the check alive when
        the client restyles itself - the layout did change on 2026-11-11, and
        the colour is no safer a bet than the coordinates. The ratio itself
        lives in `ChaoszeroUI.ui_colored_ratio()`, this is just the threshold.

        Args:
            area (tuple): x1, y1, x2, y2 of the button.

        Returns:
            bool: If the button is coloured (= claimable).
        """
        return bool(self.ui_colored_ratio(area) > CLAIM_COLORED)

    # ---------------------------------------------------------------- 通用

    def claim_and_close(self, button, area, timeout=30, expect_reward=False):
        """
        Press one 全部領取 and settle whatever it opens.

        Both panels pop a 「獲得道具」 window, and it pops half a second
        **after** the button goes grey - returning on the grey signal alone
        leaves the window to `panel_quit()`, whose X closes the panel behind it
        and never lands (measured 2026-11-11 19:42 on the mailbox: claim at
        07.354, grey at 08.023, no 「Reward window closed」 in the log).
        當日行程 does the same: 2026-11-11 19:52 the claim showed 1,500 + 60 and
        the panel would not close for 30 seconds until the window was tapped
        (2026-11-10 20:02 `The panel did not close`). The 「does not raise a
        window」 note here was measured on 2026-11-04 and is no longer true.

        Pages:
            in: 有那个按钮的面板
            out: 同一个面板

        Args:
            button (Button): The 全部領取 button of the page.
            area (tuple): x1, y1, x2, y2 of that button, for the colour check.
            timeout (int): Seconds.
            expect_reward (bool): The panel always pops a 「獲得道具」 window,
                so the grey button alone does not mean the claim is finished.

        Returns:
            bool: If the claim went through.
        """
        timeout = Timer(timeout, count=3).start()
        press = Timer(2.5, count=2)
        tap = Timer(2, count=2)
        # 按钮变灰以后最多再等 5 秒的奖励窗；`expect_reward` 才用。
        grey = Timer(5, count=1)
        seen = False

        for _ in self.loop(timeout=timeout):
            if self.reward_appear():
                seen = True
                if tap.reached():
                    tap.reset()
                    # CHAOSZERO_TAP_CENTRE 是纯坐标 Button，不是 (x, y)；
                    # 以前写成 tap_point(*...) 会在走到这支时 TypeError。
                    self.device.click(CHAOSZERO_TAP_CENTRE)  # alas-lint: allow - only reached inside `if self.reward_appear()`, the 「獲得道具」 window is on screen
                continue
            if seen:
                logger.info('Reward window closed')
                return True
            claimable = self.ui_claimable(area)
            if not claimable:
                if not expect_reward:
                    logger.info('Claim took, the 全部領取 button is grey now')
                    return True
                # 按钮灰了还要把「獲得道具」等出来再点掉。
                if not grey.started():
                    grey.start()
                if grey.reached():
                    logger.info('Claim took, no reward window showed up')
                    return True
            elif expect_reward:
                grey.clear()
            if claimable and press.reached():
                press.reset()
                self.device.click_record_clear()
                self.device.click(button)  # alas-lint: allow - the caller checked the page and the button, and the colour check above re-runs every frame
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
        # 面板关掉到大厅画出来这段最多等 3 秒。等不到就交给 `ui_quit_to_main()`：
        # 关掉「作戰」之后大厅有可能直接停在**闲置立绘**（UI 全收起来），
        # 那会儿 page_main 一直不成立，在这里空转只会白白卡满 30 秒
        # （2026-11-11 20:43 真机：32.6 关掉面板 → 44:00 才超时，中间啥也没做）。
        # ❗不要给 `gone` 加 `count`：带 count 的 `reached()` 第一次就返回 True，
        # 面板一消失就会立刻跳出，那会儿大厅还在淡入（实测 1.0 秒后才能匹配）。
        gone = Timer(3)
        # 收菜单也节流 1 秒：菜单淡出的那两帧还在匹配，连点两下会把菜单又打开。
        close_menu = Timer(1, count=2)

        for _ in self.loop(timeout=timeout):
            if self.ui_page_appear(page_main):
                return True
            if not still_open():
                # 这两个面板都是从 ≡ 菜单里点开的，关掉以后底下**还是那个菜单**：
                # 菜单盖住 MAIN_MENU_STORY（故事）和 LOBBY_ARK（方舟都市）两块，
                # 不收掉它就一直不是大厅。再点一次 ≡ 收掉菜单。
                if self.appear(DAILY_MENU_ITEM, offset=(20, 20)):
                    if close_menu.reached():
                        close_menu.reset()
                        logger.info('Back to the menu, close it')
                        self.device.click_record_clear()
                        self.tap_point(*MENU_BTN)
                    continue
                if not gone.started():
                    gone.start()
                if gone.reached():
                    break
                continue
            gone.clear()
            if retry.reached():
                retry.reset()
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
        # 每个键各用 1 秒节流，别共用一个：共用一个 3 秒节流时，点完 ≡ 要等满
        # 3 秒才轮到点「日常任務」，点完菜单项又要等 3 秒才切页签
        # （通行证那边是 6 秒的同一个坑，2026-11-11 实测 5.9 秒）。
        menu = Timer(1, count=2)
        item = Timer(2, count=2)
        tab = Timer(1, count=2)
        # 点完菜单项到「作戰」总览画出来这一段（约 1 秒）两个判据都不成立，
        # 给 2 秒缓冲再切页签，免得在加载中的页面上乱按。
        loading = Timer(2, count=1)
        # 「日常任務」打开的是「作戰」总览，标签会停在上次看的那一页，
        # 所以点完菜单还要再点一次左侧的「當日行程」。
        opened = False

        for _ in self.loop(timeout=timeout):
            if self.daily_appear():
                logger.info('當日行程 is open')
                return True

            if self.appear(DAILY_MENU_ITEM, offset=(20, 20)):
                opened = True
                if item.reached():
                    item.reset()
                    loading.reset()
                    # 菜单还在淡入时点会被吞掉（通行证那边实测点完 4 秒仍停在菜单上），
                    # 等它静止再点，一次就中。
                    self.wait_until_still(DAILY_MENU_ITEM.area, timeout=2)
                    self.device.click_record_clear()
                    logger.info('Menu, open 日常任務')
                    self.device.click(DAILY_MENU_ITEM)
                continue

            if self.appear(LOBBY_ARK, offset=(20, 20)):
                opened = False
                if menu.reached():
                    menu.reset()
                    self.device.click_record_clear()
                    logger.info('Lobby, open the top-right menu')
                    self.tap_point(*MENU_BTN)
                continue

            # 点过「日常任務」了：等「作戰」总览画出来，然后切页签。
            # ❗这段**不能**掉进下面那个"闲置立绘"分支：在加载中的页面上点 ≡ 会把
            # 菜单打开，而菜单正好盖住 LOBBY_ARK 那条判据，后面 panel_quit 就再也
            # 认不出大厅，空转 30 秒（2026-11-11 20:41 真机就是这么卡住的）。
            if opened:
                if loading.reached() and tab.reached():
                    tab.reset()
                    self.device.click_record_clear()
                    logger.info('作戰 hub, switch to 當日行程')
                    self.tap_point(*DAILY_TAB)
                continue

            if menu.reached():
                menu.reset()
                self.device.click_record_clear()
                logger.info('Lobby is idle, tap to wake it up')
                self.tap_point(*MENU_BTN)
        else:
            logger.warning('Can not open 日常任務')
            return False

    def daily_claim(self, timeout=30):
        """
        Press 全部領取 on 當日行程 and close the reward window.

        判定顺序是「先等按钮画出来，再看它是不是彩色」：

        - 2026-11-11 19:41（以及 18:54 那次）翻车的直接原因是**版面变了**：
          维护后「全部領取」往下挪了 30px，`appear(DAILY_CLAIM, offset=(20,20))`
          的搜索窗只到 y=568，够不到 y=578 的按钮，于是打一句
          `The 全部領取 button is not on screen` 就把面板关掉、什么都没领。
          `ui_claimable` 那会儿是对的（橙色 → 有得领），错的是模板。
          教训：**版面一改就要重截素材**，判据再对也救不回旧坐标。
        - 顺带别拿单帧否定：`daily_open()` 只看标题就放行，按钮可能还没画到位。
          这里用亮度模板等按钮出现（彩色/灰白两态都成立，1.000 / 0.963），
          等到再判颜色，等不到就如实报 warning。

        Pages:
            in: 當日行程
            out: 當日行程

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If nothing is left to claim, or the claim went through.
        """
        for _ in self.loop(timeout=CLAIM_APPEAR_TIMEOUT):
            if not DAILY_CLAIM.match_luma(self.device.image, offset=(20, 20),
                                          similarity=CLAIM_SIMILARITY):
                # 按钮还没画出来（面板在淡入），下一帧再看。
                continue
            if not self.ui_claimable(DAILY_CLAIM_AREA):
                logger.info('Nothing to claim on 當日行程')
                return True
            logger.info('Claim the daily track')
            return self.claim_and_close(DAILY_CLAIM, DAILY_CLAIM_AREA,
                                        timeout=timeout, expect_reward=True)

        # 等不到按钮。分开报：「有得领但找不到按钮」= 版面变了，素材要重截；
        # 「颜色也是灰的」= 面板没打开/不在当页。
        if self.ui_claimable(DAILY_CLAIM_AREA):
            logger.warning('The 全部領取 button is not on screen but the area is '
                           'still coloured, the panel layout probably changed, '
                           're-shoot DAILY_CLAIM.png')
        else:
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
        # 同 daily_open()：≡ 和信封各一个 1 秒节流，别共用一个 3 秒的。
        menu = Timer(1, count=2)
        envelope = Timer(2, count=2)
        # 点完信封到信箱滑进来约两三秒，这期间两个判据都不成立，别回头去点 ≡。
        loading = Timer(6, count=1)

        for _ in self.loop(timeout=timeout):
            if self.mail_appear():
                logger.info('信箱 is open')
                return True

            if self.appear(DAILY_MENU_ITEM, offset=(20, 20)):
                if envelope.reached():
                    envelope.reset()
                    loading.reset()
                    # 同 daily_open()：菜单淡入时的点击会被吞掉。
                    self.wait_until_still(DAILY_MENU_ITEM.area, timeout=2)
                    self.device.click_record_clear()
                    logger.info('Menu, open 信箱')
                    self.tap_point(*MAIL_BTN)
                continue

            if loading.reached() and menu.reached():
                menu.reset()
                self.device.click_record_clear()
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
        # 2026-11-11 18:54 就是这样丢的一次：面板 1 秒前才认出来，按钮还没滑到位，
        # 颜色说「有得领」、模板说「不在」，于是空手关掉面板。
        for _ in self.loop(timeout=CLAIM_APPEAR_TIMEOUT):
            if not MAIL_CLAIM.match_luma(self.device.image, offset=(20, 20),
                                         similarity=CLAIM_SIMILARITY):
                continue
            if not self.ui_claimable(MAIL_CLAIM_AREA):
                logger.info('No unclaimed mail')
                return True
            logger.info('Claim all mail')
            return self.claim_and_close(MAIL_CLAIM, MAIL_CLAIM_AREA,
                                        timeout=timeout, expect_reward=True)

        if self.ui_claimable(MAIL_CLAIM_AREA):
            logger.warning('The mail 全部領取 button is not on screen but the area '
                           'is still coloured, re-shoot MAIL_CLAIM.png')
        else:
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
