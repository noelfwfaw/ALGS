"""兑换码 of 交错战线 (Cross Core).

Every day once. The fetch half is pure network, so a day with no new code never
touches the game: `ui_ensure()` runs after the ledger has filtered the list.

The path in the game (measured 2026-11-09):

    大厅 --右上三条横线--> 右侧菜单 --竖排齿轮--> 设置
    设置 --左侧最下面的「补给兑换」--> 兑换中心页
    兑换中心 --点输入框--> 游戏自绘的底部输入条（白底，右端「确定」）
    输入条 --确定--> 对勾变橙 --点对勾--> 居中 toast（约 1~2 秒后自己消失）

Three measured details decide how this file is written:

1. The toast is the only answer of the game - there is no dialog and no confirm
   button. 无效码 显示「兑换码错误」, and the toast disappears on its own, so the
   result has to be read from the frames right after the press. The page behind
   the toast is static (two screenshots of the page differ by 0.0), which is what
   `coupon_result()` compares against to know the toast is on screen instead of
   OCR-ing the 「请输入兑换码」 placeholder.
2. The input box does not open a system keyboard; the game draws its own bar at
   the bottom of the screen. `adb shell input text` writes into it directly.
   Its brightness is 253 while it is out and 43 while it is away (area
   `(0, 650, 1280, 710)`), so one threshold answers both directions.
3. The submit check mark is grey with an empty box (0 bright pixels) and orange
   once a code is in it (3166), so the template is both the guard and the click.

The official and the B-server codes are not separated on purpose: the wiki page
lists both in the same server, and the game answers 「兑换码错误」 for the one
that does not belong to this account - a wasted press, not a failure.

The ledger lives in `config/state/crosscore_codes.json`: a top-level json would
be picked up as a scheduler instance by `alas_instance()` (hard rule 118).
"""

from module.base.timer import Timer
from module.coupon.codes import (CHANNEL, EXPIRED, FAILED, INVALID, REDEEMED,
                                 USED, CodeBook)
from module.coupon.gamekee import GameKeeError, fetch_codes
from module.coupon.text import read_text
from module.crosscore.assets import (BOOT_BACK, COUPON_ENTRY, COUPON_INPUT,
                                     COUPON_KEYBOARD_OK, COUPON_MENU,
                                     COUPON_MENU_DISMISS, COUPON_SETTINGS,
                                     COUPON_SUBMIT, COUPON_TITLE)
from module.crosscore.crosscore_ui import CrosscoreUI, page_main
from module.crosscore.utils import image_diff
from module.logger import logger

# Wiki page: `/jchx/redemptionCode/119`. `119` is not a section number, it is
# the `id` of the 「区服」 module of `/v1/wiki/indexV2` (国服); the flat coupon
# endpoint answers an empty list for this wiki, the per-server one answers the
# codes of that server, 官服 and B服 included.
COUPON_ALIAS = 'jchx'
COUPON_PAGE = 119
COUPON_SERVER_ID = 119

COUPON_LEDGER = './config/state/crosscore_codes.json'

# The game's own input bar: a full-width white strip at the bottom. 253 while it
# is out, 43 while it is away (measured on the two 2026-11-09 screenshots).
KEYBOARD_AREA = (0, 650, 1280, 710)
KEYBOARD_LUMA = 200

# The input box itself: 0 bright pixels when empty (the placeholder is grey),
# 184 when a code is in it.
INPUT_AREA = (430, 390, 860, 425)
INPUT_BRIGHT = 100

# The toast. Its background darkens the page and it draws a golden frame, so the
# simplest signal is the difference to the still page captured before the press.
TOAST_AREA = (237, 307, 1037, 375)
# The text sits on one line near the bottom of the toast; the box is wider than
# 「兑换码错误」 because a success message may be longer.
TOAST_TEXT_AREA = (300, 346, 980, 374)
TOAST_DIFF = 5

# How many backspaces clear the longest code. Extra presses are harmless.
CLEAR_PRESSES = 24


