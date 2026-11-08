"""模拟军演 of 交错战线 (Cross Core).

Flow:

    大厅 出击 → 模拟军演 → 镜像竞技 → 选对手
    → 第一行对手（直接进 VS 页）→ 挑战 → 战斗（不可跳过）
    → 战斗胜利 / 战斗失败结算页（点空白继续）→ 选对手（获得物品弹窗）
    → 商店兑换 → 一直买左上第一格 → 只剩星币 / 技术点 → 回大厅

What the 2026-11-09 measurements settled:

1. 选对手页用第一行「排名」小牌子判定（导出素材 `选对手.png`）；结算页的
   「排名:」没有那块底板，实测只匹配到 0.669，不会互相误判。
2. 胜利和失败都停在同一个结算页，标题文字不同，所以用标题下方的装饰线
   判定结算页（`军演结算.png`，跨页最高 0.724）；标题本身只用来写日志。
3. 结算页点屏幕下方空白处继续，之后必定弹「获得物品」，等它出现再点掉，
   既清掉弹窗，也确认结算页已经退掉。
4. 商店一次显示两行、六列，商品买完后变暗并排到队尾，所以一直点左上第一格。
   第一格里出现星币 / 技术点图标时，说明只剩这两件，直接退出商店。
5. 有数量选择的商品先点「最大」再点「购买」；购买成功必弹「获得物品」，
   等弹窗出现再点掉，避免同一次购买按两遍。
"""

from module.crosscore.assets import (E_5_1, EXERCISE_BUY, EXERCISE_BUY_QTY,
                                     EXERCISE_CHALLENGE, EXERCISE_COIN_ITEM,
                                     EXERCISE_ENTRY, EXERCISE_ITEM_1,
                                     EXERCISE_MAX, EXERCISE_MIRROR,
                                     EXERCISE_OPPONENT, EXERCISE_OPPONENT_1,
                                     EXERCISE_RESULT, EXERCISE_RESULT_CLICK,
                                     EXERCISE_SHOP, EXERCISE_SHOP_PAGE,
                                     EXERCISE_TECH_ITEM, EXERCISE_WIN,
                                     EXPLORE_SORTIE)
from module.crosscore.crosscore_ui import CrosscoreUI
from module.crosscore.page import page_main
from module.crosscore.utils import has_template, template_of
from module.logger import logger

# 商店左上第一格。商品买完后会排到队尾，所以第一格永远是「下一个要买的」。
FIRST_CARD_REGION = (0, 120, 250, 400)
# 整块商品区，用来等列表换位动画结束。
SHOP_CARD_REGION = (0, 120, 1280, 660)
# 选对手页左下「商店兑换」那一带，用来等结算页彻底退掉。
OPPONENT_READY_REGION = (210, 630, 390, 690)

# 模拟次数每天 10 次，打满即止。
MAX_BATTLE = 10


