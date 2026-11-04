"""方舟都市的两个每日动作：政策室批政策、咖啡廳点餐。

页面链（2026-10-30 实机量的，1280x720）：

    主界面右侧竖排菜单第五项「方舟都市」(1215, 386)
        → 方舟都市：底部一条横排入口
            政策室 (295, 605) / 星光食堂 / 庭院咖啡廳 (583, 605) /
            治療中心 / 研究設施 / 諾諾商店
        → 政策室首页：左边四项都市指数，右边一叠政策卡，底部
            「需要討論的政策 8/8」或「政策招募公告中 04:57:43 5/8」
        → 点卡片堆 (950, 360) → 批准页：左右两份政策文件 + 中间一枚金印章，
            底部「請拖曳印章到文件上以完成批准」
        → 把印章从底座 (958, 600) 拖到某一份文件上 → 该份文件亮起并预览
            都市指数的变化 → 点一下画面 → 直接翻到下一份政策
        → 咖啡廳：右下角「點餐」(1088, 634) → 菜單面板（內用 +120 體力 /
            外帶 +1 埃忒耳充電貨幣）→ 选中一项「點餐」变蓝 → 点 (940, 628)
            → 冲咖啡的过场（右上「跳過」）→「獲得道具」→ 点一下关掉

**批准一份政策会消耗一天**：左上「倒數 25 天」在盖章后变成 24。所以这个任务是
"每天批几份"的量，不是"把能批的都批掉"——配置里默认一天一份。

咖啡廳每天只能点一次：点过之后「點餐」按钮还在，但按下去菜单不再弹出。所以
"菜单没弹出来"就是"今天已经点过了"，不是失败。
"""

import cv2
import numpy as np

from module.base.timer import Timer
from module.chaoszero.assets import (ARK_TITLE, CAFE_DINEIN, CAFE_ORDER, CAFE_TITLE,
                                     LOBBY_ARK, POLICY_EMPTY, POLICY_STAMP,
                                     POLICY_TITLE)
from module.chaoszero.chaoszero_ui import (CHAOSZERO_BACK, CHAOSZERO_TAP_CENTRE,
                                           ChaoszeroUI)
from module.chaoszero.page import page_main
from module.logger import logger

# 主界面右侧竖排菜单第五项「方舟都市」的图标中心。
ARK_ENTRY = (1215, 386)
# 主界面的闲置态：停手二十秒后整个 UI 会收起来只剩一张全屏立绘，这时**第一下
# 点击只负责把界面叫醒**，而且不能点在人物身上（那会进入对话互动，界面继续不
# 响应）。这一下点画面顶部中间，那里永远是空的。
ARK_WAKE = (640, 96)

# 方舟都市底部那排入口。
ARK_POLICY = (295, 605)
ARK_CAFE = (583, 605)

# 政策室。
POLICY_CARDS = (950, 360)          # 首页那叠政策卡
POLICY_STAMP_GRAB = (958, 600)     # 印章底座（拖动的起点）
POLICY_PAPER_LEFT = (720, 300)     # 左边文件
POLICY_PAPER_RIGHT = (1090, 300)   # 右边文件
# 印章底座那一块：印章还在座上时是亮的（实测亮像素 64%、均值 190），拖走以后
# 只剩深色的台面（亮像素 0.1%、均值 50）。这是"这一份盖没盖"的唯一可靠判据 ——
# 底部那行「請拖曳印章…」在盖完之后**仍然在**，拿它判会一路绿灯。
POLICY_STAMP_BASE = (900, 555, 1025, 655)
POLICY_STAMP_PIXELS = 3000

# 批准页左右两份文件的「纸面」范围，奖励图标就排在里面第一列。
POLICY_LEFT_CARD = (645, 130, 875, 480)
POLICY_RIGHT_CARD = (975, 130, 1250, 480)
# 奖励图标方块的大小（实测 47x47）。索引箭头太小、文字太扁，都落不进这个范围。
POLICY_ICON_MIN = 34
POLICY_ICON_MAX = 62
# 一次最多批几份，防止"全批"在某个判据失灵时空转。
POLICY_MAX_PER_RUN = 10

