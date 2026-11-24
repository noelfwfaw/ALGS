"""服务器维护页处理（`ChaoszeroUI` 的混入）。

维护时客户端把整个标题/大厅换成一张 "maintenance" 公告页：中间一条纯白
横幅（維護說明 / 剩餘時間 / 開始結束時間），横幅下沿一枚橙红「公告」按钮。
这页没有任何能进游戏的按钮，点按钮只打开公告。旧启动循环认不出它就会
每 8 秒点顶部、300 秒后 `GameStuckError` → `Restart`，维护几小时就是重启循环。

不建 `Page`、不做模板：维护文案每期都换，而且这一屏只在进大厅之前出现，
建了 Page 会让 `ui_goto` 以为能从大厅「回去」。
"""

import os
import re
from datetime import datetime, timedelta

import cv2
import numpy as np

from module.base.timer import Timer
from module.chaoszero.rogue_ocr import ChaoszeroOcr
from module.log_retention import prune_diagnostics
from module.logger import logger

# 服务器维护页（2026-11-11 09:09 真机截图）。整屏换成 "maintenance" 画面：
# 中间一条纯白横幅（y≈178~458）写維護說明 / 剩餘時間 / 開始結束時間，横幅下沿
# 压着一枚橙红色「公告」按钮（实测 bbox (501,472)-(778,527)）。
# 判据用两个相对量而不是模板：换一期维护文案、换标题都照样成立。
# 103 张卡厄思历史截图（公告 / 连接失败 / 奖励弹窗 / 冷启动 / 大厅 / 战斗）
# 双门槛零误判 —— 纯白的截图橙像素为 0，纯橙的截图白像素 <0.08。
CHAOSZERO_MAINT_BANNER = (100, 230, 1180, 430)
CHAOSZERO_MAINT_BUTTON = (501, 472, 778, 527)
CHAOSZERO_MAINT_TIMER = (540, 265, 840, 330)
CHAOSZERO_MAINT_WHITE = 0.80
# Real maintenance puts one centered button across (501..778) (~0.90 orange);
# two-button popups (e.g. 下載內容) put orange only on the right half (~0.41 overlap).
CHAOSZERO_MAINT_ORANGE = 0.65
# 倒计时归零后客户端还要重连 / 校验补丁，留两分钟余量。
CHAOSZERO_MAINT_BUFFER = 2
# 倒计时读不出来时隔多久再来看一眼（分钟）。
CHAOSZERO_MAINT_RETRY = 10
CHAOSZERO_CONFIRM_WORDS = (
    '確認', '確定', '确认', '确定',
    '重試', '重试', '重新', '連接', '連線', '繼續', '继续', 'ok',
)
CHAOSZERO_POPUP_DIR = './log/error/chaoszero_boot_popup'

MAINTENANCE_TIMER = ChaoszeroOcr(CHAOSZERO_MAINT_TIMER, lang='cnocr',
                                 letter=(0, 0, 0), threshold=160,
                                 name='CHAOSZERO_MAINT_TIMER')
MAINTENANCE_BUTTON = ChaoszeroOcr(CHAOSZERO_MAINT_BUTTON, lang='cnocr',
                                  letter=(255, 255, 255), threshold=160,
                                  name='CHAOSZERO_MAINT_BUTTON')


