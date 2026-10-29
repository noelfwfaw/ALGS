"""兑换码：从 GameKee 抓、在游戏里兑、把结果记在本机上。

每天一次。抓取是纯网络的，所以没有新码时这个任务一行都不会碰游戏 ——
`run()` 里的 `ui_ensure()` 在抓取和过滤之后才调用，没有待兑换的码就直接排到
明天。

游戏里的路径（2026-10-29 实测）：

    大厅 --右上三条横线--> 菜单面板 --右侧竖排的齿轮--> 设置
    设置 --左侧最下面的「账号」--> 账号页 --底部「兑换优惠券」--> 兑换弹窗
    兑换弹窗 --点输入框--> 游戏自己的输入条（屏幕最下方一整条）
    输入条 --确定--> 弹窗 --兑换--> 结果弹窗（一个「!」+ 一行字 + 「确认」）

两个实测细节决定了这个任务的写法：

**弹窗的 X 和结果弹窗的 X 是同一个像素 `(945,152)`**。结果弹窗刚关掉那一帧按下去，
点在的是正在淡出的上一层，等于没点；实测两次（10:35、10:40）都是弹窗和设置页
**各按了第二次才关**，`wait_until_disappear()` 白白跑满两个 6 秒。所以关闭路径
每一步都要先等静止、再按、再看清现在是哪一层。

**设置页不在页面图里，退不出去时不能调 `ui_goto_main()`**：那会抛
`GamePageUnknownError`，调度器把它变成 `exit(1)` —— 整个进程，不是这个任务。
留在设置页还会让下一个任务连 `ui_ensure(page_main)` 都过不去。

往输入框里打字那一段（输入条、清空、判有没有字）在 `coupon_input.py`。
"""

from module.base.timer import Timer
from module.coupon.codes import EXPIRED, FAILED, REDEEMED, USED, CodeBook
from module.coupon.gamekee import GameKeeError, fetch_codes
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, REDEEM_BTN_CONFIRM,
                                     REDEEM_BTN_COUPON, REDEEM_BTN_SUBMIT,
                                     REDEEM_DIALOG_TITLE, REDEEM_ENTRY,
                                     REDEEM_TAB_ACCOUNT, REDEEM_TITLE_SETTING)
from module.lostsword.coupon_input import REDEEM_INPUT, REDEEM_KEYBOARD_OK, CouponInput
from module.lostsword.lostsword_ui import LostswordUI, page_battle, page_main
from module.lostsword.utils import read_text

# 账本。放在 `config/state/` 而不是 `config/` 顶层：那里每个 json 都会被
# `alas_instance()` 当成一个调度器实例（硬约束 118）。
COUPON_LEDGER = './config/state/lostsword_codes.json'

# 大厅右上角的三条横线。这个图标本身带红点、背后是会动的链条，做不成模板，
# 所以按坐标点，点完用菜单里的齿轮（`REDEEM_ENTRY`）验证菜单真的开了。
MAIN_BTN_MENU = (1230, 25)
# 结果弹窗的那一行提示。故意框得宽一点：文案长短不一，居中的位置跟着变。
REDEEM_RESULT_AREA = (450, 335, 850, 380)
# 结果弹窗自己的 X，和设置页右上角那个是同一版式但不同位置。
REDEEM_DIALOG_CLOSE = (945, 152)
# 设置页 / 账号页中间那块内容。换页动画期间它会移动，点之前先等它停。
REDEEM_PAGE_BODY = (250, 80, 1100, 640)
# 兑换弹窗的正文。上一个码的「确认」刚点完就点输入框，那一下会落在弹窗关闭的
# 动画上，所以同样先等它停。
REDEEM_DIALOG_BODY = (250, 100, 1050, 620)


def classify_result(text):
    """
    Turn the one line of the result dialog into a ledger status.

    The OCR of this game drops characters on small white text - measured on
    「已使用过的优惠券。」 it returned 「已用过券」 - so the test is on two or
    three character fragments, never on the whole sentence.

    Args:
        text (str): Han characters read from the dialog, may be empty.

    Returns:
        str: One of `REDEEMED` / `USED` / `EXPIRED` / `FAILED`.
    """
    if not text:
        return FAILED
    if '用过' in text or '已使用' in text:
        return USED
    if '成功' in text:
        return REDEEMED
    if '过期' in text:
        return EXPIRED
    # 「无效」「不存在」「格式错误」 and anything else the code cannot be: the
    # ledger still marks it so the task does not send it again tomorrow.
    return FAILED


