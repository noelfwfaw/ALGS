from module.base.button import Button
from module.base.timer import Timer
from module.logger import logger
from module.lostsword.assets import (REWARD_POPUP_TITLE, TREASURE_BTN_CLAIM,
                                    TREASURE_BTN_QUICK, TREASURE_DIALOG_PAID,
                                    TREASURE_QUICK_CLOSE, TREASURE_QUICK_TITLE)
from module.lostsword.lostsword_ui import LostswordUI, page_treasure

"""
宝藏探索 (treasure exploration).

Flow observed in game:

    page_main  --宝藏探索入口-->  page_treasure
    page_treasure  获取宝藏      ->  已获得道具。弹窗（点空白关闭）
    page_treasure  快速探查      ->  快速探查弹窗
        每日首次免费：底部是「开始探查」，按下去立刻获得 120 分钟奖励。
        免费次数用完：底部变成「💎90 开始探查」，这时只关弹窗，不付钻石。
    page_treasure  关闭 X        ->  page_main

Two timing traps, both of them cost resources or open a wrong popup:

- The reward popup fades out *after* its title is gone. A click sent during the
  fade lands on the item list of that popup and opens the item detail page
  instead of the button underneath, so every "popup is gone" check needs the
  settle window of `LostswordUI.wait_overlay_gone()`.
- The quick-explore dialog fades in. Its price row ("💎90 开始探查") does not
  match until it is drawn, so "not matched" must not be read as "free attempt
  available", otherwise the script presses start and spends 90 diamonds.
"""

# 快速探查弹窗底部的按钮。免费时写着「开始探查」，要钻石时写着「💎90 开始探查」，
# 位置和大小不变，所以直接复用「需要钻石」那张素材的按钮范围。
TREASURE_QUICK_START = Button(area=TREASURE_DIALOG_PAID.area,
                              color=TREASURE_DIALOG_PAID.color,
                              button=TREASURE_DIALOG_PAID.button,
                              name='TREASURE_QUICK_START')


class LostswordTreasure(LostswordUI):
    """
    Claim the accumulated treasure, then spend the free quick-explore of the day.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Treasure explore', level=1)
        self.ui_ensure(page_treasure)

        if self.config.LostswordTreasure_Claim:
            self.treasure_claim()
        if self.config.LostswordTreasure_Quick:
            # 关奖励弹窗的那一下会把面板一起关掉（同一击被弹窗和面板各消费一次），
            # 所以这里重新确保面板在，而不是假设还停在面板上。
            self.ui_ensure(page_treasure)
            self.treasure_quick()

        self.ui_goto_main()

        # 宝藏按分钟累积，但每天上线领一次就够，跟着日刷新排。
        self.config.task_delay(server_update=True)

    def treasure_claim(self):
        """
        Claim the treasure and dismiss the reward popup.

        The button looks the same whether there is something to claim or not,
        so "clicked and no popup came up" means nothing has accumulated yet,
        not a failure. The click is retried once because the panel slides in
        and a click sent during that animation is swallowed by the input lock.

        Pages:
            in: page_treasure
            out: page_treasure

        Returns:
            bool: If a reward popup was handled.
        """
        for _ in range(2):
            self.device.click(TREASURE_BTN_CLAIM)
            if self.wait_overlay(REWARD_POPUP_TITLE, timeout=5):
                logger.info('Treasure claimed, dismiss the reward popup')
                return self.handle_reward_popup()

        logger.info('Nothing to claim yet')
        return False

    def treasure_quick(self):
        """
        Open the quick-explore dialog and spend the free attempt of the day.

        When the free attempt is gone the dialog asks for 90 diamonds, which is
        never worth it: close the dialog and leave.

        Pages:
            in: page_treasure
            out: page_treasure

        Returns:
            bool: If an exploration was started.
        """
        for _ in range(2):
            self.device.click(TREASURE_BTN_QUICK)
            if self.wait_overlay(TREASURE_QUICK_TITLE, timeout=5):
                break
        else:
            logger.warning('Quick explore dialog did not open, skipped')
            return False

        if self.treasure_wait_paid():
            logger.info('Free attempt used up, starting one costs 90 diamonds, skipped')
            self.device.click(TREASURE_QUICK_CLOSE)
            self.wait_overlay_gone(TREASURE_QUICK_TITLE)
            return False

        logger.info('Free attempt available, start exploring')
        self.device.click(TREASURE_QUICK_START)
        self.treasure_wait_quick_result(timeout=30)
        return True

    def treasure_wait_paid(self, frames=None, timeout=5):
        """
        Decide whether the quick explore costs diamonds.

        The price row is drawn with the dialog, so a frame from the fade-in
        matches nothing. Read that as "free" and the script presses start and
        spends 90 diamonds, so the absence has to hold for a settle window too.

        Args:
            frames (int): Consecutive frames without a match needed.
            timeout (int, float): Seconds.

        Returns:
            bool: True if it costs diamonds.
        """
        frames = frames or self.SETTLE_FRAMES
        timeout = Timer(timeout).start()
        absent = 0
        while 1:
            self.device.screenshot()
            if self.appear(TREASURE_DIALOG_PAID, offset=30, similarity=0.9):
                return True
            absent += 1
            if absent >= frames:
                return False
            if timeout.reached():
                return False

    def treasure_wait_quick_result(self, timeout=30):
        """
        Wait until the quick-explore result is settled.

        Two outcomes are known: a reward popup (which is dismissed here), or
        the dialog closing straight back to the panel. Anything else is left to
        the caller, which closes the panel and goes home anyway.

        Args:
            timeout (int, float): Seconds.

        Returns:
            bool: If a result was recognised.
        """
        timeout = Timer(timeout).start()
        while 1:
            self.device.screenshot()
            if self.appear(REWARD_POPUP_TITLE, offset=30):
                logger.info('Exploration finished, dismiss the reward popup')
                return self.handle_reward_popup()
            if not self.appear(TREASURE_QUICK_TITLE, offset=30):
                logger.info('Exploration started')
                return True
            if timeout.reached():
                logger.warning('Quick explore result unknown')
                return False
