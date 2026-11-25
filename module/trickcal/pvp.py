"""Peak Duel (巅峰对决 / 胜利者的竞技场) automation for Trickcal.

Entry path: `page_main -> page_adventure -> page_pvp -> page_pvp_arena -> page_pvp_deck`.
Daily limit: 5 free challenges per day (0 stamina), defaulting to opponent 1.
"""

import re

import numpy as np

from module.base.timer import Timer
from module.base.utils import crop
from module.logger import logger
from module.trickcal.assets import (
    DUNGEON_CLONE_EMPTY,
    PVP_BUY_ATTEMPTS,
    PVP_BUY_CANCEL,
    PVP_CLAIM_REWARD,
    PVP_GO_WIN,
    PVP_RESULT_EXIT,
)
from module.trickcal.dungeon_stage import _ocr_bw, tap_box
from module.trickcal.page import page_main, page_pvp_arena, page_pvp_deck
from module.trickcal.trickcal_ui import TrickcalUI

PVP_OPPONENT_AREAS = {
    1: (650, 170, 1180, 260),
    2: (650, 345, 1180, 435),
    3: (650, 510, 1180, 600),
}
PVP_CLAIM_AREA = (51, 395, 181, 432)
PVP_CLAIM_COLOR_THRESHOLD = 55
PVP_CLAIM_DIM_FRAMES = 3
PVP_HUB_ATTEMPTS_AREA = (1178, 96, 1248, 134)
PVP_ARENA_ATTEMPTS_AREA = (405, 385, 495, 425)

PVP_OFFSET = (20, 20)
PVP_MAX_ROUNDS = 6
PVP_BATTLE_TIMEOUT = 180


def _compact_bw(bw, max_gap=3):
    """Collapse wide empty column gaps inside a binary mask so spaced `0 / 5` reads cleanly."""
    col_has_ink = (bw == 0).any(axis=0)
    keep = []
    gap = 0
    started = False
    for idx, has in enumerate(col_has_ink):
        if has:
            started = True
            gap = 0
            keep.append(idx)
        elif started:
            gap += 1
            if gap <= max_gap:
                keep.append(idx)
    return bw[:, keep] if keep else bw


def read_pvp_attempts(image, on_hub=False):
    """Read remaining daily PvP attempts (`cur/5`) on `page_pvp` or `page_pvp_arena`."""
    area = PVP_HUB_ATTEMPTS_AREA if on_hub else PVP_ARENA_ATTEMPTS_AREA
    patch = crop(image, area)
    bw = np.where(patch.min(axis=2) > 190, 0, 255).astype(np.uint8)
    last_txt = ''
    for candidate in (bw, _compact_bw(bw, max_gap=3)):
        last_txt = _ocr_bw(candidate, alphabet='0123456789/')
        m = re.search(r'(\d+)\s*/\s*(\d+)', last_txt)
        if m:
            return int(m.group(1))
    logger.warning(f'Could not parse PvP attempts: {last_txt!r}')
    return None


def pvp_claim_lit(image):
    """Return True when the hourly `领取奖励` button on `page_pvp_arena` is lit gold."""
    return PVP_CLAIM_REWARD.appear_on(image, threshold=PVP_CLAIM_COLOR_THRESHOLD)


