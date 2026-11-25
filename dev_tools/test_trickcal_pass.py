import os
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.trickcal.assets import (  # noqa: E402
    COSTUME_PASS_ENTRY,
    COSTUME_PASS_TITLE,
    EVENT_PASS_CLAIM_ALL,
)
from module.trickcal.page import (  # noqa: E402
    page_costume_pass,
    page_event_pass,
    page_main,
)
from module.trickcal.pass_task import (  # noqa: E402
    COSTUME_PASS_ENTRY_OFFSET,
    TrickcalPass,
    costume_pass_claim_lit,
)
from module.trickcal.trickcal_ui import TrickcalUI  # noqa: E402


def _make_claim_images():
    EVENT_PASS_CLAIM_ALL.ensure_template()
    x1, y1, x2, y2 = EVENT_PASS_CLAIM_ALL.area
    img_blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    img_lit = img_blank.copy()
    img_lit[y1:y2, x1:x2] = EVENT_PASS_CLAIM_ALL.image

    img_grey = img_blank.copy()
    gray = cv2.cvtColor(EVENT_PASS_CLAIM_ALL.image, cv2.COLOR_RGB2GRAY)
    gray_scaled = np.clip(gray.astype(np.float32) * (162.0 / max(1.0, float(gray.mean()))), 0, 255).astype(np.uint8)
    img_grey[y1:y2, x1:x2] = np.stack([gray_scaled, gray_scaled, gray_scaled], axis=-1)
    return img_blank, img_lit, img_grey


def _make_pass_task():
    task = TrickcalPass.__new__(TrickcalPass)
    task.device = MagicMock()
    task.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    task.device.click = MagicMock()
    task.device.click_record_clear = MagicMock()
    task.device.screenshot = MagicMock(side_effect=lambda: task.device.image)
    task.device.stuck_record_clear = MagicMock()
    task.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    task.ui_ensure = MagicMock()
    task.ui_goto_main = MagicMock()
    task.ui_additional = MagicMock(return_value=False)
    task.ui_page_appear = MagicMock(return_value=False)
    task.appear = MagicMock(return_value=False)
    task.handle_reward_popup = MagicMock(return_value=False)
    task.config = MagicMock()
    return task