class LostswordRedeem(LostswordUI, CouponInput):
    """
    Send every coupon that is new, alive and not in the ledger yet.

    The typing into the game's own input bar lives in `CouponInput`, because it
    is the one part of this flow that is about pixels and key codes rather than
    about pages.

    Pages:
        in: page_main
        out: page_main
    """

    # 最近一次结果弹窗读到的原话，写进账本方便事后对账。
    coupon_said = ''

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Coupon codes', level=1)

        # 网络这一半先做：没有新码就完全不碰游戏。
        codes = self.coupon_fetch()
        if codes is None:
            self.config.task_delay(server_update=True)
            return

        book = CodeBook(COUPON_LEDGER)
        book.log_summary()
        todo = book.pending(codes)
        # `pending()` 顺手把过期码记进账本，这里落一次盘。
        book.save()
        logger.info(f'Coupons alive: {len(codes)}, to try: {len(todo)}')
        if not todo:
            logger.info('Nothing new to redeem today')
            self.config.task_delay(server_update=True)
            return

        if not self.coupon_enter():
            logger.warning('Could not open the coupon dialog, try again tomorrow')
            self.coupon_exit()
            self.config.task_delay(server_update=True)
            return

        redeemed = 0
        for code in todo:
            # 用带超时的等待而不是看一眼：换页 / 掉线的中间帧一个检测点都不匹配，
            # 单帧判断会把"正在动"当成"界面没了"，剩下的码白等一天。
            if not self.wait_until_appear(REDEEM_DIALOG_TITLE, offset=30, timeout=3):
                # 界面跑丢了（掉线、被弹窗顶掉）。剩下的码不进账本，明天还会试。
                logger.warning('The coupon dialog is gone, stop here and retry tomorrow')
                break
            status = self.coupon_redeem(code)
            book.mark(code, status, self.coupon_said)
            # 一条一条落盘：中途崩了也不会把已经兑过的码再兑一遍。
            book.save()
            if status == REDEEMED:
                redeemed += 1

        logger.info(f'Coupons redeemed: {redeemed}, tried: {len(todo)}')
        book.log_summary()
        self.coupon_exit()
        self.config.task_delay(server_update=True)

    def coupon_fetch(self):
        """
        Read the list, keeping the failure inside this task.

        Returns:
            list[dict] or None: None when the site could not be read at all.
        """
        try:
            codes = fetch_codes(alias='lostsword', page=20)
        except GameKeeError as e:
            # Not an exception for the scheduler: the list being down is not a
            # broken game, and the next run is tomorrow anyway.
            logger.warning(f'Coupon list is unavailable today: {e}')
            return None

        for code in codes:
            logger.attr('Coupon', '{:20} expires {}'.format(
                code['code'], code['end_at'].strftime('%Y-%m-%d')))
        return codes

    def coupon_enter(self, timeout=10):
        """
        大厅 -> 菜单 -> 齿轮 -> 设置 -> 账号 -> 兑换弹窗。

        Pages:
            in: page_main
            out: the coupon dialog

        Args:
            timeout (int, float): Seconds per step.

        Returns:
            bool: If the dialog is open.
        """
        self.ui_ensure(page_main)

        # 上一次跑到一半退出，菜单可能还开着。
        if not self.coupon_menu_open():
            self.tap_point(*MAIN_BTN_MENU)
            if not self.wait_until_appear(REDEEM_ENTRY, offset=30, timeout=5):
                logger.info('The lobby menu did not open, press it again')
                self.tap_point(*MAIN_BTN_MENU)
                if not self.wait_until_appear(REDEEM_ENTRY, offset=30, timeout=5):
                    logger.warning('The lobby menu does not open')
                    return False

        # 三步都是同一个动作：点一颗按钮，等它开出下一个界面。
        if not self.coupon_step(REDEEM_ENTRY, REDEEM_TITLE_SETTING,
                                'the gear of the menu', timeout=timeout):
            return False
        # 账号标签在设置页最下面。已经在账号页时再点一次只是重新选中，没有副作用。
        if not self.coupon_step(REDEEM_TAB_ACCOUNT, REDEEM_BTN_COUPON,
                                'the account tab', timeout=timeout):
            return False
        if not self.coupon_step(REDEEM_BTN_COUPON, REDEEM_DIALOG_TITLE,
                                'the coupon button', timeout=timeout):
            return False
        return True

    def coupon_step(self, button, check, label, timeout=8, tries=2):
        """
        点一颗按钮，直到它开出下一个界面。

        这个游戏每换一页都是滑进来 / 淡进来，动画期间的点击会被吞掉，
        而模板往往在动画第一帧就匹配上了 —— 于是"页面到了"和"可以点了"
        是两件事。实测两次：2026-10-29 10:32 的设置页（标题匹配上，
        点账号标签没人理）、10:33 的账号页（点「兑换优惠券」弹窗一直不来）。

        所以先等界面停下来再点，点完没反应就再点一次，两次都不行才认输。

        Args:
            button (Button): 要点的按钮。
            check (Button): 下一个界面的检测点。
            label (str): 日志里怎么称呼这颗按钮。
            timeout (int, float): 等下一个界面出现的秒数。
            tries (int): 最多点几次。

        Returns:
            bool: 下一个界面到了。
        """
        for _ in range(tries):
            self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)
            self.tap_asset(button)
            if self.wait_until_appear(check, offset=30, timeout=timeout):
                return True
            logger.info(f'{label} did not open the next page, press it again')

        logger.warning(f'{label} does not open the next page')
        return False

    def coupon_menu_open(self, timeout=1):
        """
        Whether the lobby's side menu is already open.

        One frame cannot answer this: the menu slides in, and during the slide
        out its buttons are still where they were. Asking properly costs the
        timeout once per run, and only when the answer is "closed" - which is
        the normal case.

        Written as a loop instead of `wait_until_appear()` on purpose: the
        timeout is the expected answer on most days, and that helper reports a
        warning whenever it hits one. A daily warning in an otherwise clean log
        hides the ones that matter.

        Args:
            timeout (int, float): Seconds to look at the menu.

        Returns:
            bool: If the menu is up.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(REDEEM_ENTRY, offset=30):
                return True
            if timeout.reached():
                return False

    def coupon_redeem(self, code):
        """
        Type one code into the dialog and read the answer.

        Pages:
            in: the coupon dialog
            out: the coupon dialog

        Args:
            code (dict): `{'code', 'content', 'end_at'}`.

        Returns:
            str: A ledger status.
        """
        text = code['code']
        logger.hr(f'Coupon {text}', level=2)
        # 清掉上一条的原话：这一条要是根本没能提交（输入条没弹、按钮没了），
        # 账本的 `detail` 会拿到上一条的「已使用过」，把失败写成像用过了。
        self.coupon_said = ''

        # 上一个码刚处理完就点输入框，那一下会落在结果弹窗的关闭动画上被吞掉
        # （实测 2026-10-29 10:35：五个码交替成功和失败，相邻两次点击只隔 7 ms）。
        self.wait_until_still(REDEEM_DIALOG_BODY, timeout=3)
        self.tap_point(*REDEEM_INPUT)
        if not self.coupon_keyboard(want=True):
            logger.info('The input bar is still closed, press the box again')
            self.tap_point(*REDEEM_INPUT)
            if not self.coupon_keyboard(want=True):
                logger.warning('The input bar does not open')
                return FAILED

        # 游戏不会自己清掉上一个码，不清就会两个码拼在一起。
        self.coupon_clear()
        if not self.coupon_input_wait(want_text=False):
            logger.warning('The input box still holds an old code, skip this one')
            self.coupon_keyboard_close()
            return FAILED

        # 键码走 adb：这个游戏的输入条是自绘的，`input text` 直接写进去。
        self.device.adb_shell(['input', 'text', text])  # alas-lint: allow
        if not self.coupon_input_wait(want_text=True):
            logger.warning('The code does not land in the input box')
            self.coupon_keyboard_close()
            return FAILED

        self.tap_point(*REDEEM_KEYBOARD_OK)
        if not self.coupon_keyboard(want=False):
            logger.warning('The input bar does not close')
            return FAILED

        # 输入条收起后弹窗要过一帧才重新画出来，等它一下。
        if not self.wait_until_appear(REDEEM_BTN_SUBMIT, offset=30, timeout=5):
            logger.warning('The redeem button is gone')
            return FAILED
        self.tap_asset(REDEEM_BTN_SUBMIT)

        status = self.coupon_result()
        logger.info(f'Coupon {text}: {status}')
        return status

    def coupon_result(self, timeout=10):
        """
        Read the result dialog and dismiss it.

        Pages:
            in: the coupon dialog with a result on top
            out: the coupon dialog

        Args:
            timeout (int, float): Seconds to wait for the answer.

        Returns:
            str: A ledger status.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(REDEEM_BTN_CONFIRM, offset=30):
                said = read_text(self.device.image, REDEEM_RESULT_AREA)
                self.coupon_said = said
                logger.info(f'The game said: {said or "(nothing readable)"}')
                self.tap_asset(REDEEM_BTN_CONFIRM)
                self.wait_until_disappear(REDEEM_BTN_CONFIRM, offset=30, timeout=5)
                return classify_result(said)

            if timeout.reached():
                logger.warning('The game does not answer the redeem press')
                return FAILED

    def coupon_exit(self, rounds=4, timeout=40):
        """
        Close the coupon dialog and the settings page, end on the lobby.

        Two things were measured on 2026-10-29 and both are the reason this is a
        loop instead of a straight line of presses:

        The X of this dialog and the X of the result dialog are the same pixel
        `(945, 152)`. A press sent in the frame the result dialog closes lands on
        the layer that is fading out and does nothing, and `wait_until_disappear()`
        then runs its full six seconds. Measured twice: 10:35 and 10:40, each
        time the dialog and then the settings page needed a *second* press. So
        every press here is preceded by `wait_until_still()` and followed by a
        re-check of which layer is in front.

        The settings page is not in the page graph, so calling `ui_goto_main()`
        while it is open raises `GamePageUnknownError`, and the scheduler turns
        that into `exit(1)` - the whole process, not just this task. Leaving the
        game there also breaks the next run, which cannot even get past
        `ui_ensure(page_main)`. Measured 10:43.

        Pages:
            in: any page of the flow
            out: page_main

        Args:
            rounds (int): How many panels to close at most.
            timeout (int, float): Seconds before giving up.

        Returns:
            bool: If the lobby was reached.
        """
        timeout = Timer(timeout).start()

        for _ in range(rounds):
            if timeout.reached():
                break
            self.device.screenshot()

            if self.appear(page_main.check_button, offset=30):
                return True
            if self.appear(REDEEM_DIALOG_TITLE, offset=30):
                self.wait_until_still(REDEEM_DIALOG_BODY, timeout=3)
                self.tap_point(*REDEEM_DIALOG_CLOSE)
                self.wait_until_disappear(REDEEM_DIALOG_TITLE, offset=30, timeout=5)
                continue
            if self.appear(REDEEM_TITLE_SETTING, offset=30):
                self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)
                self.tap_asset(ARENA_BTN_CLOSE)
                self.wait_until_disappear(REDEEM_TITLE_SETTING, offset=30, timeout=5)
                continue
            # 换页途中的一帧，哪个检测点都认不出来。等它停稳再看，别瞎点。
            self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)

        self.device.screenshot()
        if self.appear(page_main.check_button, offset=30):
            return True
        if self.appear(page_battle.check_button, offset=30):
            # 齿轮那条路偶尔只退回战斗页。
            self.ui_goto_main()
            return True

        # 退不出去也绝不在设置页上调 `ui_goto_main()`：那一下是整个进程 exit(1)。
        logger.warning('The coupon flow could not walk back to the lobby')
        return False