# 咖啡廳。
CAFE_ORDER_POINT = (1088, 634)     # 右下角「點餐」
CAFE_DINEIN_POINT = (805, 195)     # 菜單里的「內用」
CAFE_CONFIRM = (940, 628)          # 菜單底部的「點餐」
# 菜单底部那枚「點餐」：没选东西时是灰白（均值 158,158,158，橙色像素 0%），选中
# 「內用」以后整枚变橙（实测均值 240,134,61，橙色像素 88.8%）。用它判"选没选中"。
# 2026-11-04 之前这里判的是**蓝色** —— 旧版菜单确实是变蓝，改版后整枚变橙，
# 于是一直判"没选中"，`cafe_order()` 在 20 秒里对着「內用」连点了 100 次。
CAFE_CONFIRM_AREA = (830, 615, 1050, 645)
CAFE_CONFIRM_ORANGE = 0.4


class ChaoszeroArk(ChaoszeroUI):
    """方舟都市 —— 政策室批政策 + 咖啡廳领体力。"""

    # ---------------------------------------------------------------- 页面判据

    def ark_appear(self):
        """Returns: bool: 在方舟都市首页。"""
        return bool(self.appear(ARK_TITLE, offset=(20, 20)))

    def policy_appear(self):
        """Returns: bool: 在政策室里（首页和批准页都算）。"""
        return bool(self.appear(POLICY_TITLE, offset=(20, 20)))

    def approval_appear(self):
        """Returns: bool: 在政策批准页（两份文件 + 印章）。"""
        return bool(self.appear(POLICY_STAMP, offset=(20, 20)))

    def cafe_appear(self):
        """Returns: bool: 在庭院咖啡廳。"""
        return bool(self.appear(CAFE_TITLE, offset=(20, 20)))

    def cafe_menu_appear(self):
        """Returns: bool: 咖啡廳的菜單面板开着。"""
        return bool(self.appear(CAFE_DINEIN, offset=(20, 20)))

    def ui_stamp_ready(self):
        """
        Whether the stamp is still sitting on its stand.

        True means the current proposal has NOT been stamped yet.

        Returns:
            bool: If the stand still holds the stamp.
        """
        image = self.image_crop(POLICY_STAMP_BASE)
        return bool(np.count_nonzero(image.mean(axis=2) > 150) > POLICY_STAMP_PIXELS)

    def ui_cafe_confirm_ready(self):
        """
        Whether the menu's 點餐 button has gone orange, i.e. a dish is selected.

        Returns:
            bool: If the button is active.
        """
        image = self.image_crop(CAFE_CONFIRM_AREA).astype(int)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        orange = np.count_nonzero((r > 200) & (g > 90) & (g < 180) & (b < 110))
        return bool(orange > CAFE_CONFIRM_ORANGE * image.shape[0] * image.shape[1])

    # ---------------------------------------------------------------- 走去方舟都市

    def ark_enter(self, timeout=90):
        """
        Walk the lobby into 方舟都市.

        The lobby collapses its whole UI after ~20 seconds without input. The
        first tap on the idle artwork only wakes it up, and if that tap lands on
        the character it starts a chat instead and the menu stays dead — so the
        wake tap goes to the empty top of the screen, and the menu entry is only
        pressed once `LOBBY_ARK` is actually visible.

        Pages:
            in: page_main
            out: 方舟都市

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If 方舟都市 is open.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(3, count=2)

        for _ in self.loop(timeout=timeout):
            if self.ark_appear():
                logger.info('At 方舟都市')
                return True

            if not retry.reached():
                continue
            retry.reset()
            self.device.click_record_clear()

            if self.appear(LOBBY_ARK, offset=(20, 20)):
                logger.info('Lobby, open 方舟都市')
                self.tap_point(*ARK_ENTRY)
            else:
                logger.info('Lobby is idle, tap the top to wake the UI up')
                self.tap_point(*ARK_WAKE)
        else:
            logger.warning('Can not open 方舟都市')
            return False

    # ---------------------------------------------------------------- 政策室

    def policy_card_rewards(self, area):
        """
        Count the *extra* rewards printed on one proposal.

        每份政策都必带一条「獲得N個政策點數」，所以"图标数 - 1"就是额外奖励的条数。
        奖励图标是纸面上唯一那种 47x47 的彩色圆角方块 —— 都市指数的箭头只有十几
        像素高，文字更扁，都落不进这个尺寸范围，所以用连通域数就行，**不需要认识
        具体是什么道具**。这也是为什么它天生适配以后新加的奖励种类。

        Args:
            area (tuple): 这张卡的纸面范围。

        Returns:
            tuple: (额外奖励条数, 图标总数)
        """
        image = self.image_crop(area).astype(int)
        high = image.max(axis=2)
        low = image.min(axis=2)
        mask = (((high - low) > 55) & (high > 50)).astype(np.uint8)
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

        icons = 0
        for index in range(1, count):
            _, _, width, height, size = stats[index]
            if POLICY_ICON_MIN <= width <= POLICY_ICON_MAX \
                    and POLICY_ICON_MIN <= height <= POLICY_ICON_MAX and size > 500:
                icons += 1
        return max(0, icons - 1), icons

    def policy_pick(self):
        """
        Choose the proposal with more extra rewards.

        「政策點數不重要」，所以只比额外奖励的条数；一样多就盖左边（或听配置）。

        Returns:
            str: 'left' or 'right'.
        """
        left_extra, left_icons = self.policy_card_rewards(POLICY_LEFT_CARD)
        right_extra, right_icons = self.policy_card_rewards(POLICY_RIGHT_CARD)
        logger.info(f'Reward icons: left {left_icons} ({left_extra} extra), '
                    f'right {right_icons} ({right_extra} extra)')

        if right_extra > left_extra:
            logger.info('The right proposal gives more')
            return 'right'
        if left_extra > right_extra:
            logger.info('The left proposal gives more')
            return 'left'
        logger.info('Same reward count, keep it simple')
        return 'left'

    def policy_open(self, timeout=45):
        """
        Walk from 方舟都市 (or 政策室 首页) to the approval screen.

        Pages:
            in: 方舟都市 | 政策室（首页）
            out: 批准页

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the approval screen is up.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(3, count=2)

        for _ in self.loop(timeout=timeout):
            if self.approval_appear():
                return True

            # 政策室首页右边那个空槽写着「新增政策」= 今天没有待批的了，
            # 不用再等 45 秒的「打不开」。
            if self.appear(POLICY_EMPTY, offset=(20, 20)):
                logger.info('The deck is empty')
                return False

            if not retry.reached():
                continue
            retry.reset()
            self.device.click_record_clear()

            if self.policy_appear():
                logger.info('政策室, open the proposal deck')
                self.tap_point(*POLICY_CARDS)
            else:
                logger.info('方舟都市, open 政策室')
                self.tap_point(*ARK_POLICY)
        else:
            logger.warning('The approval screen did not open')
            return False

    def policy_stamp(self, timeout=60):
        """
        Drag the stamp onto one of the two proposals and walk to the next one.

        The stamp lands on the document and stays there; one more tap then flips
        to the following proposal with the stamp back on its stand. So the whole
        step is "drag, then tap until the stamp is back on its stand".

        Pages:
            in: 批准页（印章在座上）
            out: 批准页（下一份，印章在座上）

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If one proposal was approved.
        """
        # 批准页滑进来时模板判据会提前放行，奖励图标要在完全画好的帧上数。
        self.wait_until_settled(POLICY_STAMP, timeout=5)

        side = self.config.ChaoszeroArk_PolicySide
        if side not in ('left', 'right'):
            side = self.policy_pick()
        target = POLICY_PAPER_RIGHT if side == 'right' else POLICY_PAPER_LEFT
        logger.info(f'Stamp the {side} proposal')

        self.device.drag(POLICY_STAMP_GRAB, target,
                         point_random=(0, 0, 0, 0), hold_duration=0.4)

        # 拖动本身会被转场吃掉（实测同一个点时有成功时有失败），离座才是证据。
        moved = Timer(6, count=3).start()
        while not moved.reached():
            self.device.screenshot()
            self.device.stuck_record_clear()
            if not self.ui_stamp_ready():
                break
        else:
            logger.warning('The stamp did not leave its stand')
            return False

        timeout = Timer(timeout, count=3).start()
        tap = Timer(2, count=2)

        for _ in self.loop(timeout=timeout):
            if self.ui_stamp_ready():
                logger.info('Proposal approved')
                return True
            # 批掉最后一份会直接回政策室首页，右边那个空槽写着「新增政策」。
            # 少了这一支，循环会一直点画面正中，最后撞上 12 次点击上限。
            if self.appear(POLICY_EMPTY, offset=(20, 20)):
                logger.info('Proposal approved, the deck is empty now')
                return True
            if tap.reached():
                tap.reset()
                self.device.click_record_clear()
                self.device.click(CHAOSZERO_TAP_CENTRE)  # alas-lint: allow - the two branches above already ruled out every page this loop knows
        else:
            logger.warning('The stamp never came back to its stand')
            return False

    def policy_run(self, times):
        """
        Approve proposals — `times` of them, or every one the deck offers.

        批到批不动为止：`policy_open()` 打不开就说明卡叠空了（或者今天已经没得批）。
        第一份给足时间，后面几份缩到 20 秒 —— 真的还有货的时候它是立刻就开的。

        Pages:
            in: 方舟都市
            out: 方舟都市

        Args:
            times (int): How many proposals to approve, 0 = all of them.

        Returns:
            bool: If at least one went through.
        """
        logger.hr('政策室 全批' if times <= 0 else f'政策室 x{times}', level=2)

        limit = times if times > 0 else POLICY_MAX_PER_RUN
        done = 0

        for index in range(limit):
            timeout = 45 if index == 0 else 20
            if not self.policy_open(timeout=timeout):
                # 卡叠空着是正常状态（都批完了），不是失败。
                if self.appear(POLICY_EMPTY, offset=(20, 20)):
                    logger.info('No proposals waiting, nothing to approve')
                    return True
                if index == 0:
                    logger.warning('The proposal deck did not open')
                    return False
                logger.info('Stop here')
                break
            if not self.policy_stamp():
                logger.warning(f'Proposal {index + 1}: stamping failed')
                break
            done += 1

        logger.info(f'{done} proposal(s) approved')
        return done > 0

    def ark_back_to_city(self, timeout=30):
        """
        Walk from 政策室 back to 方舟都市.

        Pages:
            in: 政策室（首页或批准页）
            out: 方舟都市

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If 方舟都市 is back.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(2, count=2)

        for _ in self.loop(timeout=timeout):
            if self.ark_appear():
                return True
            if retry.reached():
                retry.reset()
                self.device.click_record_clear()
                self.device.click(CHAOSZERO_BACK)  # alas-lint: allow - the loop only gets here after ruling out 方舟都市, so we are inside it; the arrow is fixed chrome
        else:
            logger.warning('Did not get back to 方舟都市')
            return False

    # ---------------------------------------------------------------- 咖啡廳

    def cafe_open(self, timeout=45):
        """
        Walk from 方舟都市 to 庭院咖啡廳.

        Pages:
            in: 方舟都市
            out: 庭院咖啡廳

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the cafe is open.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(3, count=2)

        for _ in self.loop(timeout=timeout):
            if self.cafe_appear():
                return True
            if not retry.reached():
                continue
            retry.reset()
            self.device.click_record_clear()
            logger.info('方舟都市, open 庭院咖啡廳')
            self.tap_point(*ARK_CAFE)
        else:
            logger.warning('Can not open 庭院咖啡廳')
            return False

    def cafe_menu(self, timeout=25):
        """
        Press 點餐 and tell whether the menu comes up.

        The cafe only serves one order a day: after that the button is still
        there but does nothing, so "no menu" is a normal answer, not an error.

        Pages:
            in: 庭院咖啡廳
            out: 庭院咖啡廳（菜單开着或不开）

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the menu opened.
        """
        timeout = Timer(timeout, count=3).start()
        tap = Timer(3, count=2)

        for _ in self.loop(timeout=timeout):
            if self.cafe_menu_appear():
                return True
            if tap.reached():
                tap.reset()
                if self.appear(CAFE_ORDER, offset=(20, 20)):
                    self.device.click_record_clear()
                    self.device.click(CAFE_ORDER)
                else:
                    logger.warning('The 點餐 button is not on screen')
                    return False
        else:
            return False

    def cafe_order(self, timeout=180):
        """
        Pick 內用 and confirm, then walk back to the cafe.

        內用 gives +120 體力 straight away; 外帶 hands out a charge coin worth 60
        that has to be spent later, so it is strictly worse while stamina is not
        capped. The order runs a coffee-brewing cutscene (with a 跳過 button in
        the top right) and ends on a 「獲得道具」 window that any tap closes.

        Pages:
            in: 庭院咖啡廳（菜單开）
            out: 庭院咖啡廳

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the order went through and the cafe is back.
        """
        logger.info('Choose 內用')
        # 1.5 秒一下：菜单是滑进来的，刚打开那一下常被转场吃掉；而每帧都点会在
        # 判据失灵时变成狂点（2026-11-04 旧判据下 20 秒点了 100 次）。
        press = Timer(1.5, count=2)
        for _ in self.loop(timeout=20):
            if self.ui_cafe_confirm_ready():
                break
            if press.reached():
                press.reset()
                self.device.click_record_clear()
                self.tap_point(*CAFE_DINEIN_POINT)
        else:
            logger.warning('The 內用 dish did not get selected')
            return False

        logger.info('Order it')
        self.device.click_record_clear()
        self.tap_point(*CAFE_CONFIRM)

        # 菜单先关掉才算点中了「點餐」。`cafe_appear()` 只看左上角的页面标题，而
        # 菜单是盖在咖啡廳页面上的浮层 —— 标题一直露在外面，所以菜单开着的时候
        # 它也是 True（2026-11-04：点完 0.2 秒就报「Stamina claimed」，其实订单
        # 才刚开始过场，点空了也看不出来）。
        self.wait_until_disappear(CAFE_DINEIN, offset=(20, 20), timeout=10, settle=2)

        # 过场 + 获得道具 + 回到咖啡廳，都在这一段里。
        timeout = Timer(timeout, count=3).start()
        tap = Timer(3, count=2)

        for _ in self.loop(timeout=timeout):
            if self.cafe_appear():
                logger.info('Stamina claimed')
                return True
            if tap.reached():
                tap.reset()
                self.device.click(CHAOSZERO_TAP_CENTRE)  # alas-lint: allow - the branch above already ruled out every known page; a centre tap is the only thing that moves a reward/preview window on
        else:
            logger.warning('The cafe never came back after ordering')
            return False

    # ---------------------------------------------------------------- 收尾

    def ark_quit(self, timeout=45):
        """
        Walk back to the lobby.

        Pages:
            in: any
            out: page_main

        Args:
            timeout (int): Seconds.

        Returns:
            bool: If the lobby is back.
        """
        timeout = Timer(timeout, count=3).start()
        retry = Timer(2, count=2)

        for _ in self.loop(timeout=timeout):
            if self.ui_page_appear(page_main):
                logger.info('Back at page_main')
                return True
            if retry.reached():
                retry.reset()
                self.device.adb_shell(['input', 'keyevent', '4'])
        else:
            # 返回键不一定按得动（政策室首页见过按不动），最后交给启动循环。
            logger.info('Back keys did not land, walk the boot screens')
            return self.ui_quit_to_main()

    def run(self):
        """
        Task: 方舟都市的每日 —— 政策室批政策 + 咖啡廳领体力。

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('方舟都市', level=1)

        # 守卫（固定两行）：两个动作全关就不启动游戏，直接把任务关掉。
        if not (self.config.ChaoszeroArk_PolicyEnable or self.config.ChaoszeroArk_CafeOrder):
            logger.info('Policy approval and cafe order are both off')
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        # 上一个任务可能把游戏停在模擬或政策室里（这些页面之间没有 link，
        # `ui_goto` 走不了），先自己退到主界面。
        if not self.ui_page_appear(page_main):  # alas-lint: allow - "not at the lobby" is the question; ui_quit_to_main() is bounded
            logger.info('Not at the lobby, walk back first')
            self.ui_quit_to_main()

        if not self.ark_enter():
            logger.warning('Cannot open 方舟都市, try again later')
            self.config.task_delay(success=False)
            return

        if self.config.ChaoszeroArk_PolicyEnable:
            times = int(self.config.ChaoszeroArk_PolicyTimes)
            # 批不批得成都要回方舟都市：下一步的咖啡廳跟政策室没关系。
            if not self.policy_run(times):
                logger.warning('Policy approval did not finish')
            self.ark_back_to_city()
        else:
            logger.info('Policy approval is off')

        if self.config.ChaoszeroArk_CafeOrder:
            if self.ark_enter(timeout=45) and self.cafe_open():
                if self.cafe_menu():
                    self.cafe_order()
                else:
                    logger.info('The cafe menu does not open, today is already taken')
        else:
            logger.info('Cafe order is off')

        self.ark_quit()
        self.config.task_delay(server_update=True)
