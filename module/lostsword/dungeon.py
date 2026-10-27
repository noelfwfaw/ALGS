from module.base.timer import Timer
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (ARENA_BTN_CLOSE, DUNGEON_BTN_BACK,
                                     DUNGEON_BTN_CONFIRM, DUNGEON_BTN_MATCH,
                                     DUNGEON_CARD, DUNGEON_CLEAR,
                                     DUNGEON_DIALOG_CLOSE,
                                     DUNGEON_DIALOG_TITLE, DUNGEON_TITLE)
from module.lostsword.lostsword_ui import (LostswordUI, page_battle,
                                          page_dungeon)

"""
小队副本 (squad dungeon).

Flow observed in game:

    page_main  --底栏「战斗」-->  page_battle（普通页签，小队副本是第三张卡）
    page_battle  --「小队副本」卡-->  page_dungeon（黑龙·尼德霍格 / KING）
    page_dungeon  --「开始匹配 1/1」-->  「是否前往小队副本房间?」--> 「确认」
    ->  客户端加载页（正在火热招募队友中… 20）
    ->  战斗（自动，无需准备）->  「CLEAR」结算页  --「返回」-->  page_dungeon
    page_dungeon  --右上圆 X-->  page_battle  --右上圆 X-->  page_main

One try a day. The detail page is built exactly like the boss raid one (same
「队伍编排」 button, same left column), so it is matched by its boss name instead;
and the card of the battle page only exists under 「普通」.

The result page of this mode is 「CLEAR」, not the 「VICTORY」 of the solo modes,
which is why it needs its own asset rather than reusing BOSS_VICTORY.

Whether today's try is left is read from the match button: it is drawn as
「开始匹配 1/1」 while a try is left (match 1.00) and as "ticket count + 开始匹配"
once it is used up (match below 0.5).
"""

# Recruiting takes 20 seconds, then the client loads, then the battle runs on its
# own. Two minutes is generous.
DUNGEON_TIMEOUT = 300


class LostswordDungeon(LostswordUI):
    """
    Spend the daily squad dungeon try and wait for the battle to clear.

    Pages:
        in: page_main
        out: page_main
    """

    def run(self):
        logger.hr('Squad dungeon', level=1)
        self.ui_ensure(page_battle)
        self.battle_goto_normal()
        self.ui_ensure(page_dungeon)

        if self.dungeon_available():
            self.dungeon_fight()
        else:
            logger.info('No squad dungeon try left for today')

        self.ui_goto_main()
        # One try a day, at the daily reset of this game (00:00).
        self.config.task_delay(server_update=True)

    def dungeon_available(self):
        """
        Whether the daily try is still there.

        Returns:
            bool: If 「开始匹配」 is the version with a try count.
        """
        self.device.screenshot()
        return self.appear(DUNGEON_BTN_MATCH, offset=30)

    def dungeon_fight(self, timeout=DUNGEON_TIMEOUT):
        """
        Confirm the match and wait for the CLEAR screen, then leave it.

        Pages:
            in: page_dungeon
            out: page_dungeon

        Args:
            timeout (int, float): Seconds to wait for the battle.

        Returns:
            bool: If a battle was fought to the end.

        Raises:
            GameStuckError: If the battle does not end in time.
        """
        logger.hr('Squad dungeon battle', level=2)
        self.device.click(DUNGEON_BTN_MATCH)
        if not self.wait_overlay(DUNGEON_DIALOG_TITLE, timeout=8):
            logger.warning('Match confirm dialog did not open')
            return False

        self.device.click(DUNGEON_BTN_CONFIRM)

        # Recruiting runs on its own countdown ("小队突袭无需准备，一定时间后自动
        # 开始"), and the battle is auto played: nothing is clicked until CLEAR.
        timeout = Timer(timeout).start()
        report = Timer(30).start()
        while 1:
            self.device.stuck_record_clear()
            self.device.screenshot()
            if self.appear(DUNGEON_CLEAR, offset=30):
                logger.info('Squad dungeon cleared')
                break
            if self.appear(DUNGEON_TITLE, offset=30):
                # Back on the detail page without a result screen: the run ended
                # in some way that leaves nothing to collect.
                logger.info('Back at the dungeon page, battle is over')
                return True
            if report.reached():
                report.reset()
                logger.info(f'Still in the dungeon, {int(timeout.current_time())}s elapsed')
            if timeout.reached():
                logger.warning('Squad dungeon did not finish in time')
                raise GameStuckError('Squad dungeon did not end in time')
            self.device.sleep(2)

        self.device.click(DUNGEON_BTN_BACK)
        if not self.wait_overlay(DUNGEON_TITLE, timeout=40):
            logger.warning('Did not return to the squad dungeon page')
        return True
