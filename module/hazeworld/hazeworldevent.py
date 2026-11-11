"""苍雾限时活动「艾吉斯未解之迷」清体力。

Built from the page-card spec by dev_tools/spec_build.py（串联链模式）.

Chain:
    9 presses in card order, one loop for the whole tutorial.
    0 resident keys checked before every frame of the chain.

前提：关卡必须已经通关（画面上显示 CLEAR）。链条里只有「扫荡」，
没有「作战准备」，脚本不负责开荒；没通关就启用会停在选关页。

本地补丁（重新生成后要重打，2026-11-11 10:31 真机翻车后修）：
    E_5_2 是左上角「返回主页面」键，在活动选关 / 详情 / 扫荡弹窗 / 结算
    四页模板得分全是 1.00。把它留在引导链里，点完「开始扫荡」0.6 秒后结算
    动画还没出来，链条就抢先连点主页键，触发 GameTooManyClickError 重启，
    「扫荡结算」的确认键 E_7_1 一次都没点到。
    现在：E_5_2 移出链条；「开始扫荡」后由 `wait_sweep_result()` 正面等
    E_7_1 出现 → 点确认 → 等弹窗消失 → 才按卡片 5-2 点一次主页键收工。
    10:45 真机补充：MAX 会按体力自动把次数拉满，扫到「连一把都打不了」
    为止，所以「体力不够」是清完体力的**正常终态**，不是暂时不足。
    此时（右上 35/260、单场 42）弹窗把「扣除后剩余」标红而「开始扫荡」
    仍是橙色。`sweep_stamina_short()` 认这行红字，不点开始扫荡、不空等
    90 秒结算，直接收工按 server_update 排到次日；不要短延迟重试。
    2026-11-11 真机补充：联合讨伐期间「今日已消耗体力（300/300）」白卡
    会顶掉扫荡面板，是模态（背后的按钮点不动）。`_interrupt()` 每帧先调
    UI 基类的 `handle_joint_raid()` 取消它；取消后面板不会自动回来，要再按
    一次「扫荡」，所以调用方要清掉 stubborn。结算等待与收工同样拦截。
    Regenerate with dev_tools/spec_build.py; edit the cards, not this file.
"""

import numpy as np

from module.hazeworld.assets import (CORE_RAID_POPUP, E_1_1, E_2_1, E_3_1,
                                     E_4_1, E_5_1, E_5_2, E_6_1, E_6_2,
                                     E_7_1)
from module.base.timer import Timer
from module.hazeworld.hazeworld_ui import HazeworldUI
from module.logger import logger


# 允许按钮偏离框选位置多少像素。引导气泡的位置会变，所以不能按固定坐标点；
# 但开得越大越慢：64 个模板全屏扫一遍要 1 秒，外扩 60 像素只要 50 毫秒。
CHAIN_OFFSET = 60

# 扫荡弹窗里「当前体力 ≫ 扣除后剩余」那一行的右侧数字。
# 体力够时是白/黄字；不够时游戏把它标红（10:45 真机：右上 35/260、单场 42）。
# 归一化 1280x720 实测：不足帧该区域红色像素 0.131，
# 正常体力帧与其余 6 张活动帧都 <=0.004，阈值 0.05 有 26 倍余量。
SWEEP_STAMINA_AREA = (740, 410, 790, 445)
SWEEP_STAMINA_RED = 0.05

# 需要往里打字的按钮：{Button: 内容}。其余按钮都只点一下。
# `input text` 只认 ASCII，所以内容只能是英文和数字。
TEXT_INPUT = {
}

# 按卡片顺序。顺序就是优先级：两个按钮同时出现时，点上面的那个。
# E_5_2（返回主页面键）故意不进链条：它在活动的四个子页上都常驻，
# 会在扫荡结算动画还没出来时抢帧连点。它只在结算确认之后被点一次，
# 见 `confirm_sweep_result()`。
GUIDE_CHAIN = (
    E_1_1,
    E_2_1,
    E_3_1,
    E_4_1,
    E_6_1,
    E_6_2,
    E_7_1,
    E_5_1,
)


