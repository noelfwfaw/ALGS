"""兑换码：从 GameKee 抓、在游戏里兑、把结果记在本机上。

每天一次。抓取是纯网络的，所以没有新码时这个任务一行都不会碰游戏 ——
`run()` 里的 `ui_ensure()` 在抓取和过滤之后才调用，没有待兑换的码就直接排到
明天。

游戏里的路径（2026-10-29 实测）：

    大厅 --右上角 2x2 方格--> 「其他」菜单 --第二行「添加优惠券」--> 兑换网页
    兑换网页（游戏内嵌的 webview，昵称已经自动填好）--点序列号输入框--> 直接打字
    输入框 --「兑换」--> 系统 alert（「网址为…的网页显示：」+ 文案 + 「确定」）
    alert --「确定」--> 回到网页，输入框自己清空
    网页 --右上角 X--> 「其他」菜单 --左上角返回箭头--> 大厅

三件这个游戏和失落之剑不一样、必须按这里的事实来写的事：

**没有任何键盘**。这个网页是内嵌的，点输入框只出现一个光标，不出输入条也不出
系统键盘，`input text` 直接写进框里。所以不需要"等输入条弹出"，只需要"打完了
看一眼框里有没有字"。

**结果不是游戏画的面板，是 Android 的 alert**。「确定」按钮的位置跟着文案行数
上下浮动（一行时 `y≈458`，两行时 `y≈460`），所以它只能靠模板找，不能写死坐标。
文案是黑字白底，OCR 要传 `letter=(0,0,0)` —— 失落之剑的 `read_text()` 默认找白色
字，在这里会读出噪声。

**网页是固定版式，但要先滚到底**。「兑换」按钮在首屏之外，滚到底之后布局就固定
了（输入框 `(640,254)`、按钮 `(641,524)`），而**这两块是跟着滚动一起动的**，所以
输入框不写绝对坐标，用相对按钮的 `INPUT_OFFSET`（硬约束 123）。滚动写成
"滑一下 → 看一眼 → 没有就再滑"的循环（`coupon_scroll()`）：网页要联网加载，标题
模板出现那一帧往往只有昵称那一行，固定滑两次会滑在空白页上（实测第一次就栽在
`The redeem button is not on the coupon page`）。

账本在 `config/state/browndust_codes.json`（不能放 `config/` 顶层，硬约束 118）。
往输入框里打字那一段（清空、判有没有字）在 `coupon_input.py`。
"""

import cv2

from module.base.timer import Timer
from module.base.utils import crop
from module.browndust.assets import (COUPON_ALERT_OK, COUPON_ENTRY,
                                     COUPON_MENU_GRID, COUPON_SUBMIT,
                                     COUPON_WEB_CLOSE, COUPON_WEB_TITLE)
from module.browndust.browndust_ui import BrowndustUI, page_main
from module.browndust.coupon_input import CouponInput
from module.browndust.coupon_page import MENU_BACK, WEB_BODY, CouponPage
from module.coupon.codes import (EXPIRED, FAILED, INVALID, REDEEMED, USED,
                                 CodeBook)
from module.coupon.gamekee import GameKeeError, fetch_codes
from module.coupon.text import read_text
from module.logger import logger

# 账本。放在 `config/state/` 而不是 `config/` 顶层：那里每个 json 都会被
# `alas_instance()` 当成一个调度器实例（硬约束 118）。
COUPON_LEDGER = './config/state/browndust_codes.json'
# GameKee 上这个游戏的别名与维基页码（用户给的链接 .../zsca2/redemptionCode/12）。
GAMEKEE_ALIAS = 'zsca2'
GAMEKEE_PAGE = 12

# 输入框中心相对「兑换」按钮中心的偏移。两者是同一张页面上的两块，滚动时一起
# 移动，所以这个偏移是常量，而它们各自的绝对位置不是 —— 页面停在哪个滚动位置
# 都不影响：按钮在哪，输入框就在它上方 270 像素（实测 2026-10-29）。
INPUT_OFFSET = (-1, -270)
# alert 的两行文案。行距固定，弹窗只往上长，所以这两条线的位置不随行数变。
ALERT_LINE1 = (330, 338, 960, 370)
ALERT_LINE2 = (330, 370, 960, 402)
# 网页要联网加载，首次打开实测 3~5 秒，给足余量。
WEB_LOAD_TIMEOUT = 30


