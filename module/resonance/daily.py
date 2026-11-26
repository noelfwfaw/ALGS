import cv2

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.exception import GameStuckError
from module.resonance.assets import LOGIN_REWARD, TEMPLATE_DAILY_CLAIM
from module.resonance.page import page_daily
from module.resonance.resonance_ui import ResonanceUI


CARD_PROGRESS = (124, 292, 1127, 419)
CARD_BUTTONS = (124, 599, 1127, 641)
MILESTONES = ButtonGrid(origin=(421, 168), delta=(122, 0), button_shape=(6, 11), grid_shape=(6, 1))


class ResonanceDaily(ResonanceUI):
    def run(self):
        # Reopening the task panel starts its horizontal list at the first card.
        self.ui_ensure(self.page_main, skip_first_screenshot=False)
        self.ui_ensure(page_daily)
        self.claim_tasks()
        self.claim_milestones()
        self.ui_goto_main()
        self.config.task_delay(server_update=True)

    def claim_tasks(self):
        previous = None
        retry = Timer(1)
        for _ in self.loop(timeout=45):
            if self.handle_reward_popup():
                retry.reset()
                continue
            if self.ui_page_appear(page_daily) and retry.reached():
                score, claim = TEMPLATE_DAILY_CLAIM.match_result(self.image_crop(CARD_BUTTONS))
                if score > 0.90:
                    self.device.click(claim.move(CARD_BUTTONS[:2]))
                    retry.reset()
                    previous = None
                    continue

                cards = self.image_crop(CARD_PROGRESS)
                if previous is not None and cv2.absdiff(previous, cards).mean() < 1:
                    return
                previous = cards
                self.device.swipe((850, 443), (550, 443), duration=0.55, name='DAILY_TASKS_SCROLL')
                if not self.wait_until_still(CARD_PROGRESS, timeout=8, skip_first_screenshot=False):
                    break
        raise GameStuckError('Resonance daily task cards did not settle')

    def _reward_popup_appear(self):
        return (
            self.appear(LOGIN_REWARD, offset=(5, 5))
            or self.appear(LOGIN_REWARD, offset=(30, 140), similarity=0.78)
        )

    def _wait_milestone_claimed(self, gift):
        for _ in self.loop(skip_first=False, timeout=8):
            if self._reward_popup_appear():
                return True
            if self.ui_page_appear(page_daily):
                if self.image_color_count(gift, (248, 179, 1), threshold=35, count=35):
                    continue
                return True
        return False

    def claim_milestones(self):
        for _ in self.loop(timeout=45):
            if self.handle_reward_popup():
                continue
            if self.ui_page_appear(page_daily):
                for gift in MILESTONES.buttons:
                    if self.image_color_count(gift, (248, 179, 1), threshold=35, count=35):
                        self.device.click(gift)
                        if not self._wait_milestone_claimed(gift):
                            raise GameStuckError(f'Resonance activity reward did not appear for {gift}')
                        break
                else:
                    return
        raise GameStuckError('Resonance activity rewards did not settle')