class TestTrickcalPass(unittest.TestCase):
    def test_page_costume_pass_precedes_event_pass(self):
        self.assertLess(
            TrickcalUI.pages.index(page_costume_pass),
            TrickcalUI.pages.index(page_event_pass),
        )

    def test_real_screenshots_costume_pass(self):
        img_blank, img_lit, img_grey = _make_claim_images()
        self.assertFalse(EVENT_PASS_CLAIM_ALL.match_luma(img_blank, offset=(10, 10)))
        self.assertTrue(EVENT_PASS_CLAIM_ALL.match_luma(img_lit, offset=(10, 10)))
        self.assertTrue(costume_pass_claim_lit(img_lit))
        self.assertTrue(EVENT_PASS_CLAIM_ALL.match_luma(img_grey, offset=(10, 10)))
        self.assertFalse(costume_pass_claim_lit(img_grey))

        u_dir = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded'
        paths = {
            'lobby_bakery': os.path.join(u_dir, 'media_1795581362756_87728e05.jpg'),
            'lobby_city': os.path.join(u_dir, 'media_1795580306731_2666bb61.jpg'),
            'cpass_lit': os.path.join(u_dir, 'media_1795581405936_d84d4edd.jpg'),
            'cpass_grey': os.path.join(u_dir, 'media_1795227813016_e870d2ae.jpg'),
        }
        if not all(os.path.exists(p) for p in paths.values()):
            return

        def load_rgb_1280(p):
            bgr = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bgr.shape[:2] != (720, 1280):
                bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        bakery = load_rgb_1280(paths['lobby_bakery'])
        city = load_rgb_1280(paths['lobby_city'])
        cpass_lit = load_rgb_1280(paths['cpass_lit'])
        cpass_grey = load_rgb_1280(paths['cpass_grey'])

        self.assertTrue(COSTUME_PASS_ENTRY.match(bakery, offset=COSTUME_PASS_ENTRY_OFFSET))
        self.assertTrue(COSTUME_PASS_ENTRY.match(city, offset=COSTUME_PASS_ENTRY_OFFSET))
        self.assertTrue(COSTUME_PASS_TITLE.match(cpass_lit, offset=(20, 20)))
        self.assertTrue(COSTUME_PASS_TITLE.match(cpass_grey, offset=(20, 20)))
        self.assertFalse(COSTUME_PASS_TITLE.match(bakery, offset=(20, 20)))
        self.assertFalse(COSTUME_PASS_TITLE.match(city, offset=(20, 20)))
        self.assertTrue(EVENT_PASS_CLAIM_ALL.match_luma(cpass_lit, offset=(10, 10)))
        self.assertTrue(EVENT_PASS_CLAIM_ALL.match_luma(cpass_grey, offset=(10, 10)))
        self.assertTrue(costume_pass_claim_lit(cpass_lit))
        self.assertFalse(costume_pass_claim_lit(cpass_grey))

        ui = TrickcalUI.__new__(TrickcalUI)
        ui.device = MagicMock()
        ui.device.image = cpass_lit
        self.assertIs(ui.ui_get_current_page(skip_first_screenshot=True), page_costume_pass)
        ui.device.image = cpass_grey
        self.assertIs(ui.ui_get_current_page(skip_first_screenshot=True), page_costume_pass)

    def test_costume_pass_waits_for_paint_and_claims(self):
        task = _make_pass_task()
        img_blank, img_lit, img_grey = _make_claim_images()
        state = {'page': page_main, 'blank_frames': 2, 'popup': False, 'claimed': False}
        task.device.image = img_blank

        def page_appear(p):
            if p is not state['page']:
                return False
            if p is page_costume_pass and not state['claimed'] and not state['popup']:
                if state['blank_frames'] > 0:
                    state['blank_frames'] -= 1
                    task.device.image = img_blank
                else:
                    task.device.image = img_lit
            return True

        task.ui_page_appear.side_effect = page_appear
        task.appear.side_effect = lambda btn, **k: state['page'] is page_main and btn is COSTUME_PASS_ENTRY

        def handle_popup():
            if state['popup']:
                state['popup'] = False
                task.device.image = img_grey
                return True
            return False

        task.handle_reward_popup.side_effect = handle_popup

        def on_click(btn):
            if btn is COSTUME_PASS_ENTRY:
                state['page'] = page_costume_pass
            elif btn is EVENT_PASS_CLAIM_ALL:
                state['claimed'] = True
                state['popup'] = True

        task.device.click.side_effect = on_click
        ok = task.costume_pass_claim()

        self.assertTrue(ok)
        clicked_names = [c[0][0].name for c in task.device.click.call_args_list]
        self.assertEqual(clicked_names, ['COSTUME_PASS_ENTRY', 'EVENT_PASS_CLAIM_ALL'])
        task.ui_goto_main.assert_called_once()

    def test_costume_pass_skips_when_already_grey(self):
        task = _make_pass_task()
        _, _, img_grey = _make_claim_images()
        task.device.image = img_grey
        task.ui_page_appear.side_effect = lambda p: p is page_costume_pass

        ok = task.costume_pass_claim()

        self.assertTrue(ok)
        task.device.click.assert_not_called()
        task.ui_goto_main.assert_called_once()

    def test_costume_pass_skips_cleanly_when_inactive(self):
        task = _make_pass_task()
        task.ui_page_appear.side_effect = lambda p: p is page_main
        task.appear.return_value = False
        task.pass_claim = MagicMock(return_value=(True, ''))

        task.run()

        self.assertFalse(task.costume_pass_open())
        task.device.click.assert_not_called()
        task.pass_claim.assert_called_once()
        task.config.task_delay.assert_called_once_with(server_update=True)


if __name__ == '__main__':
    unittest.main()