class TrickcalPvp(TrickcalUI):
    """
    Daily Peak Duel (`巅峰对决 -> 胜利者的竞技场`) challenger.

    Pages:
        in: page_main
        out: page_main
    """

    def ui_additional(self):
        """Dismiss leftover PvP popups before delegating to `TrickcalUI`."""
        if self.appear(PVP_BUY_ATTEMPTS, offset=PVP_OFFSET) and self.appear(
            PVP_BUY_CANCEL, offset=PVP_OFFSET, interval=2
        ):
            logger.info('Leftover PvP buy-attempts popup (购买挑战次数), press 取消')
            self.device.click(PVP_BUY_CANCEL)
            return True
        if self.appear(PVP_RESULT_EXIT, offset=PVP_OFFSET, interval=2):
            logger.info('Leftover PvP result popup, press 退出')
            self.device.click(PVP_RESULT_EXIT)
            return True
        return super().ui_additional()

    def run(self):
        """Enter 胜利者的竞技场, claim hourly reward, challenge opponents, and exit to lobby."""
        logger.hr('Trickcal PvP', level=1)
        self.ui_ensure(page_main)
        self.ui_ensure(page_pvp_arena)

        self._claim_hourly_reward()

        slot = max(1, min(3, int(self.config.TrickcalPvp_Opponent)))
        for _ in range(PVP_MAX_ROUNDS):
            self.ui_ensure(page_pvp_arena)

            rem = read_pvp_attempts(self.device.image, on_hub=False)
            if rem == 0:
                logger.info('PvP daily attempts 0/5, done')
                break
            if self.appear(PVP_BUY_ATTEMPTS, offset=PVP_OFFSET):
                self._dismiss_buy_attempts()
                break

            if not self._open_opponent_deck(slot):
                logger.warning(f'Could not open opponent {slot} deck or attempts exhausted, stop')
                break

            status = self._depart_pvp()
            if status == 'empty':
                break
            if status == 'timeout':
                logger.warning('PvP depart timed out, return to arena list')
                self.ui_ensure(page_pvp_arena)
                break
            if status in ('battle', 'result') and not self._wait_pvp_battle_end():
                break

        if self.ui_page_appear(page_pvp_arena) and pvp_claim_lit(self.device.image):
            self._claim_hourly_reward()

        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def _claim_hourly_reward(self):
        """Claim accumulated arena points when `领取奖励` is lit gold and dismiss reward popup."""
        retry = Timer(2.0)
        claimed = False
        dim_frames = 0
        for _ in self.loop(timeout=10):
            if self.handle_reward_popup():
                claimed = True
                dim_frames = 0
                continue
            if self.ui_page_appear(page_pvp_arena) and PVP_CLAIM_REWARD.match_luma(self.device.image, offset=PVP_OFFSET):
                if pvp_claim_lit(self.device.image):
                    dim_frames = 0
                    if retry.reached():
                        retry.reset()
                        logger.info('Claim hourly PvP reward')
                        self.device.click(PVP_CLAIM_REWARD)  # alas-lint: allow - guarded by ui_page_appear(page_pvp_arena), match_luma, and pvp_claim_lit()
                else:
                    dim_frames += 1
                    if (claimed and dim_frames >= 2) or dim_frames >= PVP_CLAIM_DIM_FRAMES:
                        if not claimed:
                            logger.info('PvP hourly reward is dim (0%), skip')
                        return claimed
            else:
                dim_frames = 0
        return claimed

    def _dismiss_buy_attempts(self):
        """Close 「购买挑战次数」 via 取消 without spending crystals."""
        retry = Timer(2.0)
        clean = 0
        for _ in self.loop(timeout=8):
            if self.appear(PVP_BUY_ATTEMPTS, offset=PVP_OFFSET):
                clean = 0
                if self.appear(PVP_BUY_CANCEL, offset=PVP_OFFSET) and retry.reached():
                    retry.reset()
                    logger.info('PvP daily attempts exhausted (购买挑战次数), press 取消')
                    self.device.click(PVP_BUY_CANCEL)
                continue
            clean += 1
            if clean >= 2:
                return True
        return False

    def _open_opponent_deck(self, slot):
        """Tap opponent `slot` (1..3) on `page_pvp_arena` until `page_pvp_deck` opens."""
        opp_btn = tap_box(PVP_OPPONENT_AREAS[slot], f'PVP_OPPONENT_{slot}')
        retry = Timer(2.0)
        for _ in self.loop(timeout=8):
            if self.appear(PVP_BUY_ATTEMPTS, offset=PVP_OFFSET):
                self._dismiss_buy_attempts()
                return False
            if self.appear(DUNGEON_CLONE_EMPTY, offset=PVP_OFFSET):
                logger.info('PvP daily attempts exhausted (每日入场次数已用完), stop')
                return False
            if self.ui_page_appear(page_pvp_deck):
                return True
            if self.ui_page_appear(page_pvp_arena) and retry.reached():
                retry.reset()
                logger.info(f'Select PvP opponent {slot}')
                self.device.click(opp_btn)  # alas-lint: allow - guarded by ui_page_appear(page_pvp_arena)
        return self.ui_page_appear(page_pvp_deck)

    def _depart_pvp(self):
        """Press `去获胜` on `page_pvp_deck` until battle starts or result appears."""
        retry = Timer(2.0)
        departed = False
        absent = 0
        for _ in self.loop(timeout=12):
            if self.appear(PVP_BUY_ATTEMPTS, offset=PVP_OFFSET):
                self._dismiss_buy_attempts()
                return 'empty'
            if self.appear(PVP_RESULT_EXIT, offset=PVP_OFFSET):
                return 'result'
            if self.ui_page_appear(page_pvp_arena):
                return 'arena'
            if self.appear(PVP_GO_WIN, offset=PVP_OFFSET):
                absent = 0
                departed = True
                if retry.reached():
                    retry.reset()
                    logger.info('Start PvP match, press 去获胜')
                    self.device.click(PVP_GO_WIN)
                continue
            if departed:
                absent += 1
                if absent >= 3:
                    return 'battle'
        return 'timeout'

    def _wait_pvp_battle_end(self, timeout=PVP_BATTLE_TIMEOUT):
        """Wait for PvP auto-battle to finish, dismiss result (`退出`), and return to arena."""
        overall = Timer(timeout).start()
        report = Timer(30).start()
        for _ in self.loop():
            self.device.stuck_record_clear()
            if self.handle_reward_popup():
                continue
            if self.appear(PVP_RESULT_EXIT, offset=PVP_OFFSET, interval=2):
                logger.info('PvP battle finished, press 退出')
                self.device.click(PVP_RESULT_EXIT)
                continue
            if self.ui_page_appear(page_pvp_arena):
                logger.info('Back at 胜利者的竞技场')
                return True
            if report.reached():
                report.reset()
                logger.info(f'PvP battle running ({int(overall.current_time())}s elapsed)')
            if overall.reached():
                logger.warning('PvP battle wait timed out')
                return False
        return False
