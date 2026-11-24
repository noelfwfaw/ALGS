"""Guild War (阿瓦隆) automation for Lost Sword (失落之剑)."""

import datetime
import re

from module.base.timer import Timer
from module.base.utils import get_color
from module.exception import GameStuckError
from module.logger import logger
from module.lostsword.assets import (AVALON_BTN_CHALLENGE,
                                     AVALON_BTN_CONFIRM, AVALON_BTN_ENTER,
                                     AVALON_CARD, AVALON_CITY_CONFIRM,
                                     AVALON_RANK_REWARD, AVALON_TITLE,
                                     BATTLE_TITLE, BOSS_VICTORY,
                                     DUNGEON_BTN_CONFIRM, EVENT_BTN_OK,
                                     MAIN_DEFEAT, REWARD_POPUP_TITLE)
from module.lostsword.lostsword_ui import (BATTLE_TAB_GUILD,
                                           BATTLE_TAB_SELECTED_MEAN,
                                           BOSS_RESULT_TAP, LostswordUI,
                                           MAIN_DEFEAT_BACK, page_avalon,
                                           page_battle)
from module.lostsword.star import STAR_RESET_MARGIN, parse_next_time
from module.ocr.ocr import Ocr

# Six attackable cities on the Avalon map (1280x720 shield centers).
AVALON_CITIES = {
    '埃塞尔城': (245, 138),
    '爱尔亚城': (250, 388),
    '埃尔达利亚城': (535, 481),
    '卡美洛城': (845, 343),
    '廷塔哲城': (795, 573),
    '默西亚城': (1030, 373),
}
AVALON_DEFAULT_CITY = '埃塞尔城'
AVALON_DEFAULT_CITY2 = '爱尔亚城'
AVALON_CITY_MAX_BATTLES = 3
AVALON_MAX_BATTLES = 6
AVALON_BATTLE_TIMEOUT = 300
AVALON_CHALLENGE_ENABLED_MEAN = 140

# Card subtitle strip under 「阿瓦隆」 (yellow "可进入" vs rest-period text).
AVALON_CARD_STATUS_AREA = (150, 600, 225, 630)
AVALON_CARD_STATUS_OCR = Ocr(AVALON_CARD_STATUS_AREA, lang='cnocr',
                             letter=(209, 193, 108), threshold=128,
                             name='AVALON_CARD_STATUS_OCR')
# Remaining tries inside 「挑战 (x / 6)」 on `<城市> 现状`.
AVALON_TRIES_AREA = (560, 650, 720, 686)
AVALON_TRIES_OCR = Ocr(AVALON_TRIES_AREA, lang='cnocr', letter=(75, 66, 58),
                       threshold=128, name='AVALON_TRIES_OCR')
AVALON_TRIES_PATTERN = re.compile(r'(\d)\s*/\s*6')
# Body text of transient / blocking notice dialogs (`EVENT_BTN_OK` / `DUNGEON_BTN_CONFIRM`).
AVALON_NOTICE_AREA = (320, 250, 960, 430)
AVALON_NOTICE_OCR = Ocr(AVALON_NOTICE_AREA, lang='cnocr',
                        letter=(235, 230, 220), threshold=128,
                        name='AVALON_NOTICE_OCR')
# Occupied/closed city popup (`城主 / 公会简介 / 下次时间`) countdown row `剩余153:33:28`.
AVALON_NEXT_TIME_AREA = (550, 495, 735, 526)
AVALON_NEXT_TIME_LETTER = (230, 223, 218)
AVALON_NEXT_TIME_THRESHOLDS = (80, 100, 128)
AVALON_NEXT_TIMES = [
    Ocr(AVALON_NEXT_TIME_AREA, lang='cnocr', letter=AVALON_NEXT_TIME_LETTER,
        threshold=threshold, alphabet='0123456789:',
        name=f'AVALON_NEXT_TIME_{threshold}')
    for threshold in AVALON_NEXT_TIME_THRESHOLDS
]


