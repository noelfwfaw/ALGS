"""兑换码：从 GameKee 抓、在游戏里兑、把结果记在本机上。

每天一次。抓取是纯网络的，所以没有新码时这个任务一行都不会碰游戏 ——
`run()` 里的 `redeem_enter()` 在抓取之后才调用，没有待兑换的码就直接
排到明天。

**不按服务器过滤**（用户 2026-11-08）。GameKee 的 czn 列表把国服和全球服放在
一起发，国服那份是中文码，本机跑的是 STOVE 全球客户端
（`com.smilegate.chaoszero.stove.google`），兑不了。早先这里按"码里有没有中日韩
字符"跳过它们，用户要求改成照常尝试：兑不了就让游戏自己回答失败，不替用户
判断服务器。`adb shell input text` 只送得进 ASCII，中文码注定落不进输入框，
这种情况记 `failed` 结算，免得每天重试同一个码。

游戏里的路径（2026-11-08 用户录制的 9 页 spec，并口头修正了 2_1）：

    大厅 --右上 ☰--> 菜单面板 --右下齿轮--> 设置页
    设置页 --左侧「账号」标签--> 账号页 --「登錄優惠券」--> 兑换 webview
    兑换页 --点输入框--> 输入序號 --橙色「確認」--> 结果弹窗（成功 / 已使用）
    结果弹窗 --「確認」--> 兑换页（输入框里还留着刚才那个码）
    兑换 webview 右上 ✕ --> 账号页 --右上 ✕--> 菜单面板 --右上 ✕--> 大厅

这个客户端的兑换页是**网页**（底部有一条浏览器的前进/后退/刷新/主页栏），
不是游戏自绘的输入条，所以输入走 `input text`、清空走 MOVE_END + DEL。

三件实测出来的事决定了这里的写法：

**输入框不会自己清空**（用户 2026-11-08 特别提醒）。兑换成功后码还留在框里，
第二个码必须先把上一个删干净再输入，否则会提交一个拼接出来的不存在的码。

**结果弹窗是网页里的白色浮层**，它盖住了「確認」按钮和输入框。所以每个码
开始前先把上一个弹窗关掉（`redeem_dismiss_result()`），不能只看标题 ——
「獎勵序號」标题在弹窗打开时仍然可见（实测相似度 1.000），标题不能回答
"有没有弹窗"。

**设置页 / 账号页 / 兑换页都不在页面图里**，退不出去时不能调 `ui_goto_main()`：
那会抛 `GamePageUnknownError`，调度器把它变成整个进程 `exit(1)`。退出路径
按层关，最后一层认不出来才冷重启兜底。

流程里的每一步都可能被上一帧的动画吞掉（用户说"spec 可能有错，容错你来解决"），
所以进入和退出都写成有限次的状态循环：每帧先认"现在是哪一层"，再点下一层，
点完等下一层的判据出现；超时就下一轮再点，最多几轮。
"""

from module.base.timer import Timer
from module.chaoszero.assets import (REDEEM_ACCOUNT_TAB, REDEEM_CLOSE,
                                     REDEEM_CONFIRM, REDEEM_ENTRY, REDEEM_MENU,
                                     REDEEM_RESULT_DONE, REDEEM_RESULT_USED,
                                     REDEEM_SETTINGS, REDEEM_SETTINGS_CLOSE,
                                     REDEEM_SUBMIT, REDEEM_TITLE)
from module.chaoszero.chaoszero_ui import ChaoszeroUI
from module.chaoszero.page import page_main
from module.coupon.codes import (EXPIRED, FAILED, INVALID, REDEEMED, USED,
                                 CodeBook)
from module.coupon.gamekee import GameKeeError, fetch_codes
from module.coupon.text import read_text
from module.logger import logger

# 账本。放在 `config/state/` 而不是 `config/` 顶层：那里每个 json 都会被
# `alas_instance()` 当成一个调度器实例（硬约束 118）。
COUPON_LEDGER = './config/state/chaoszero_codes.json'

