import json
import os
import unittest
from unittest.mock import MagicMock

import cv2
import numpy as np

from module.config.config_manual import ManualConfig
from module.config.server import set_server
from module.config.utils import get_server_next_update

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.trickcal.assets import (  # noqa: E402
    ORDER_CHECK,
    ORDER_ENTRY,
    ORDER_HQ_TITLE,
    ORDER_RELIC_CLAIM,
    ORDER_RELIC_TITLE,
)
from module.trickcal.order import (  # noqa: E402
    TrickcalOrder,
    order_relic_claim_lit,
)
from module.trickcal.page import page_order, page_order_relic  # noqa: E402


def _make_relic_claim_images():
    ORDER_RELIC_CLAIM.ensure_template()
    x1, y1, x2, y2 = ORDER_RELIC_CLAIM.area
    img_blank = np.zeros((720, 1280, 3), dtype=np.uint8)
    img_lit = img_blank.copy()
    img_lit[y1:y2, x1:x2] = ORDER_RELIC_CLAIM.image

    img_grey = img_blank.copy()
    gray = cv2.cvtColor(ORDER_RELIC_CLAIM.image, cv2.COLOR_RGB2GRAY)
    gray_scaled = np.clip(gray.astype(np.float32) * (166.0 / max(1.0, float(gray.mean()))), 0, 255).astype(np.uint8)
    img_grey[y1:y2, x1:x2] = np.stack([gray_scaled, gray_scaled, gray_scaled], axis=-1)
    return img_blank, img_lit, img_grey


def _make_order_task():
    order = TrickcalOrder.__new__(TrickcalOrder)
    order.device = MagicMock()
    order.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    order.device.click = MagicMock()
    order.device.click_record_clear = MagicMock()
    order.device.screenshot = MagicMock(side_effect=lambda: order.device.image)
    order.device.stuck_record_clear = MagicMock()
    order.loop = MagicMock(side_effect=lambda timeout=10: iter(range(20)))
    order.ui_ensure = MagicMock()
    order.ui_goto_main = MagicMock()
    order.ui_page_appear = MagicMock(return_value=False)
    order.appear = MagicMock(return_value=False)
    order.handle_reward_popup = MagicMock(return_value=False)
    order.config = MagicMock()
    return order