def classify_result(text):
    """
    Turn the toast's one line into a ledger status.

    All five answers were measured on the real game (2026-11-09):

        兑换成功奖励已发送至您的邮箱          -> redeemed
        兑换码已经使用                        -> used
        不符合该兑换码所限制的渠道类型        -> channel (B服 code, 官服 account)
        兑换码错误                            -> invalid
        (nothing readable)                    -> failed

    The model garbles the middle of a long line sometimes (measured
    「兑换成功笑励已发送至忽的邮箱」), so only the fragment that carries the
    meaning is compared.

    Args:
        text (str): Han characters read from the toast, may be empty.

    Returns:
        str: A ledger status.
    """
    if not text:
        return FAILED
    if '不符合' in text or '渠道' in text:
        return CHANNEL
    if '过期' in text:
        return EXPIRED
    if '使用' in text:
        return USED
    if '成功' in text:
        return REDEEMED
    if '错误' in text or '无效' in text or '不存在' in text:
        return INVALID
    return FAILED


class CrosscoreRedeem(CrosscoreUI):
    """
    Send every coupon that is new, alive and not in the ledger yet.

    Pages:
        in: page_main
        out: page_main
    """

    # The raw line of the last toast, written into the ledger for later checks.
    coupon_said = ''

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Coupon codes', level=1)

        codes = self.coupon_fetch()
        if codes is None:
            self.config.task_delay(server_update=True)
            return

        book = CodeBook(COUPON_LEDGER)
        book.log_summary()
        todo = book.pending(codes)
        # `pending()` marks the codes that have expired on the way, save that.
        book.save()
        logger.info(f'Coupons alive: {len(codes)}, to try: {len(todo)}')
        if not todo:
            logger.info('Nothing new to redeem today')
            self.config.task_delay(server_update=True)
            return

        # The task ends on the coupon page only when a run crashed, and neither
        # that page nor the settings page behind it is in the page graph, so
        # `ui_ensure(page_main)` would raise `GamePageUnknownError` on them.
        # Walking the flow backwards first is a no-op when the lobby is already
        # in front, and it is the normal way out otherwise.
        self.coupon_exit()
        if not self.coupon_enter():
            logger.warning('Could not open the coupon page, try again tomorrow')
            self.coupon_exit()
            self.config.task_delay(server_update=True)
            return

        redeemed = 0
        for code in todo:
            # A timeout instead of a single look: the page fades between codes
            # and one transition frame matches nothing.
            if not self.wait_until_appear(COUPON_TITLE, offset=(20, 20), timeout=3):
                logger.warning('The coupon page is gone, stop here and retry tomorrow')
                break
            status = self.coupon_redeem(code)
            book.mark(code, status, self.coupon_said)
            # One save per code: a crash in the middle must not send a redeemed
            # code again tomorrow.
            book.save()
            if status == REDEEMED:
                redeemed += 1

        logger.info(f'Coupons redeemed: {redeemed}, tried: {len(todo)}')
        book.log_summary()
        self.coupon_exit()
        self.config.task_delay(server_update=True)

    def coupon_fetch(self):
        """
        Read the list, keeping a network failure inside this task.

        Returns:
            list[dict] or None: None when the site could not be read at all.
        """
        try:
            codes = fetch_codes(alias=COUPON_ALIAS, page=COUPON_PAGE,
                                server_id=COUPON_SERVER_ID)
        except GameKeeError as e:
            logger.warning(f'Coupon list is unavailable today: {e}')
            return None

        for code in codes:
            logger.attr('Coupon', '{:20} expires {}'.format(
                code['code'], code['end_at'].strftime('%Y-%m-%d')))
        return codes

    def coupon_enter(self, timeout=10):
        """
        大厅 -> 菜单 -> 设置 -> 补给兑换 -> 兑换中心.

        Pages:
            in: page_main
            out: the coupon page

        Args:
            timeout (int, float): Seconds per step.

        Returns:
            bool: If the coupon page is open.
        """
        # The menu may still be open from an interrupted run.
        if not self.coupon_menu_open():
            if not self.coupon_step(COUPON_MENU, COUPON_SETTINGS,
                                    'the lobby menu', timeout=timeout):
                return False
        if not self.coupon_step(COUPON_SETTINGS, COUPON_ENTRY,
                                'the settings gear', timeout=timeout):
            return False
        if not self.coupon_step(COUPON_ENTRY, COUPON_TITLE,
                                'the coupon entry', timeout=timeout):
            return False

        self.wait_until_still(COUPON_TITLE.area, timeout=3)
        return True

    def coupon_step(self, button, check, label, timeout=8, tries=2):
        """
        Press a button until it opens the next page.

        Every page of this game slides in, and a template often matches on the
        first frame of the slide while the click is still swallowed. So each
        attempt waits for the button to be still, presses it, then waits for the
        next page; a second attempt only happens when nothing moved.

        Args:
            button (Button): Button to press.
            check (Button): Detection point of the next page.
            label (str): How the log calls that button.
            timeout (int, float): Seconds to wait for the next page.
            tries (int): Attempts at most.

        Returns:
            bool: If the next page is on screen.
        """
        for _ in range(tries):
            if not self.wait_until_appear(button, offset=(20, 20), timeout=timeout):
                logger.warning(f'Cannot see {label}')
                continue
            self.wait_until_still(button.area, timeout=3)
            if self.appear(button, offset=(20, 20)):
                logger.info(f'Press {label}')
                self.device.click(button)
                if self.wait_until_appear(check, offset=(20, 20), timeout=timeout):
                    return True
            logger.info(f'{label} did not open the next page, press it again')

        logger.warning(f'{label} does not open the next page')
        return False

    def coupon_menu_open(self, timeout=1):
        """
        Whether the lobby's side menu is already open.

        Written as a loop instead of `wait_until_appear()` because "closed" is
        the normal answer and that helper warns on every timeout, which would
        put a warning into an otherwise clean daily log.

        Args:
            timeout (int, float): Seconds to look at the menu.

        Returns:
            bool: If the menu is up.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(COUPON_SETTINGS, offset=(20, 20)):
                return True
            if timeout.reached():
                return False

    def coupon_keyboard_luma(self):
        """
        Mean brightness of the strip the game's input bar occupies.

        Returns:
            float: 0~255.
        """
        image = self.device.image
        if image is None:
            return 0.0
        x1, y1, x2, y2 = KEYBOARD_AREA
        patch = image[y1:y2, x1:x2]
        if patch.size == 0:
            return 0.0
        return float(patch.sum(axis=2).mean() / 3)

    def coupon_keyboard(self, want=True, timeout=3):
        """
        Wait for the input bar to be out or away.

        Args:
            want (bool): True to wait for it, False for it to leave.
            timeout (int, float): Seconds.

        Returns:
            bool: If it is in the wanted state.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            luma = self.coupon_keyboard_luma()
            if (luma >= KEYBOARD_LUMA) == want:
                return True
            if timeout.reached():
                return False

    def coupon_keyboard_close(self):
        """
        Put the input bar away so the page is visible again.
        """
        if self.appear(COUPON_TITLE, offset=(20, 20)) and self.coupon_keyboard(want=True, timeout=2):
            self.device.click(COUPON_KEYBOARD_OK)
            self.coupon_keyboard(want=False)

    def coupon_input_bright(self):
        """
        Bright pixels of the input box: 0 when empty, 184 with a code.

        Returns:
            int: Pixel count.
        """
        image = self.device.image
        if image is None:
            return 0
        x1, y1, x2, y2 = INPUT_AREA
        patch = image[y1:y2, x1:x2]
        if patch.size == 0:
            return 0
        luma = patch.sum(axis=2) / 3
        return int((luma > 170).sum())

    def coupon_input_wait(self, want_text, timeout=3):
        """
        Wait until the input box holds a code or is empty.

        Args:
            want_text (bool): True to wait for a code, False for empty.
            timeout (int, float): Seconds.

        Returns:
            bool: If it reached the wanted state.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            bright = self.coupon_input_bright()
            if (bright > INPUT_BRIGHT) == want_text:
                return True
            if timeout.reached():
                return False

    def coupon_clear(self):
        """
        Delete whatever the input box holds.

        The box keeps the last code after a submission, so every code after the
        first one would otherwise be typed behind it.
        """
        self.device.adb_shell(['input', 'keyevent', '123'])  # alas-lint: allow - MOVE_END
        for _ in range(CLEAR_PRESSES):
            self.device.adb_shell(['input', 'keyevent', '67'])  # alas-lint: allow - DEL

    def coupon_toast_band(self):
        """
        Copy of the toast area of the current frame, used as the still page.

        Returns:
            np.ndarray or None.
        """
        image = self.device.image
        if image is None:
            return None
        x1, y1, x2, y2 = TOAST_AREA
        return image[y1:y2, x1:x2].copy()

    def coupon_redeem(self, code):
        """
        Type one code and read the toast.

        Pages:
            in: the coupon page
            out: the coupon page

        Args:
            code (dict): `{'code', 'content', 'end_at'}`.

        Returns:
            str: A ledger status.
        """
        text = code['code']
        logger.hr(f'Coupon {text}', level=2)
        # Clear the previous answer first: a code that never gets submitted
        # must not inherit the last toast in its ledger detail.
        self.coupon_said = ''

        # Every press is guarded by the page title: the coupon page is the only
        # place with this title, and it stays on screen while the bar is out.
        if self.appear(COUPON_TITLE, offset=(20, 20)):
            self.wait_until_still(COUPON_TITLE.area, timeout=3)
            self.device.click(COUPON_INPUT)
        else:
            logger.warning('The coupon page is not on screen, skip this code')
            return FAILED
        if not self.coupon_keyboard(want=True):
            logger.info('The input bar is still closed, press the box again')
            if self.appear(COUPON_TITLE, offset=(20, 20)):
                self.device.click(COUPON_INPUT)
            if not self.coupon_keyboard(want=True):
                logger.warning('The input bar does not open')
                return FAILED

        self.coupon_clear()
        if not self.coupon_input_wait(want_text=False):
            logger.warning('The input box still holds an old code, skip this one')
            self.coupon_keyboard_close()
            return FAILED

        # adb types into the game's own bar directly (measured 2026-11-09).
        self.device.adb_shell(['input', 'text', text])  # alas-lint: allow
        if not self.coupon_input_wait(want_text=True):
            logger.warning('The code does not land in the input box')
            self.coupon_keyboard_close()
            return FAILED

        # Put the bar away first, like the other coupon tasks do; the page
        # below it is unchanged.
        if self.appear(COUPON_TITLE, offset=(20, 20)) and self.coupon_keyboard(want=True):
            self.device.click(COUPON_KEYBOARD_OK)
        else:
            logger.warning('The input bar vanished before it could be closed')
            return FAILED
        if not self.coupon_keyboard(want=False):
            logger.warning('The input bar does not close')
            return FAILED

        # The check mark is the "a code is in the box" guard as well as the
        # button. Its grey and orange states have the same shape, so
        # `TM_CCOEFF_NORMED` matches both (measured: 0.99 on the empty page);
        # the enabled state is the golden paint inside it instead - 0 pixels
        # grey, 3465 orange.
        if self.wait_until_appear(COUPON_SUBMIT, offset=(20, 20), timeout=5) \
                and self.image_color_count(COUPON_SUBMIT, color=(255, 186, 50),
                                           threshold=30, count=500):
            still = self.coupon_toast_band()
            self.device.click(COUPON_SUBMIT)
        else:
            logger.warning('The submit button did not light up')
            return FAILED

        status = self.coupon_result(still)
        logger.info(f'Coupon {text}: {status}')
        return status

    def coupon_result(self, still, timeout=10):
        """
        Read the toast raised by the press and wait for it to leave.

        The toast disappears by itself after one or two seconds, so the loop
        starts right after the click. The page behind it is static, which makes
        "the toast is here" a difference against the frame captured before the
        press; OCR only runs on that frame, never on the page itself (the
        placeholder 「请输入兑换码」 is Chinese too).

        Args:
            still (np.ndarray): The toast area before the press.
            timeout (int, float): Seconds to wait for the answer.

        Returns:
            str: A ledger status.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            image = self.device.image
            if image is not None and still is not None:
                x1, y1, x2, y2 = TOAST_AREA
                current = image[y1:y2, x1:x2]
                if current.shape == still.shape and image_diff(current, still) > TOAST_DIFF:
                    said = read_text(image, TOAST_TEXT_AREA)
                    if said:
                        self.coupon_said = said
                        logger.info(f'The game said: {said}')
                        self.coupon_toast_gone(still)
                        return classify_result(said)

            if timeout.reached():
                logger.warning('The game does not answer the redeem press')
                return FAILED

    def coupon_toast_gone(self, still, timeout=5):
        """
        Wait until the toast disappears and the page is still again.

        Args:
            still (np.ndarray): The toast area before the press.
            timeout (int, float): Seconds.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            image = self.device.image
            if image is not None:
                x1, y1, x2, y2 = TOAST_AREA
                current = image[y1:y2, x1:x2]
                if current.shape == still.shape and image_diff(current, still) < 2:
                    return
            if timeout.reached():
                return

    def coupon_exit(self, rounds=8, timeout=60):
        """
        Walk back to the lobby from the coupon page.

        The settings page is not in the page graph, so `ui_goto_main()` while it
        is open raises `GamePageUnknownError`, which the scheduler turns into
        `exit(1)` - the whole process, not just this task. So the way out is
        the same arrow the game draws on every full page, and a cold restart is
        the fallback: the boot loop knows every screen on that path.

        `appear()` here carries no `interval`: the back arrow is present on both
        the coupon page and the settings page, and the cooldown of the first
        press made the second press invisible (measured 2026-11-09 - the loop
        burned all its rounds in 1.4 s and restarted the game).

        Pages:
            in: any page of the flow
            out: page_main

        Returns:
            bool: If the lobby was reached.
        """
        timeout = Timer(timeout).start()

        for _ in range(rounds):
            if timeout.reached():
                break
            self.device.screenshot()

            if self.ui_page_appear(page_main):
                return True
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.appear(COUPON_TITLE, offset=(20, 20)):
                # Leave the coupon page first; the settings page behind it has
                # its own back arrow.
                self.wait_until_still(COUPON_TITLE.area, timeout=3)
                if self.appear(BOOT_BACK, offset=(20, 20)):
                    logger.info('Leave the coupon page')
                    self.device.click(BOOT_BACK)
                    self.wait_until_disappear(COUPON_TITLE, offset=(20, 20), timeout=5)
                continue
            if self.appear(COUPON_SETTINGS, offset=(20, 20)):
                # The side menu is an overlay on the lobby. Its own icon is
                # covered by the panel (measured 2026-11-09), the system back
                # key is ignored, but a tap on the scene closes it.
                logger.info('Close the lobby menu')
                self.device.click(COUPON_MENU_DISMISS)
                self.wait_until_disappear(COUPON_SETTINGS, offset=(20, 20), timeout=5)
                continue
            if self.appear(BOOT_BACK, offset=(20, 20)):
                logger.info('Leave the settings page')
                self.device.click(BOOT_BACK)
                if self.wait_until_appear(page_main.check_button, offset=(20, 20), timeout=5):
                    return True
                continue
            # A transition frame matches nothing; wait for it to settle.
            self.wait_until_still(BOOT_BACK.area, timeout=3)

        self.device.screenshot()
        if self.ui_page_appear(page_main):
            return True

        logger.warning('The coupon flow could not walk back to the lobby, restart the game')
        self.device.app_stop()
        self.device.app_start()
        self.handle_app_boot()
        return True