class Maintenance:
    """Detect the maintenance screen and end the task with a delay.

    Depends on the class it is combined with (`ChaoszeroUI` / `ModuleBase`):

    - `image_crop(area)` and `device.image` for the current frame.
    - `config.SCHEDULER_PRIORITY`, `config.cross_get()`,
      `config.task_delay()` and `config.task_stop()` for scheduling.
    - `handle_maintenance()` is called from `handle_app_boot()` and
      `ui_additional()` of the UI class.
    """

    def maintenance_appear(self):
        """
        Whether the server-maintenance screen is on screen.

        Two independent colour gates, both relative (hard rule 178). The white
        banner alone also matches a few white/cropped screenshots and the orange
        button alone matches the mail asset previews, but never together:
        measured on 103 real Chaoszero frames, maintenance reads
        white=0.901 / orange=0.899 while every other frame misses one gate.
        `astype(int)` is required - subtracting uint8 channels wraps around and
        turns arbitrary colours into "orange" (hard rule on channel math).

        Returns:
            bool:
        """
        # The cheap gate comes first: this runs on every frame of every boot
        # loop, and the button area is 1/14 the size of the banner.
        image = self.image_crop(CHAOSZERO_MAINT_BUTTON).astype(int)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        orange = float(np.count_nonzero(
            (r > 195) & (r - g > 80) & (r - b > 80) & (g < 150) & (b < 130)
        )) / r.size
        if orange < CHAOSZERO_MAINT_ORANGE:
            return False

        image = self.image_crop(CHAOSZERO_MAINT_BANNER).astype(int)
        r, g, b = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        white = float(np.count_nonzero((r > 225) & (g > 225) & (b > 225))) / r.size
        return white > CHAOSZERO_MAINT_WHITE

    def maintenance_remaining(self):
        """
        Read the HH:MM:SS countdown on the maintenance banner.

        Called only after `maintenance_appear()` (hard rule 19). cnocr reads
        `03:50:32` on the real frame with every letter/threshold combination
        tried; the digits are pulled out of the string instead of a strict
        regex because the spacing around the colons varies.

        Returns:
            datetime: Expected end of the maintenance, None if unreadable.
        """
        text = MAINTENANCE_TIMER.ocr(self.device.image)
        digits = re.findall(r'\d+', text or '')
        if len(digits) < 3:
            logger.warning(f'Cannot read the maintenance countdown: {text!r}')
            return None
        hour, minute, second = (int(x) for x in digits[:3])
        if hour > 23 or minute > 59 or second > 59:
            logger.warning(f'Invalid maintenance countdown: {text!r}')
            return None
        target = datetime.now() + timedelta(
            hours=hour, minutes=minute + CHAOSZERO_MAINT_BUFFER, seconds=second)
        logger.info(f'Maintenance countdown {text}, expected to end at {target}')
        return target

    def maintenance_delay(self, target):
        """
        Push every Chaoszero task that is due before `target` to `target`.

        A maintenance window lasts hours. Delaying only the task that happened
        to be running leaves the other four due immediately: the scheduler would
        launch the game again for each of them, see the same screen and stop,
        i.e. four pointless cold starts. Names come from `SCHEDULER_PRIORITY`
        so a newly added task is covered without touching this method.

        `task_delay()` writes `NextRun` only - it never enables a task the user
        turned off (hard rule 70) - and a task already scheduled later than
        `target` is left alone instead of being pulled forward.

        Args:
            target (datetime): When to retry, must be in the future.
        """
        names = [name for name in self.config.SCHEDULER_PRIORITY.replace('>', ' ').split()
                 if name.startswith('Chaoszero')]
        for name in names:
            current = self.config.cross_get(keys=[name, 'Scheduler', 'NextRun'])
            if isinstance(current, str):
                try:
                    current = datetime.fromisoformat(current)
                except ValueError:
                    continue
            if not isinstance(current, datetime):
                continue
            if current >= target:
                continue
            self.config.task_delay(target=target, task=name)

    def _save_boot_popup(self, button_text):
        """Save one diagnostic frame when a white-banner modal is not maintenance."""
        saver = getattr(self, '_maint_popup_saved', None)
        if saver is None:
            saver = Timer(10)
            self._maint_popup_saved = saver
        if not saver.reached():
            return
        saver.reset()
        os.makedirs(CHAOSZERO_POPUP_DIR, exist_ok=True)
        path = os.path.join(CHAOSZERO_POPUP_DIR,
                            datetime.now().strftime('popup_%Y%m%d_%H%M%S.png'))
        cv2.imwrite(path, self.device.image[:, :, ::-1])
        prune_diagnostics(CHAOSZERO_POPUP_DIR, 'screenshot')
        logger.warning(f'Saved non-maintenance boot popup ({button_text!r}) to {path}')

    def handle_maintenance(self):
        """
        Handle the white-banner + orange-button modal during boot or mid-run.

        Server maintenance shows an 「公告」 button (or a `HH:MM:SS` countdown)
        and delays all Chaoszero tasks until it ends. Other modals with the
        exact same white-banner + orange-button layout (such as a network/session
        error dialog whose button reloads the game) do not show 「公告」 or a
        countdown; those must click the confirm/retry button instead of delaying
        every Chaoszero task as false maintenance.

        Returns:
            bool: True when a confirm/retry modal was tapped, False otherwise.

        Raises:
            TaskEnd: When confirmed server maintenance stops the task.
        """
        if not self.maintenance_appear():
            return False

        button_text = (MAINTENANCE_BUTTON.ocr(self.device.image) or '').strip()
        target = self.maintenance_remaining()
        if target is None and '公告' not in button_text:
            self._save_boot_popup(button_text)
            lowered = button_text.lower()
            if any(word in lowered for word in CHAOSZERO_CONFIRM_WORDS):
                cooldown = getattr(self, '_maint_popup_click', None)
                if cooldown is None:
                    cooldown = Timer(3)
                    self._maint_popup_click = cooldown
                if cooldown.reached():
                    cooldown.reset()
                    x1, y1, x2, y2 = CHAOSZERO_MAINT_BUTTON
                    logger.info(f'Boot/network confirm popup ({button_text!r}), click to reload')
                    self.device.click_record_clear()
                    self.tap_point((x1 + x2) // 2, (y1 + y2) // 2, name='CHAOSZERO_BOOT_CONFIRM')
                return True
            logger.warning(f'Unknown white-banner modal (button={button_text!r}), ignore')
            return False

        if target is None:
            target = datetime.now() + timedelta(minutes=CHAOSZERO_MAINT_RETRY)
        self.maintenance_delay(target)
        shown = target.replace(microsecond=0)
        logger.warning(f'Server maintenance, Chaoszero tasks delayed to {shown}')
        self.config.task_stop(f'游戏维护中，卡厄思任务已延迟到 {shown}')