class TestTrickcalOrder(unittest.TestCase):
    def test_scheduler_priority_before_stamina_tasks(self):
        lines = [line.strip() for line in ManualConfig.SCHEDULER_PRIORITY.splitlines() if line.strip()]
        trickcal_line = next(line for line in lines if 'TrickcalOrder' in line)
        tasks = [t.strip() for t in trickcal_line.lstrip('>').split('>')]
        for stamina_task in ('TrickcalDoll', 'TrickcalEvent', 'TrickcalDungeon'):
            self.assertLess(tasks.index('TrickcalOrder'), tasks.index(stamina_task))

    def test_real_screenshots_and_claim_lit(self):
        img_blank, img_lit, img_grey = _make_relic_claim_images()
        self.assertFalse(ORDER_RELIC_CLAIM.match_luma(img_blank, offset=(20, 20)))
        self.assertTrue(ORDER_RELIC_CLAIM.match_luma(img_lit, offset=(20, 20)))
        self.assertTrue(order_relic_claim_lit(img_lit))
        self.assertTrue(ORDER_RELIC_CLAIM.match_luma(img_grey, offset=(20, 20)))
        self.assertFalse(order_relic_claim_lit(img_grey))

        u_dir = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded'
        paths = {
            'main': os.path.join(u_dir, 'media_1795580306731_2666bb61.jpg'),
            'ord': os.path.join(u_dir, 'media_1795580310515_6492dacd.jpg'),
            'rel': os.path.join(u_dir, 'media_1795580313511_3d103158.jpg'),
        }
        if not all(os.path.exists(p) for p in paths.values()):
            return

        def load_rgb_1280(p):
            bgr = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bgr.shape[:2] != (720, 1280):
                bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        main_img = load_rgb_1280(paths['main'])
        ord_img = load_rgb_1280(paths['ord'])
        rel_img = load_rgb_1280(paths['rel'])

        self.assertTrue(ORDER_ENTRY.match(main_img, offset=(20, 20)))
        self.assertTrue(ORDER_CHECK.match(ord_img, offset=(20, 20)))
        self.assertTrue(ORDER_HQ_TITLE.match(ord_img, offset=(20, 20)))
        self.assertTrue(ORDER_RELIC_TITLE.match(rel_img, offset=(20, 20)))
        self.assertTrue(ORDER_RELIC_CLAIM.match(rel_img, offset=(20, 20)))
        self.assertTrue(ORDER_RELIC_CLAIM.match_luma(rel_img, offset=(20, 20)))
        self.assertFalse(ORDER_RELIC_CLAIM.match_luma(ord_img, offset=(20, 20)))
        self.assertTrue(order_relic_claim_lit(rel_img))
        self.assertFalse(ORDER_HQ_TITLE.match(rel_img, offset=(20, 20)))

        x1, y1, x2, y2 = ORDER_RELIC_CLAIM.area
        rel_grey = rel_img.copy()
        crop_gray = cv2.cvtColor(rel_img[y1:y2, x1:x2], cv2.COLOR_RGB2GRAY)
        scaled = np.clip(crop_gray.astype(np.float32) * (166.0 / max(1.0, float(crop_gray.mean()))), 0, 255).astype(np.uint8)
        rel_grey[y1:y2, x1:x2] = np.stack([scaled, scaled, scaled], axis=-1)
        self.assertTrue(ORDER_RELIC_CLAIM.match_luma(rel_grey, offset=(20, 20)))
        self.assertFalse(order_relic_claim_lit(rel_grey))

    def test_run_switches_to_hq_opens_relic_and_claims(self):
        order = _make_order_task()
        _, img_lit, img_grey = _make_relic_claim_images()

        state = {'page': page_order, 'hq': False, 'popup': False}
        order.device.image = img_lit
        order.ui_page_appear.side_effect = lambda p: p is state['page']
        order.appear.side_effect = lambda b, **k: b is ORDER_HQ_TITLE and state['hq']

        def handle_popup():
            if state['popup']:
                state['popup'] = False
                order.device.image = img_grey
                return True
            return False

        order.handle_reward_popup.side_effect = handle_popup

        def on_click(btn):
            if btn.name == 'ORDER_HQ_TAB':
                state['hq'] = True
            elif btn.name == 'ORDER_RELIC_SHRINE':
                state['page'] = page_order_relic
            elif btn is ORDER_RELIC_CLAIM:
                state['popup'] = True

        order.device.click.side_effect = on_click
        order.run()

        clicked_names = [c[0][0].name for c in order.device.click.call_args_list]
        self.assertEqual(clicked_names, ['ORDER_HQ_TAB', 'ORDER_RELIC_SHRINE', 'ORDER_RELIC_CLAIM'])
        order.ui_goto_main.assert_called_once()
        order.config.task_delay.assert_called_once_with(server_update=True)

    def test_claim_skips_when_already_grey(self):
        order = _make_order_task()
        _, _, img_grey = _make_relic_claim_images()
        order.device.image = img_grey
        order.ui_page_appear.side_effect = lambda p: p is page_order_relic
        order.appear.side_effect = lambda b, **k: b is ORDER_HQ_TITLE

        order.run()
        order.device.click.assert_not_called()
        order.ui_goto_main.assert_called_once()
        order.config.task_delay.assert_called_once_with(server_update=True)

    def test_claim_waits_for_panel_slide_in(self):
        order = _make_order_task()
        img_blank, img_lit, img_grey = _make_relic_claim_images()
        state = {'blank_frames': 3, 'popup': False, 'claimed': False}
        order.device.image = img_blank
        order.appear.side_effect = lambda b, **k: b is ORDER_HQ_TITLE

        def page_appear(p):
            if p is not page_order_relic:
                return False
            if not state['claimed'] and not state['popup']:
                if state['blank_frames'] > 0:
                    state['blank_frames'] -= 1
                    order.device.image = img_blank
                else:
                    order.device.image = img_lit
            return True

        order.ui_page_appear.side_effect = page_appear

        def handle_popup():
            if state['popup']:
                state['popup'] = False
                order.device.image = img_grey
                return True
            return False

        order.handle_reward_popup.side_effect = handle_popup

        def on_click(btn):
            if btn is ORDER_RELIC_CLAIM:
                state['claimed'] = True
                state['popup'] = True

        order.device.click.side_effect = on_click
        order.run()

        clicked_names = [c[0][0].name for c in order.device.click.call_args_list]
        self.assertEqual(clicked_names, ['ORDER_RELIC_CLAIM'])
        order.ui_goto_main.assert_called_once()
        order.config.task_delay.assert_called_once_with(server_update=True)

    def test_dual_server_update_schedule(self):
        with open('config/template.json', encoding='utf-8') as f:
            tmpl = json.load(f)

        dual_tasks = (
            'TrickcalFriend',
            'TrickcalMail',
            'TrickcalOrder',
            'TrickcalEvent',
            'TrickcalDungeon',
            'TrickcalTask',
            'TrickcalPass',
        )
        single_tasks = (
            'TrickcalLogin',
            'TrickcalDoll',
            'TrickcalClass',
            'TrickcalPvp',
            'TrickcalShop',
            'TrickcalNormalShop',
        )
        for task in dual_tasks:
            self.assertEqual(tmpl[task]['Scheduler']['ServerUpdate'], '05:00, 18:00', task)
        for task in single_tasks:
            self.assertEqual(tmpl[task]['Scheduler']['ServerUpdate'], '05:00', task)

        next_run = get_server_next_update('05:00, 18:00')
        self.assertIn((next_run.hour, next_run.minute), ((5, 0), (18, 0)))


if __name__ == '__main__':
    unittest.main()