# GameKee 上这个游戏的 alias 和列表页尾号，取自
# https://www.gamekee.com/czn/redemptionCode/104 。
GAMEKEE_ALIAS = 'czn'
GAMEKEE_PAGE = 104

# 模板匹配的搜索窗口。兑换页里的元素位置固定，20 px 足够吸收模拟器的零点漂移，
# 又不会把下方同款橙色的「確認」弹窗键误认成提交键。
REDEEM_OFFSET = 20

# 兑换页的输入框。点它聚焦，`input text` 才有地方落。
REDEEM_INPUT_POINT = (900, 202)
# 输入框里那一行字：空框 0 个深色像素，有码约 1000 个（阈值取 200）。
REDEEM_INPUT_AREA = (185, 182, 1090, 222)
REDEEM_INPUT_LUMA = 100
REDEEM_INPUT_DARK = 200
# 清空输入框时按几次退格。最长的兑换码也没这么长，多按没有副作用。
REDEEM_CLEAR_PRESSES = 40
# 结果弹窗中间那一行提示。故意框宽一点：文案长短不一，居中位置跟着变。
# 实测这一条带（不是整块弹窗）OCR 最稳，再宽 cnocr 会被白色留白带偏。
REDEEM_RESULT_AREA = (420, 275, 900, 330)
# 兑换页里的空白处（说明文字右侧）。系统键盘挡住「確認」时点一下这里让它收起，
# 这个点离标题、按钮和说明文字都远，点了不会触发任何链接。
REDEEM_PAGE_BLANK = (1050, 500)
# 整屏。换页 / 键盘收放都是动画，做"现在是哪一层"的判断前先等它停。
REDEEM_PAGE_BODY = (0, 0, 1280, 720)


def classify_result(text):
    """
    Turn the one line of the result dialog into a ledger status.

    实测的两句话（2026-11-08 的 7、8 页截图）：

        已配發序號獎勵。        the game took the code
        各角色只能使用1次。      the code was spent before

    `read_text()` 只保留汉字，数字和标点会丢，所以「各角色只能使用1次。」
    里能拿来判的是「只能使用」或「使用次」，不是整句。OCR 偶尔还会掉字，
    因此一律判两三字的片段。

    Args:
        text (str): Han characters read from the dialog, may be empty.

    Returns:
        str: One of `REDEEMED` / `USED` / `EXPIRED` / `INVALID` / `FAILED`.
    """
    if not text:
        return FAILED
    if '只能使用' in text or '使用次' in text \
            or '已使用' in text or '使用过' in text or '使用過' in text:
        return USED
    if '配發' in text or '配发' in text \
            or '獎勵' in text or '奖励' in text or '成功' in text:
        return REDEEMED
    # cnocr 对这个字体不稳：实测「已配發序號獎勵」被读成「已配骏序唬励」。
    # 「配」加「勵/励/序/號」的组合只可能出现在成功文案里，认一半也够。
    if '配' in text and ('勵' in text or '励' in text or '序' in text
                         or '號' in text or '号' in text):
        return REDEEMED
    if '過期' in text or '过期' in text:
        return EXPIRED
    if '無效' in text or '无效' in text or '不存在' in text:
        return INVALID
    # 读不出来也照样记成已结算：同一个码每天重试只会得到同一句看不懂的话。
    return FAILED