def classify_result(text):
    """
    Turn the alert's text into a ledger status.

    The three answers measured on 2026-10-29:

        无效的序列号 / 请重新确认        -> the server does not know the code
        本序列号已使用完毕               -> already spent
        序列号输入完毕! / 请登录游戏确认奖励 -> accepted

    The OCR drops punctuation and is not trusted with a whole sentence, so the
    test is on short fragments. `使用完毕` has to be checked before `输入完毕`:
    both end in 完毕 and the two answers would otherwise be confused.

    Args:
        text (str): Han characters read from the alert, may be empty.

    Returns:
        str: One of `REDEEMED` / `USED` / `INVALID` / `EXPIRED` / `FAILED`.
    """
    if not text:
        return FAILED
    if '已使用' in text or '使用完毕' in text:
        return USED
    if '输入完毕' in text or '登录游戏' in text:
        return REDEEMED
    if '无效' in text or '重新确认' in text:
        return INVALID
    if '过期' in text:
        return EXPIRED
    # 读出来了但不认识：记下来，别再试第二次。
    return FAILED


class BrowndustRedeem(BrowndustUI, CouponPage, CouponInput):
    """
    Send every coupon that is new, alive and not in the ledger yet.

    Two parts live next door, because they are about something else than
    redeeming: `CouponPage` walks in and out of the webview (no page graph
    reaches it), `CouponInput` types into the serial number field.

    Pages:
        in: page_main
        out: page_main
    """

    # 最近一次 alert 读到的原话，写进账本方便事后对账。每一条开头清零，
    # 否则没提交成功的那条会继承上一条的证据（硬约束 116）。
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

        if not self.coupon_open():
            logger.warning('Could not open the coupon page, try again tomorrow')
            self.coupon_exit()
            self.config.task_delay(server_update=True)
            return

        redeemed = 0
        for code in todo:
            status = self.coupon_redeem(code)
            if status is None:
                # 没交上去（字没进框、alert 没来）。不进账本，明天还会试。
                logger.warning('Coupon {} was not submitted, retry tomorrow'.format(code['code']))
                continue
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
            codes = fetch_codes(alias=GAMEKEE_ALIAS, page=GAMEKEE_PAGE)
        except GameKeeError as e:
            # Not an exception for the scheduler: the list being down is not a
            # broken game, and the next run is tomorrow anyway.
            logger.warning(f'Coupon list is unavailable today: {e}')
            return None

        for code in codes:
            logger.attr('Coupon', '{:20} expires {}'.format(
                code['code'], code['end_at'].strftime('%Y-%m-%d')))
        return codes

    def coupon_open(self, timeout=15):
        """
        大厅 -> 「其他」菜单 -> 兑换网页，并把它滚到底。

        每一步都是"点一下，然后等下一个界面出现"：网页是联网加载的，慢起来
        好几秒，看一帧就下结论会误判成没打开。

        Pages:
            in: page_main
            out: the coupon page，滚到底

        Args:
            timeout (int, float): Seconds to wait for each screen.

        Returns:
            bool: If the page is open and scrolled to the redeem button.
        """
        # 上一次跑到一半退出，可能停在网页或菜单上 —— 先退回来再 ui_ensure。
        self.coupon_reset()
        self.ui_ensure(page_main)

        # 菜单偶尔已经开着（上一次点完没进网页），这时再点一次是关掉它。
        if not self.coupon_menu_open():
            self.coupon_tap(COUPON_MENU_GRID)
            if not self.wait_until_appear(COUPON_ENTRY, offset=30, timeout=5):
                logger.info('The 其他 menu did not open, press it again')
                self.coupon_tap(COUPON_MENU_GRID)
                if not self.wait_until_appear(COUPON_ENTRY, offset=30, timeout=5):
                    logger.warning('The 其他 menu does not open')
                    return False

        self.wait_until_still(COUPON_ENTRY.area, timeout=2)
        self.coupon_tap(COUPON_ENTRY)
        if not self.wait_until_appear(COUPON_WEB_TITLE, offset=30, timeout=WEB_LOAD_TIMEOUT):
            logger.info('The coupon page did not load, press the entry again')
            self.coupon_tap(COUPON_ENTRY)
            if not self.wait_until_appear(COUPON_WEB_TITLE, offset=30, timeout=WEB_LOAD_TIMEOUT):
                logger.warning('The coupon page does not open')
                return False

        return self.coupon_scroll()

    def coupon_menu_open(self, timeout=1):
        """
        Whether the 「其他」 menu is already open.

        Written as a loop instead of `wait_until_appear()` on purpose: "closed"
        is the normal answer, and that helper logs a warning every time it hits
        its timeout. A daily warning in an otherwise clean log hides the ones
        that matter.

        Args:
            timeout (int, float): Seconds to look at the menu.

        Returns:
            bool: If the menu is up.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(COUPON_ENTRY, offset=30):
                return True
            if timeout.reached():
                return False

    def coupon_redeem(self, code):
        """
        Type one code into the page and read the answer.

        Pages:
            in: the coupon page
            out: the coupon page

        Args:
            code (dict): `{'code', 'content', 'end_at'}`.

        Returns:
            str or None: A ledger status, or None when nothing was submitted
                and the code should be tried again tomorrow.
        """
        text = code['code']
        logger.hr(f'Coupon {text}', level=2)
        # 清零：这一条要是根本没交上去，账本的 `detail` 不能拿到上一条的原话。
        self.coupon_said = ''

        # 上一个码的「确定」刚点完，网页还在恢复，等一下再定位。
        self.wait_until_still(WEB_BODY, timeout=3)
        self.coupon_page_ready()
        submit = self.coupon_locate(COUPON_SUBMIT)
        if submit is None:
            logger.warning('The redeem button is not on the coupon page')
            return None
        box = (submit[0] + INPUT_OFFSET[0], submit[1] + INPUT_OFFSET[1])

        self.coupon_tap(box)
        # 网页兑换完会自己清空输入框（成功和失败都清），这里只是保险。
        self.coupon_clear()
        if not self.coupon_input_wait(want_text=False, box=box):
            logger.warning('The input box still holds an old code, skip this one')
            return None

        # 这个网页没有键盘，`input text` 直接写进框里。
        self.device.adb_shell(['input', 'text', text.replace(' ', '%s')])  # alas-lint: allow
        if not self.coupon_input_wait(want_text=True, box=box):
            logger.warning('The code does not land in the input box')
            return None

        self.coupon_tap(submit)
        said = self.coupon_answer()
        if said is None:
            return None

        status = classify_result(said)
        logger.info(f'Coupon {text}: {status}')
        return status

    def coupon_scroll(self, timeout=20):
        """
        Scroll the coupon page down until the redeem button is on screen.

        The page opens at the top, where only the nickname and the top half of
        the serial field are visible; the button and the notes are below the
        fold.

        Two things were measured on 2026-10-29, and both are why this looks
        instead of counting swipes:

        - **the title arrives long before the form does.** `COUPON_WEB_TITLE`
          is up about 0.2 s after the press, and at that moment the page has
          nothing but the nickname row - no field, no button. The first version
          treated "title is up" as "page is ready" and swiped twice on a blank
          page, then reported `The redeem button is not on the coupon page`;
        - **while the webview repaints during a swipe it goes flat white for a
          frame or two**, and on a flat frame `cv2.matchTemplate` reports 1.000
          at `(0, 0)` - the correlation of a constant patch is undefined and
          OpenCV answers "perfect". That frame made the first version of this
          task believe the button was at the top-left corner and tap `(40,
          -246)`; the same trap sits behind `appear()`. Hence
          `coupon_page_blank()` and the guard inside `coupon_locate()`.

        Pages:
            in: the coupon page
            out: the coupon page, with the redeem button on screen

        Args:
            timeout (int, float): Seconds to keep trying.

        Returns:
            bool: If the redeem button is on screen.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if not self.coupon_page_ready():
                # 网页正在重绘（一整帧纯白）：这时候既不能判断也不能点。
                continue
            if self.coupon_locate(COUPON_SUBMIT) is not None:
                return True
            if timeout.reached():
                break
            self.device.swipe((640, 600), (640, 300), 0.3)
            self.wait_until_still(WEB_BODY, timeout=2)

        logger.warning('The redeem button never showed up on the coupon page')
        return False

    def coupon_page_ready(self, timeout=3):
        """
        Whether the webview has finished painting this frame.

        A swipe makes the page flat white for a frame or two while it redraws,
        and a flat frame is not something to make a decision on - see
        `coupon_scroll()` for what it did to the first version.

        Args:
            timeout (int, float): Seconds to wait for a painted frame.

        Returns:
            bool: True once a non-flat frame is on screen.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if not self.coupon_page_blank():
                return True
            if timeout.reached():
                return False

        return False

    def coupon_page_blank(self):
        """
        Whether the current frame is a single flat colour.

        Returns:
            bool: True if the page body has almost no contrast.
        """
        image = self.device.image
        if image is None:
            return True
        x1, y1, x2, y2 = WEB_BODY
        patch = image[y1:y2, x1:x2]
        return bool(patch.std() < 12)

    def coupon_locate(self, button, similarity=0.9):
        """
        Where a button is right now, in the current frame.

        `appear()` only answers yes or no, and the coupon page moves: the same
        button sits at a different `y` depending on how far the page has been
        scrolled. Its offset from the input field stays the same, so one
        location is enough to place both.

        `Button.match()` cannot be used for this - it passes the template and
        the screenshot to `cv2.matchTemplate()` the wrong way round (upstream
        does too) and only works when both are the same size.

        `button.image` is used as it comes: `ensure_template()` has already
        cropped the PNG to `button.area`, so cropping it a second time with the
        absolute area leaves an all-black patch outside the image. A constant
        template scores 1.000 at `(0, 0)` on **every** frame (the correlation of
        a constant is undefined, OpenCV answers "perfect"), which is what made
        this method report the button at the top-left corner and tap `(40,
        -246)` twice on 2026-10-29. Same trap as hard rule 105, second way in.

        Args:
            button (Button): Template to look for.
            similarity (float): Below this the button is not there.

        Returns:
            tuple or None: Centre (x, y) of the match, None when it is not there.
        """
        self.device.screenshot()
        button.ensure_template()
        template = button.image
        if template is None or template.std() < 12:
            # 一条纯黑的模板对任何画面都是 1.000，先把它挡在门外。
            logger.warning(f'{button.name} has a flat template, fix the .png')
            return None

        height, width = template.shape[0], template.shape[1]
        result = cv2.matchTemplate(self.device.image, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < similarity:
            return None

        x, y = location
        patch = crop(self.device.image, (x, y, x + width, y + height))
        if patch.std() < 12:
            # 截图那一块是纯色（网页重绘时的整帧白），这里同样没有可比的东西。
            return None

        return (x + width // 2, y + height // 2)

    def coupon_answer(self, timeout=10):
        """
        Wait for the system alert, read it and press 确定.

        The alert is Android's own, not the game's: a white box titled
        「网址为"https://redeem.bd2.pmang.cloud"的网页显示：」 with the message of
        the server and a single 确定. Its height follows the number of lines,
        so the button is found by its own text and never by a fixed point.

        Pages:
            in: the coupon page with an alert on top
            out: the coupon page

        Args:
            timeout (int, float): Seconds to wait for the answer.

        Returns:
            str or None: The text that was read, or None when no alert came.
        """
        timeout = Timer(timeout).start()
        for _ in self.loop():
            # 用 `coupon_locate()` 而不是 `appear()`：后者在纯白帧上会对任何模板
            # 说"看见"（见 `coupon_scroll()`），而这个弹窗后面正是一张会滚动的网页。
            ok = self.coupon_locate(COUPON_ALERT_OK)
            if ok is not None:
                said = self.coupon_read_alert()
                self.coupon_said = said
                logger.info(f'The game said: {said or "(nothing readable)"}')
                self.coupon_tap(ok)
                self.wait_until_disappear(COUPON_ALERT_OK, offset=30, timeout=5)
                return said

            if timeout.reached():
                logger.warning('The game does not answer the redeem press')
                return None

        return None

    def coupon_read_alert(self):
        """
        OCR the alert's message, line by line.

        One line per call: the model is asked to read single lines and returns
        noise on a two-line crop (measured - 「无效的序列号/请重新确认」 came back
        as 「螭」 when both lines were fed at once). The text is black on white,
        hence `letter=(0, 0, 0)`; the default looks for white letters.

        Returns:
            str: Both lines joined, Han characters only.
        """
        lines = [
            read_text(self.device.image, ALERT_LINE1, letter=(0, 0, 0)),
            read_text(self.device.image, ALERT_LINE2, letter=(0, 0, 0)),
        ]
        return ''.join(lines)