class CrosscoreExercise(CrosscoreUI):
    """
    Fight the first opponent of 模拟军演 until the daily attempts run out,
    then spend the points in its shop.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        """
        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('交错模拟军演', level=1)
        self.ui_ensure(page_main)

        if not self.exercise_enter():
            logger.warning('Cannot open 模拟军演, retry in 15 minutes')
            self.config.task_delay(minute=15)
            return

        fought = self.exercise_fight()
        if fought is None:
            logger.warning('模拟军演 failed, retry in 15 minutes')
            self.config.task_delay(minute=15)
            return

        bought = self.exercise_shop()
        if bought is None:
            logger.warning('军演商店 failed, retry in 15 minutes')
            self.config.task_delay(minute=15)
            return

        self.back_to_main()
        logger.info(f'模拟军演 {fought} battle(s), {bought} item(s) bought')
        # Simulation attempts and the shop reset with the daily server update.
        self.config.task_delay(server_update=True)

    def exercise_enter(self):
        """
        Walk from the lobby to the opponent page.

        Returns:
            bool: If the opponent page is on screen.
        """
        for _ in self.loop(timeout=90):
            if self.handle_item_popup():
                continue
            if self.handle_lobby_popup():
                continue
            if self.exercise_opponent_appear():
                # The list fades in; a click on a half drawn row is lost.
                self.wait_until_still(EXERCISE_OPPONENT.area, timeout=3)
                return True
            if self.appear(EXERCISE_MIRROR, offset=(20, 20), interval=3):
                logger.info('模拟军演 page, press 镜像竞技')
                self.device.click(EXERCISE_MIRROR)
            elif self.appear(EXERCISE_ENTRY, offset=(20, 20), interval=3):
                logger.info('Sortie page, press 模拟军演')
                self.device.click(EXERCISE_ENTRY)
            elif self.appear(EXPLORE_SORTIE, offset=(20, 20), interval=3):
                logger.info('Lobby, press 出击')
                self.device.click(EXPLORE_SORTIE)

        logger.warning('Cannot open the opponent page')
        return False

    def exercise_opponent_appear(self):
        """
        Whether the opponent page is drawn (its 「排名」 plate).
        """
        return self.appear(EXERCISE_OPPONENT, offset=(20, 20))

    def exercise_fight(self):
        """
        Fight the first opponent until the attempts run out.

        The first row is always the one fought - 用户要求「不用管对手战力，
        只打第一个」. When the attempts are gone the row stops opening the VS
        page; that is the normal end of the loop, not a failure.

        Returns:
            int: Battles fought.
            None: If the battle or the result page is stuck.
        """
        logger.hr('军演战斗', level=2)
        fought = 0

        for _ in range(MAX_BATTLE):
            if not self.exercise_pick_first_opponent():
                logger.info('No simulation attempt left')
                break

            if not self.exercise_challenge():
                logger.warning('Cannot press 挑战')
                return None

            if not self.exercise_result():
                logger.warning('Battle did not finish')
                return None

            fought += 1
            logger.info(f'Battle {fought} done')

        return fought

    def exercise_pick_first_opponent(self):
        """
        Press the first opponent row and wait for the VS page.

        The row is the button: pressing it jumps straight to the VS page, there
        is no 「进攻部署」 step in between - that button opens the 战棋编队 page
        instead (实测 2026-11-09).

        Returns:
            bool: If the VS page (its 「挑战」) is on screen.
        """
        for retry in range(3):
            for _ in self.loop(timeout=10):
                if self.handle_item_popup():
                    continue
                if self.appear(EXERCISE_OPPONENT, offset=(20, 20)):
                    logger.info('Select the first opponent')
                    self.device.click(EXERCISE_OPPONENT_1)
                    break
            else:
                logger.warning('Lost the opponent page')
                return False

            # A popup opening on top of the row, or a click on a half drawn
            # list, can swallow the press, so try again before giving up.
            if self.wait_until_appear(EXERCISE_CHALLENGE, offset=(20, 20), timeout=8):
                return True
            logger.warning(f'The VS page did not show up, retry {retry + 1}/3')

        return False

    def exercise_challenge(self):
        """
        Press 「挑战」 once and hand over to the battle.

        The battle can not be skipped, it is waited out in `exercise_result()`.
        The click counter is cleared so the long wait does not trip the
        same-button protection.

        Returns:
            bool: If the button was pressed.
        """
        for _ in self.loop(timeout=20):
            if self.appear(EXERCISE_CHALLENGE, offset=(20, 20)):
                logger.info('Press 挑战')
                self.device.click(EXERCISE_CHALLENGE)
                self.device.click_record_clear()
                return True

        return False

    def exercise_result(self):
        """
        Wait out the battle, then click the result page away.

        Both victory and defeat end on the same page; the title itself is only
        used for the log. The 「获得物品」 popup that follows is the positive
        proof that the result page is gone - waiting for the page to disappear
        can be fooled by its animations (同一坑：每日探索的扫荡结算).

        Returns:
            bool: If the opponent page is back.
        """
        if not self.wait_until_appear(EXERCISE_RESULT, offset=(20, 20), timeout=300):
            logger.warning('Battle result page did not show up')
            return False

        if self.appear(EXERCISE_WIN, offset=(20, 20)):
            logger.info('Battle won')
        else:
            logger.info('Battle lost')

        # Press the blank area until the result page is gone. The page animates
        # while it fades, so one click is not guaranteed to land; the reward
        # popup is handled on the way out.
        for _ in self.loop(timeout=60):
            if self.handle_item_popup():
                continue
            if self.appear(EXERCISE_RESULT, offset=(20, 20), interval=3):
                logger.info('Press the blank area to leave the result page')
                self.device.click(EXERCISE_RESULT_CLICK)
                continue
            if self.exercise_opponent_appear():
                self.wait_until_still(OPPONENT_READY_REGION, timeout=3)
                return True

        logger.warning('The opponent page did not come back')
        return False

    def exercise_shop(self):
        """
        Open the shop from the opponent page and buy until only the two
        currency cards are left.

        Returns:
            int: Items bought.
            None: If the shop is stuck.
        """
        logger.hr('军演商店', level=2)

        for _ in self.loop(timeout=30):
            if self.handle_item_popup():
                continue
            if self.appear(EXERCISE_SHOP_PAGE, offset=(20, 20)):
                # The grid slides after each purchase; only read it once still.
                self.wait_until_still(SHOP_CARD_REGION, timeout=3)
                return self.exercise_buy_all()
            if self.appear(EXERCISE_SHOP, offset=(20, 20), interval=3):
                logger.info('Press 商店兑换')
                self.device.click(EXERCISE_SHOP)

        logger.warning('Cannot open the shop')
        return None

    def exercise_buy_all(self):
        """
        Press the first card until 星币 / 技术点 come to the front.

        Returns:
            int: Items bought.
            None: If a purchase does not raise its popup.
        """
        bought = 0

        for _ in self.loop(timeout=900):
            if self.handle_item_popup():
                continue

            # A purchase dialog is open: finish it before touching the grid.
            if self.appear(EXERCISE_MAX, offset=(20, 20)) \
                    or self.appear(EXERCISE_BUY, offset=(20, 20)) \
                    or self.appear(EXERCISE_BUY_QTY, offset=(20, 20)):
                if not self.exercise_buy_one():
                    return None
                bought += 1
                logger.info(f'Bought {bought} item(s)')
                self.wait_until_still(SHOP_CARD_REGION, timeout=5)
                continue

            if self.appear(EXERCISE_SHOP_PAGE, offset=(20, 20), interval=2):
                if self.exercise_only_currency_left():
                    logger.info('Only 星币 and 技术点 are left, shop done')
                    return bought
                logger.info('Press the first shop item')
                self.device.click(EXERCISE_ITEM_1)

        logger.warning('The shop did not finish in time')
        return None

    def exercise_buy_one(self):
        """
        Buy the open purchase dialog: 最大 (if present) → 购买 → 获得物品.

        Returns:
            bool: If the purchase popup was raised.
        """
        if self.appear(EXERCISE_MAX, offset=(20, 20)):
            logger.info('Press 最大')
            self.device.click(EXERCISE_MAX)
            # The quantity and the total price below it are redrawn.
            self.wait_until_still((740, 415, 1060, 470), timeout=3)

        for _ in self.loop(timeout=10):
            if self.appear(EXERCISE_BUY, offset=(20, 20), interval=2) \
                    or self.appear(EXERCISE_BUY_QTY, offset=(20, 20), interval=2):
                logger.info('Press 购买')
                self.device.click(EXERCISE_BUY)
                break
        else:
            logger.warning('The purchase dialog has no 购买')
            return False

        if self.wait_until_appear(E_5_1, offset=(20, 20), timeout=10):
            self.handle_item_popup()
            return True

        logger.warning('No purchase popup')
        return False

    def exercise_only_currency_left(self):
        """
        Whether the first shop card is 星币 or 技术点.

        The two cards are the tail of the list (用户实测：买完的商品会变暗排到
        队尾), so once one of them reaches the first slot there is nothing else
        worth buying. The icons are matched over the whole first slot, because
        the card keeps its art when it moves.
        """
        image = self.device.image
        return has_template(image, template_of(EXERCISE_COIN_ITEM),
                            FIRST_CARD_REGION, similarity=0.85) \
            or has_template(image, template_of(EXERCISE_TECH_ITEM),
                            FIRST_CARD_REGION, similarity=0.85)