def parse_avalon_tries(text):
    """Parse remaining Avalon tries from OCR text like `挑战(6/6)`."""
    cleaned = (text or '').replace('o', '0').replace('O', '0')
    match = AVALON_TRIES_PATTERN.search(cleaned)
    if not match:
        return -1
    tries = int(match.group(1))
    if 0 <= tries <= AVALON_MAX_BATTLES:
        return tries
    return -1


class LostswordAvalon(LostswordUI):
    """
    Challenge up to two selected cities (3 times per city, 6 total) in Guild War (阿瓦隆).

    Pages:
        in: page_main
        out: page_main
    """

    def avalon_cities(self):
        """Return ordered unique target cities `[city1, city2]` with valid fallbacks."""
        cities = []
        for key, default in (('LostswordAvalon_City', AVALON_DEFAULT_CITY),
                             ('LostswordAvalon_City2', AVALON_DEFAULT_CITY2)):
            city = getattr(self.config, key, default)
            if city not in AVALON_CITIES:
                logger.warning(f'[Avalon] Unknown city "{city}", fallback to {default}')
                city = default
            if city not in cities:
                cities.append(city)
        return cities

    def avalon_read_next_time(self):
        """Read `下次时间` countdown seconds from the city summary popup, or 0."""
        readings = [parse_next_time(ocr.ocr(self.device.image))
                    for ocr in AVALON_NEXT_TIMES]
        readings = [seconds for seconds in readings if seconds]
        if len(readings) >= 2 and len(set(readings)) == 1:
            return readings[0]
        return 0

    def avalon_schedule(self):
        """Delay to the parsed city countdown if available, otherwise weekly reset."""
        target = getattr(self, 'avalon_next_reset', None)
        if target is not None:
            logger.attr('Avalon next reset', str(target))
            self.config.task_delay(target=target)
            return target
        return self.delay_next_week(label='Avalon next reset')

    def _dismiss_notice(self):
        """Dismiss a blocking notice or city-summary dialog if visible; return True if handled."""
        for btn in (EVENT_BTN_OK, DUNGEON_BTN_CONFIRM):
            if self.appear(btn, offset=30):
                text = AVALON_NOTICE_OCR.ocr(self.device.image)
                logger.info(f'[Avalon] Notice popup: {text}')
                self.device.click(btn)
                self.wait_overlay_gone(btn, timeout=4)
                return True
        if self.appear(AVALON_CITY_CONFIRM, offset=30):
            seconds = self.avalon_read_next_time()
            if seconds:
                self.avalon_next_reset = datetime.datetime.now() + datetime.timedelta(
                    seconds=seconds + STAR_RESET_MARGIN)
                logger.info(f'[Avalon] City summary popup, next reset in '
                            f'{datetime.timedelta(seconds=seconds)}')
            else:
                logger.info('[Avalon] City summary popup (countdown unreadable)')
            self.device.click(AVALON_CITY_CONFIRM)
            self.wait_overlay_gone(AVALON_CITY_CONFIRM, timeout=4)
            return True
        return False

    def battle_goto_guild(self, timeout=10):
        """
        Switch `page_battle` to its 「公会」 top tab.

        Pages:
            in: page_battle
            out: page_battle
        """
        timeout = Timer(timeout).start()
        retry = Timer(1.5)
        for _ in self.loop():
            color = get_color(self.device.image, BATTLE_TAB_GUILD.area)
            if sum(color) / 3 > BATTLE_TAB_SELECTED_MEAN:
                return True
            if timeout.reached():
                logger.warning('[Avalon] Cannot switch battle page to 公会 tab')
                return False
            if retry.reached() and self.appear(BATTLE_TITLE, offset=30):
                self.device.click(BATTLE_TAB_GUILD)
                retry.reset()

    def avalon_enter(self, timeout=12):
        """
        Enter the Avalon city map from the 公会 tab, or detect rest period.

        Returns:
            bool: True if Avalon map opened; False if closed/in rest period.
        """
        timeout = Timer(timeout).start()
        retry = Timer(2.0)
        for _ in self.loop():
            if self.appear(AVALON_TITLE, offset=30):
                self.wait_overlay_settle(AVALON_TITLE)
                return True
            if self._dismiss_notice():
                logger.info('[Avalon] Notice popup on entry, likely rest period')
                return False
            if timeout.reached():
                logger.warning('[Avalon] Cannot enter Avalon (likely in rest period)')
                return False
            if retry.reached() and self.appear(AVALON_CARD, offset=30):
                status = AVALON_CARD_STATUS_OCR.ocr(self.device.image)
                if '休整' in status:
                    logger.info(f'[Avalon] Card status "{status}", rest period')
                    return False
                # Cards on page_battle ignore short minitouch taps (same as copy.py).
                self.tap_asset(AVALON_CARD)
                retry.reset()

    def avalon_open_city(self, city, timeout=10):
        """
        Open `<城市> 现状` from the Avalon map.

        Returns:
            bool: True if city status page opened; False on closed popup/timeout.
        """
        point = AVALON_CITIES.get(city, AVALON_CITIES[AVALON_DEFAULT_CITY])
        timeout = Timer(timeout).start()
        retry = Timer(2.0)
        for _ in self.loop():
            if self.appear(AVALON_RANK_REWARD, offset=30) or self.appear(AVALON_BTN_CHALLENGE, offset=30):
                self.wait_overlay_settle(AVALON_RANK_REWARD, timeout=4)
                return True
            if self._dismiss_notice():
                logger.info('[Avalon] City popup on open, skip')
                return False
            if timeout.reached():
                logger.warning(f'[Avalon] City status did not open for {city}')
                return False
            if retry.reached() and self.appear(AVALON_TITLE, offset=30):
                self.tap_point(*point)
                retry.reset()

    def avalon_read_tries(self):
        """
        Read remaining tries on `<城市> 现状`.

        Returns:
            int: 0..6 when recognized (0 if button is disabled), -1 if unknown.
        """
        color = get_color(self.device.image, AVALON_BTN_CHALLENGE.area)
        if sum(color) / 3 < AVALON_CHALLENGE_ENABLED_MEAN:
            return 0
        for attempt in range(2):
            if attempt:
                self.device.screenshot()
            text = AVALON_TRIES_OCR.ocr(self.device.image)
            tries = parse_avalon_tries(text)
            if tries >= 0:
                return tries
        return -1

    def avalon_start_sortie(self, timeout=15):
        """
        Advance from `<城市> 现状` -> `<城市>城墙` -> confirm dialog -> start battle.

        Returns:
            bool: True if battle loading started; False if blocked or timed out.
        """
        self.interval_clear(AVALON_BTN_CHALLENGE)
        self.interval_clear(AVALON_BTN_ENTER)
        self.interval_clear(AVALON_BTN_CONFIRM)
        notices = 0
        timeout = Timer(timeout).start()
        for _ in self.loop():
            if self.appear(AVALON_BTN_ENTER, offset=30):
                self.wait_overlay_settle(AVALON_BTN_ENTER, frames=2, timeout=3)
                break
            if self._dismiss_notice():
                notices += 1
                if notices >= 2:
                    return False
                self.interval_clear(AVALON_BTN_CHALLENGE)
                continue
            if timeout.reached():
                logger.warning('[Avalon] Sortie page did not open')
                return False
            if self.appear_then_click(AVALON_BTN_CHALLENGE, offset=30, interval=2):
                continue

        timeout = Timer(12).start()
        for _ in self.loop():
            if self._dismiss_notice():
                return False
            if self.appear_then_click(AVALON_BTN_CONFIRM, offset=30, interval=2):
                if self.wait_until_disappear(AVALON_BTN_ENTER, offset=30, timeout=5, settle=2):
                    logger.info('[Avalon] Battle started')
                    return True
                continue
            if self.appear_then_click(AVALON_BTN_ENTER, offset=30, interval=2):
                continue
            if not self.appear(AVALON_BTN_ENTER, offset=30):  # alas-lint: allow - check if sortie page left after click
                if self.wait_until_disappear(AVALON_BTN_ENTER, offset=30, timeout=3, settle=2):
                    logger.info('[Avalon] Battle started')
                    return True
            if timeout.reached():
                logger.warning('[Avalon] Battle did not start from sortie page')
                return False

    def avalon_wait_battle(self, timeout=AVALON_BATTLE_TIMEOUT):
        """
        Wait through auto-battle and victory screen until `page_avalon` returns.

        Raises:
            GameStuckError: If the battle does not return to the Avalon map.
        """
        timeout = Timer(timeout).start()
        report = Timer(30).start()
        for _ in self.loop():
            # Auto-battle has sparse UI updates; keep the stuck watchdog clear.
            self.device.stuck_record_clear()

            if self.appear(AVALON_TITLE, offset=30):
                self.wait_overlay_settle(AVALON_TITLE)
                logger.info('[Avalon] Battle finished, returned to city map')
                return True
            if timeout.reached():
                raise GameStuckError('Avalon battle did not finish in time')
            if self.appear(BOSS_VICTORY, offset=30, interval=2):
                logger.info('[Avalon] Victory, tap through')
                self.device.click(BOSS_RESULT_TAP)
                continue
            if self.appear(MAIN_DEFEAT, offset=30, interval=2):
                logger.info('[Avalon] Defeat, tap through')
                self.device.click(MAIN_DEFEAT_BACK)
                continue
            if self.appear(REWARD_POPUP_TITLE, offset=30, interval=2):
                self.handle_reward_popup(button=BOSS_RESULT_TAP)
                continue
            if report.reached():
                report.reset()
                logger.info(f'[Avalon] Still fighting, {int(timeout.current_time())}s elapsed')

    def run(self):  # alas-lint: allow - scheduled weekly via avalon_schedule()/delay_next_week(), which calls config.task_delay()
        """
        Run Guild War (阿瓦隆) on the two configured cities, then schedule weekly.

        Pages:
            in: page_main
            out: page_main
        """
        logger.hr('Lostsword Avalon', level=1)
        self.avalon_next_reset = None
        cities = self.avalon_cities()
        logger.attr('Cities', ', '.join(cities))

        self.ui_ensure(page_battle)
        if not self.battle_goto_guild() or not self.avalon_enter():
            logger.info('[Avalon] Not open or in rest period, delay to next week')
            self.ui_goto_main()
            self.avalon_schedule()
            return

        total_done = 0
        out_of_tries = False
        for city_idx, city in enumerate(cities):
            if city_idx:
                self.ui_ensure(page_avalon)
            for city_round in range(1, AVALON_CITY_MAX_BATTLES + 1):
                if total_done >= AVALON_MAX_BATTLES:
                    out_of_tries = True
                    break
                logger.hr(f'Avalon {city} ({city_round}/{AVALON_CITY_MAX_BATTLES})', level=2)
                if not self.avalon_open_city(city):
                    break
                tries = self.avalon_read_tries()
                logger.info(f'[Avalon] {city} remaining tries: {tries}/{AVALON_MAX_BATTLES}')
                if tries == 0:
                    logger.info(f'[Avalon] {city} has no tries left')
                    break
                if not self.avalon_start_sortie():
                    logger.info(f'[Avalon] {city} sortie could not start, stop city')
                    break
                self.avalon_wait_battle()
                total_done += 1
                if tries == 1:
                    logger.info('[Avalon] Last try completed')
                    out_of_tries = True
                    break
            if out_of_tries or self.avalon_next_reset is not None:
                break

        self.ui_goto_main()
        self.avalon_schedule()