class ChaoszeroRedeem(ChaoszeroUI):
    """
    Send every coupon that is new, alive and not in the ledger yet.

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

        if not self.redeem_enter():
            logger.warning('Could not open the coupon page, try again tomorrow')
            self.redeem_exit()
            self.config.task_delay(server_update=True)
            return

        redeemed = 0
        for code in todo:
            # 用带超时的等待而不是看一眼：换页 / 掉线的中间帧一个检测点都不匹配，
            # 单帧判断会把"正在动"当成"界面没了"，剩下的码白等一天。
            if not self.wait_until_appear(REDEEM_TITLE, offset=REDEEM_OFFSET, timeout=3):
                # 界面跑丢了（掉线、被弹窗顶掉）。剩下的码不进账本，明天还会试。
                logger.warning('The coupon page is gone, stop here and retry tomorrow')
                break

            status = self.redeem_one(code)
            if status is None:
                if not code['code'].isascii():
                    # `adb shell input text` 只送得进 ASCII，中文码永远落不进
                    # 输入框。这不是"流程断了"，记 failed 结算，继续下一条，
                    # 否则同一个码每天都会重试一次、白白占一天。
                    logger.warning(f'Coupon {code["code"]}: cannot be typed in, '
                                   f'mark as failed')
                    book.mark(code, FAILED,
                              'not typable: adb input text accepts ASCII only')
                    book.save()
                    continue
                # 流程断了、清不空、输入没落进框：这一条**不记账**，明天重来。
                # 记成 failed 会把它永久排除，那是"读不懂的回复"才该有的待遇。
                logger.warning(f'Coupon {code["code"]}: not settled, retry tomorrow')
                break

            book.mark(code, status, self.coupon_said)
            # 一条一条落盘：中途崩了也不会把已经兑过的码再兑一遍。
            book.save()
            if status == REDEEMED:
                redeemed += 1

        logger.info(f'Coupons redeemed: {redeemed}, tried: {len(todo)}')
        book.log_summary()
        self.redeem_exit()
        self.config.task_delay(server_update=True)

    def coupon_fetch(self):
        """
        Read the coupon list.

        Returns:
            list[dict] or None: None when the site could not be read at all.
        """
        try:
            codes = fetch_codes(alias=GAMEKEE_ALIAS, page=GAMEKEE_PAGE)
        except GameKeeError as e:
            # 站点挂了不是"游戏坏了"：记 warning、排明天，不重试整轮。
            logger.warning(f'Coupon list is unavailable today: {e}')
            return None

        for code in codes:
            logger.attr('Coupon', '{:20} expires {}'.format(
                code['code'], code['end_at'].strftime('%Y-%m-%d')))
        return codes

    def redeem_enter(self, timeout=10):
        """
        大厅 -> 菜单 -> 齿轮 -> 设置 -> 账号 -> 兑换页。

        Pages:
            in: page_main (or a layer of this flow left by a previous run)
            out: the coupon page

        Args:
            timeout (int, float): Seconds per step.

        Returns:
            bool: If the coupon page is open.
        """
        logger.hr('Open the coupon page', level=2)

        if not self.device.has_cached_image:
            self.device.screenshot()
        if self.appear(REDEEM_TITLE, offset=REDEEM_OFFSET):
            logger.info('The coupon page is already open')
            return True

        # 上一次跑到一半退出时可能停在设置页或 webview 里，这两种界面
        # `ui_quit_to_main()` 都不认识：它会一直点屏幕顶部直到超时。只有确实
        # 不在兑换流程里时才先走回大厅。
        if not self.redeem_inside_flow():
            self.ui_quit_to_main()

        # 每一轮先认"现在是哪一层"，再点出下一层；点完等下一层的判据出现。
        # 动画期间的点击会被吞掉，所以同一个动作允许在下一轮再点一次。
        # 实机（2026-11-08）在账号页点「登錄優惠券」就被刚切过来的转场吞过一次，
        # 5 轮不够把每个动作的重试都排进去，给到 8 轮。
        for _ in range(8):
            if self.appear(REDEEM_TITLE, offset=REDEEM_OFFSET):
                return True

            # 上一个码的结果弹窗可能还开着，它盖住输入框和提交键。
            if self.redeem_dismiss_result():
                continue

            if self.appear(REDEEM_ENTRY, offset=REDEEM_OFFSET):
                logger.info('Account page, press 登錄優惠券')
                self.device.click(REDEEM_ENTRY)
                # 兑换页是网页，第一次打开要走网络，比游戏内切页慢，给两倍时间。
                self.wait_until_appear(REDEEM_TITLE, offset=REDEEM_OFFSET,
                                       timeout=timeout * 2, settle=2)
                continue

            if self.appear(REDEEM_ACCOUNT_TAB, offset=REDEEM_OFFSET):
                logger.info('Settings page, press the account tab')
                self.device.click(REDEEM_ACCOUNT_TAB)
                self.wait_until_appear(REDEEM_ENTRY, offset=REDEEM_OFFSET,
                                       timeout=timeout, settle=2)
                continue

            if self.appear(REDEEM_SETTINGS, offset=REDEEM_OFFSET):
                logger.info('The lobby menu is open, press the gear')
                self.device.click(REDEEM_SETTINGS)
                self.wait_until_appear(REDEEM_ACCOUNT_TAB, offset=REDEEM_OFFSET,
                                       timeout=timeout, settle=2)
                continue

            if self.ui_page_appear(page_main, offset=30):
                logger.info('Lobby, open the menu')
                self.device.click(REDEEM_MENU)
                self.wait_until_appear(REDEEM_SETTINGS, offset=REDEEM_OFFSET,
                                       timeout=timeout, settle=2)
                continue

            # 换页动画的一帧：既不是兑换流程的某一层，也不是大厅。等它停稳
            # 再看，这一轮不点任何东西。
            self.wait_until_still(REDEEM_PAGE_BODY, timeout=2)

        logger.warning('Could not open the coupon page')
        return False

    def redeem_inside_flow(self):
        """
        Whether the game is already somewhere inside this flow.

        Returns:
            bool: If one of the layers of the coupon flow is on screen.
        """
        return (self.appear(REDEEM_TITLE, offset=REDEEM_OFFSET)
                or self.appear(REDEEM_ENTRY, offset=REDEEM_OFFSET)
                or self.appear(REDEEM_ACCOUNT_TAB, offset=REDEEM_OFFSET)
                or self.appear(REDEEM_SETTINGS, offset=REDEEM_OFFSET))

    def redeem_dismiss_result(self, timeout=5):
        """
        Close the result dialog if one is open.

        The two known answers have their own templates; any other answer shares
        the same orange 「確認」, so `REDEEM_CONFIRM` is the generic "a dialog is
        open" check. The title of the page stays visible behind the dialog
        (measured similarity 1.000), so it cannot be used for this.

        Args:
            timeout (int, float): Seconds to wait for the dialog to leave.

        Returns:
            bool: If a dialog was on screen (and was pressed away).
        """
        if self.appear(REDEEM_CONFIRM, offset=REDEEM_OFFSET):
            logger.info('A result dialog is open, press 確認')
            for _ in range(2):
                # The press is swallowed by the fade-in animation on the first
                # frames, so a second press is allowed - the wait below is what
                # proves the dialog is still there.
                self.device.click(REDEEM_CONFIRM)
                if self.wait_until_disappear(REDEEM_CONFIRM, offset=REDEEM_OFFSET,
                                             timeout=timeout, settle=2):
                    break
            return True

        return False

    def redeem_one(self, code):
        """
        输入一个码、提交、读回结果。

        Pages:
            in: the coupon page
            out: the coupon page

        Args:
            code (dict): `{'code', 'content', 'end_at'}`.

        Returns:
            str or None: A ledger status, or None when the step broke and the
            code should be tried again tomorrow (not written to the ledger).
        """
        text = code['code']
        logger.hr(f'Coupon {text}', level=2)
        # 清掉上一条的原话：这一条要是根本没能提交，账本的 `detail` 会拿到
        # 上一条的「已配發」，把失败写成像成功了。
        self.coupon_said = ''

        # 上一条的结果弹窗盖着输入框，先关掉。
        self.redeem_dismiss_result()

        # 等页面静止再点：弹窗关闭的动画会吞掉紧接着的这一次点击。
        self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)
        self.tap_point(*REDEEM_INPUT_POINT, name='CHAOSZERO_REDEEM_INPUT')

        # 游戏不会自己清掉上一个码，不清就会两个码拼在一起。
        self.coupon_clear()
        if not self.coupon_input_wait(want_text=False, timeout=3):
            logger.info('The old code is still in the box, clear it again')
            self.coupon_clear()
            if not self.coupon_input_wait(want_text=False, timeout=3):
                logger.warning('The input box cannot be cleared, stop and retry tomorrow')
                return None

        self.device.adb_shell(['input', 'text', text])  # alas-lint: allow - typing ASCII into the focused web input
        if not self.coupon_input_wait(want_text=True, timeout=3):
            # 点输入框那一下可能被吞了，字没落进去。重新聚焦、清干净再送一次。
            logger.info('The code did not land in the box, focus it and send again')
            self.tap_point(*REDEEM_INPUT_POINT, name='CHAOSZERO_REDEEM_INPUT')
            self.coupon_clear()
            self.coupon_input_wait(want_text=False, timeout=2)
            self.device.adb_shell(['input', 'text', text])  # alas-lint: allow - retry of the same ASCII text
            if not self.coupon_input_wait(want_text=True, timeout=3):
                logger.warning('The code does not land in the input box, stop and retry tomorrow')
                return None

        if not self.redeem_submit():
            logger.warning('The 確認 button is not on the page, stop and retry tomorrow')
            return None

        status = self.redeem_result(timeout=12)
        if status is None:
            # 提交那一下可能落在键盘收起的动画上被吞了，重按一次。
            logger.info('No answer to the first press, press 確認 again')
            if self.redeem_submit():
                status = self.redeem_result(timeout=12)
        if status is None:
            logger.warning('The coupon page does not answer, stop and retry tomorrow')
            return None

        logger.info(f'Coupon {text}: {status}')
        return status

    def coupon_clear(self):
        """
        Delete whatever the input box holds.

        MOVE_END first: the caret may sit in the middle after a click, and DEL
        then removes the character behind it while the head of the old code
        stays.
        """
        self.device.adb_shell(['input', 'keyevent', '123'])  # alas-lint: allow - MOVE_END
        for _ in range(REDEEM_CLEAR_PRESSES):
            self.device.adb_shell(['input', 'keyevent', '67'])  # alas-lint: allow - DEL

    def coupon_input_wait(self, want_text, timeout=3):
        """
        Wait until the input box holds text or is empty.

        Args:
            want_text (bool): True to wait for a code in it, False for empty.
            timeout (int, float): Seconds.

        Returns:
            bool: If it reached the wanted state.
        """
        for _ in self.loop(timeout=timeout):
            dark = self.coupon_input_dark()
            if (dark > REDEEM_INPUT_DARK) == want_text:
                return True
        return False

    def coupon_input_dark(self):
        """
        Count the dark pixels of the input box, which is how "it holds a code"
        is answered: an empty box has none, a filled one about a thousand.
        The placeholder is light grey and the focus ring is yellow, so neither
        of them reaches the threshold.

        Returns:
            int: Pixel count.
        """
        image = self.device.image
        if image is None:
            return 0
        x1, y1, x2, y2 = REDEEM_INPUT_AREA
        patch = image[y1:y2, x1:x2]
        if patch.size == 0:
            return 0
        luma = patch.sum(axis=2) / 3
        return int((luma < REDEEM_INPUT_LUMA).sum())

    def redeem_submit(self):
        """
        Press the orange 「確認」 that submits the code.

        The on-screen keyboard occasionally pushes the page around, so when the
        button is not where it usually is, the page blank is pressed once to
        blur the input and put the layout back before looking again.

        Returns:
            bool: If the button was pressed.
        """
        if self.appear(REDEEM_SUBMIT, offset=REDEEM_OFFSET):
            self.device.click(REDEEM_SUBMIT)
            return True

        # The blank spot is inside the coupon page and off every control; the
        # caller has already checked the page is open.
        self.tap_point(*REDEEM_PAGE_BLANK, name='CHAOSZERO_REDEEM_BLANK')
        if self.wait_until_appear(REDEEM_SUBMIT, offset=REDEEM_OFFSET, timeout=3):
            self.device.click(REDEEM_SUBMIT)
            return True

        return False

    def redeem_result(self, timeout=12):
        """
        Read the result dialog and dismiss it.

        Pages:
            in: the coupon page with a result on top
            out: the coupon page

        Args:
            timeout (int, float): Seconds to wait for the answer.

        Returns:
            str or None: A ledger status, or None if no dialog showed up.
        """
        for _ in self.loop(timeout=timeout):
            if self.appear(REDEEM_CONFIRM, offset=REDEEM_OFFSET):
                if self.appear(REDEEM_RESULT_DONE, offset=REDEEM_OFFSET):
                    said = '已配發序號獎勵。'
                    status = REDEEMED
                elif self.appear(REDEEM_RESULT_USED, offset=REDEEM_OFFSET):
                    said = '各角色只能使用1次。'
                    status = USED
                else:
                    said = read_text(self.device.image, REDEEM_RESULT_AREA,
                                     letter=(0, 0, 0), threshold=170)
                    status = classify_result(said)

                self.coupon_said = said
                logger.info(f'The game said: {said or "(nothing readable)"}')
                self.redeem_dismiss_result()
                return status

        return None

    def redeem_exit(self, rounds=5, timeout=40):
        """
        从兑换流程退回到大厅。

        按层关：webview 的 ✕ -> 设置页/账号页的 ✕ -> 菜单面板的 ✕。
        入口页不在页面图里，所以**绝不**调 `ui_goto_main()`：那会抛
        `GamePageUnknownError`，调度器把它变成整个进程 exit(1)。

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

            if self.ui_page_appear(page_main, offset=30):
                logger.info('Back at page_main')
                return True

            # 结果弹窗在最上层，先关掉它才知道下面是什么。
            if self.redeem_dismiss_result():
                continue

            # webview 的 ✕ 和设置页的 ✕ 位置几乎重叠，所以必须先判兑换页。
            if self.appear(REDEEM_TITLE, offset=REDEEM_OFFSET):
                self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)
                self.device.click(REDEEM_CLOSE)
                self.wait_until_disappear(REDEEM_TITLE, offset=REDEEM_OFFSET, timeout=5)
                continue

            if self.appear(REDEEM_SETTINGS_CLOSE, offset=REDEEM_OFFSET):
                self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)
                self.device.click(REDEEM_SETTINGS_CLOSE)
                self.wait_until_disappear(REDEEM_SETTINGS_CLOSE, offset=REDEEM_OFFSET, timeout=5)
                continue

            if self.appear(REDEEM_SETTINGS, offset=REDEEM_OFFSET):
                # 菜单打开后，原来那颗 ☰ 变成了同一个位置上的 ✕。模板匹配不上，
                # 但这个点就是关掉它的地方。
                self.wait_until_still(REDEEM_PAGE_BODY, timeout=3)
                self.device.click(REDEEM_MENU)
                self.wait_until_disappear(REDEEM_SETTINGS, offset=REDEEM_OFFSET, timeout=5)
                continue

            # 换页 / 淡出途中的一帧，哪个检测点都认不出来。等它停稳，别瞎点。
            self.wait_until_still(REDEEM_PAGE_BODY, timeout=2)

        self.device.screenshot()
        if self.ui_page_appear(page_main, offset=30):
            return True

        # 退不出去也绝不在这些页上调 `ui_goto_main()`，但把游戏留在这里同样
        # 不行：下一个任务连 `ui_ensure(page_main)` 都过不去。冷重启兜底 ——
        # boot 循环认识标题屏和它路上的一切弹窗，落回大厅是确定的。
        logger.warning('The coupon flow could not walk back to the lobby, restart the game')
        self.device.app_stop()
        self.device.app_start()
        # Fresh screenshot first: the cached one is the screen we failed to leave.
        self.handle_app_boot(skip_first_screenshot=False)
        return True