class Hazeworldevent(HazeworldUI):
    """限时活动「艾吉斯未解之迷」：扫荡已通关关卡，不负责开荒."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 常驻键的冷却表，key 是 button.name
        self._cool = {}

    def run(self):
        """
        Pages:
            in: any
            out: page_main
        """
        logger.hr('苍雾活动·艾吉斯未解之迷（清体力）', level=1)
        self.guide_chain()
        # MAX 会自己把次数拉到体力用尽，所以不管这一轮有没有真的扫成，
        # 体力都已经清干净了。正常排到次日，不要短延迟轮询。
        self.config.task_delay(server_update=True)

    def _interrupt(self):
        """
        每帧最先处理的全局弹窗：联合讨伐提醒。

        它顶掉的是扫荡面板，背后的按钮看着还在但点不动。取消之后面板
        **不会**自动回来，要再按一次「扫荡」，所以 `guide_chain()` 里
        命中这一支时要把 stubborn 清掉，否则 `E_5_1` 会被记成「点了两次
        都不消失」而永远跳过。
        """
        return self.handle_joint_raid()

    def sweep_stamina_short(self):
        """
        Whether the sweep dialog says there is not enough stamina for one run.

        The right-hand number of the 「当前体力 ≫ 扣除后剩余」 row is white or
        yellow when the sweep is affordable, and the game paints it red when
        it is not. Reading that colour is steadier than OCR-ing two numbers
        and comparing them, and it does not care how many runs MAX picked.
        MAX already spends stamina down to the last affordable run, so a red
        number means "stamina cleared", not "wait for it to refill".
        `astype(int)` is required: subtracting uint8 channels wraps around.

        Returns:
            bool:
        """
        image = self.image_crop(SWEEP_STAMINA_AREA).astype(int)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        red = (r > 140) & (r - g > 60) & (r - b > 60) & (g < 150)
        return float(np.count_nonzero(red)) / r.size > SWEEP_STAMINA_RED

    def confirm_sweep_result(self):
        """
        Press 「確認」 on the sweep result, then the home key once.

        `E_7_1`'s click point was already rewritten by the `appear()` that
        found it, in either caller. Card 5-2 asks for the home key after the
        sweep is done; doing it here and only here is what keeps it from being
        pressed twelve times during the result animation.

        Returns:
            bool: True when the result dialog closed.
        """
        # Guard lives here, not only in the callers: both of them already
        # matched E_7_1, but a click must always be justified by the frame it
        # is sent on (and `appear()` rewrites the click point).
        if self.appear(E_7_1, offset=CHAIN_OFFSET):
            self.device.click(E_7_1)
            gone = self.wait_until_disappear(E_7_1, offset=CHAIN_OFFSET,
                                             timeout=8, settle=2)
            # 消耗体力后弹窗可能压在结算页上，主页键这会儿按了也被吞。
            # 先取消并等它真的消失，再按主页键归位；等不到就干脆别按，
            # 把归位留给下一个任务的 ui_goto。
            if self._interrupt():
                logger.info('Joint raid reminder after the result, dismissed')
                if not self.wait_until_disappear(CORE_RAID_POPUP, offset=(20, 20),
                                                 timeout=8, settle=2):
                    logger.warning('Joint raid reminder still up, home key skipped')
                    return gone
            if self.appear(E_5_2, offset=CHAIN_OFFSET):
                self.device.click(E_5_2)
            logger.info('Sweep result confirmed, event run done')
            return gone

        logger.warning('Sweep result dialog vanished before the confirm press')
        return False

    def wait_sweep_result(self, timeout=90):
        """
        Wait for the sweep result dialog after 「開始掃蕩」 was pressed.

        The sweep animation is the game's own process: clear the watchdog
        every frame (hard rule 152) and let the loop's Timer hold the upper
        bound. The guide chain must not run here - the home key is resident
        on every event page and would be pressed a dozen times before the
        result dialog is even drawn.

        Args:
            timeout (int): Seconds to wait for the dialog.

        Returns:
            bool: True if the result was confirmed and closed.
        """
        for _ in self.loop(timeout=timeout):
            self.device.stuck_record_clear()
            # 弹窗可能压住结算页：先取消它，再继续正面等确认键，
            # 别让这一轮在 90 秒里空等一个被顶掉的 E_7_1。
            if self._interrupt():
                continue
            if self.appear(E_7_1, offset=CHAIN_OFFSET):
                logger.info('Sweep result dialog appeared, confirming')
                return self.confirm_sweep_result()

        logger.warning(f'Sweep result dialog did not appear in {timeout}s')
        return False

    def guide_chain(self, timeout=900, idle=20, idle_start=60):
        """
        Press the tutorial's buttons one after another.

        Every frame tries the whole chain and presses the first button on
        screen. Doing it this way — instead of "wait for step N, then step
        N+1" — is what keeps a dropped frame or a re-entered tutorial from
        derailing the run: whatever is on screen gets pressed, and the order
        of the chain only decides who wins when two buttons are up at once.

        A press is not finished until the same button leaves the screen.
        Without that wait the next frame matches the same button again and
        presses it a second time — for a dialog that means opening it and
        closing it on the next tick, forever.

        The chain ends when nothing has matched for `idle` seconds: a
        tutorial with no button left has nothing more to press. Raise
        `idle` if the flow has a fight or a cutscene longer than that.
        This event normally ends earlier: pressing Start Sweep hands over to
        `wait_sweep_result()`, which waits for the result dialog before
        confirming it. The home key is resident on every event page, so the
        screen never goes quiet and an idle-only chain would spin until timeout.

        Args:
            timeout (int): Give up after this many seconds.
            idle (int): Seconds without a match before the chain is done.
            idle_start (int): Same, but before the first button is found. A
                cold start spends 30-60s on logos and loading where nothing
                matches; with the short budget the chain would call it done
                while the game is still booting. Tightened automatically on
                the first hit, so a finished tutorial does not wait for it.

        Returns:
            bool: True on a quiet screen or a confirmed sweep, False on timeout.
        """
        quiet = Timer(idle_start).start()
        started = False
        # 点过却不消失的按钮，说明它不是「推进型」的：SKIP、返回、关闭都在此列。
        # 记次数、两次之后跳过，免得整个链条卡在它身上空转。
        stubborn = {}
        typed = set()
        for _ in self.loop(timeout=timeout):
            # 常驻键排在最前：它会盖住引导，而且一直都在
            if self._interrupt():
                # 弹窗取消后要重新按一次「扫荡」。之前被模态吞掉的点击
                # 会让 E_5_1 被记成「点了两次都不消失」，不清掉的话
                # 链条会永久跳过它，这一轮体力就白留着了。
                stubborn.clear()
                quiet.reset()
                if not started:
                    started = True
                    quiet.limit = idle
                continue
            for button in GUIDE_CHAIN:
                if stubborn.get(button.name, 0) >= 2:
                    continue
                if button.name in typed:
                    continue
                if self.appear(button, offset=CHAIN_OFFSET):
                    # 点完「开始扫荡」就交给结算等待，别再回链条里让常驻
                    # 主页键抢帧；E_7_1 若已直接出现也走同一套确认流程。
                    if button is E_6_2:
                        if self.sweep_stamina_short():
                            # 体力已被 MAX 用到连一把都打不了，这是清完体力
                            # 的正常终态。别点开始扫荡（不会出结算），也别
                            # 短延迟重试；收工后 run() 直接排到次日。
                            logger.info('Stamina spent, no sweep left this run')
                            if self.appear(E_5_2, offset=CHAIN_OFFSET):
                                self.device.click(E_5_2)
                            return True
                        self.device.click(button)
                        return self.wait_sweep_result()
                    if button is E_7_1:
                        return self.confirm_sweep_result()
                    self.device.click(button)
                    content = TEXT_INPUT.get(button.name)
                    if content:
                        self.device.adb_shell(['input', 'text', content])
                        typed.add(button.name)
                        quiet.reset()
                        if not started:
                            started = True
                            quiet.limit = idle
                        break
                    quiet.reset()
                    if not started:
                        started = True
                        quiet.limit = idle
                    # 等它从画面上消失：没了才说明这一步真的生效了。
                    gone = self.wait_until_disappear(button, offset=CHAIN_OFFSET,
                                                     timeout=4, settle=2)
                    if gone:
                        stubborn.pop(button.name, None)
                    else:
                        stubborn[button.name] = stubborn.get(button.name, 0) + 1
                        if stubborn[button.name] >= 2:
                            logger.warning(f'{button.name} 点了两次都没消失，跳过它')
                    break
            else:
                if quiet.reached():
                    logger.info(f'Guide chain: nothing for {idle}s, done')
                    return True

        logger.warning(f'Guide chain: still pressing after {timeout}s')
        return False
