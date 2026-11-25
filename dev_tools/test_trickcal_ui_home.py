import os
import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from module.config.server import set_server

# Bind trickcal assets/config before importing module.trickcal.*
set_server('trickcal')

from module.trickcal.assets import BACK, HOME  # noqa: E402
from module.trickcal.page import (  # noqa: E402
    page_adventure,
    page_main,
    page_order,
    page_order_relic,
    page_pvp_arena,
    page_task,
)
from module.trickcal.trickcal_ui import TrickcalUI  # noqa: E402
from module.ui.ui import UI  # noqa: E402


def _make_ui():
    ui = TrickcalUI.__new__(TrickcalUI)
    ui.device = MagicMock()
    ui.device.image = np.zeros((720, 1280, 3), dtype=np.uint8)
    ui.device.click = MagicMock()
    ui.device.screenshot = MagicMock(side_effect=lambda: ui.device.image)
    ui.device.stuck_record_clear = MagicMock()
    ui.loop = MagicMock(side_effect=lambda skip_first=True, timeout=60: iter(range(30)))
    ui.interval_clear = MagicMock()
    ui.interval_reset = MagicMock()
    ui.ui_loading_appear = MagicMock(return_value=False)
    ui.ui_wait_loading = MagicMock(return_value=True)
    ui.ui_wait_page_leave = MagicMock(return_value=True)
    ui.ui_additional = MagicMock(return_value=False)
    ui.ui_page_appear = MagicMock(return_value=False)
    ui.appear = MagicMock(return_value=False)
    return ui


class TestTrickcalUiHome(unittest.TestCase):
    def test_home_template_on_real_screenshots(self):
        u_dir = r'C:\Users\14494\.gemini\antigravity\brain\13f03cda-c1d1-419a-8ba6-f6233f3d96d8\.user_uploaded'
        pos_paths = [
            os.path.join(u_dir, 'media_1795580310515_6492dacd.jpg'),  # page_order
            os.path.join(u_dir, 'media_1795576723965_d73212fa.jpg'),  # page_adventure
            os.path.join(u_dir, 'media_1795581748279_78e2af51.jpg'),  # page_pvp_arena
            os.path.join(u_dir, 'media_1795581405936_d84d4edd.jpg'),  # page_costume_pass
            os.path.join(u_dir, 'media_1795535223483_c5d06a65.jpg'),  # page_doll
        ]
        neg_paths = [
            os.path.join(u_dir, 'media_1795581362756_87728e05.jpg'),  # page_main bakery
            os.path.join(u_dir, 'media_1795580306731_2666bb61.jpg'),  # page_main city
            os.path.join(u_dir, 'media_1795580313511_3d103158.jpg'),  # page_order_relic
            os.path.join('screenshots', 'trickcal', '每日任务.png'),  # page_task
            os.path.join('screenshots', 'trickcal', '邮箱.png'),      # page_mail
        ]

        def load_rgb_1280(p):
            bgr = cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)
            if bgr.shape[:2] != (720, 1280):
                bgr = cv2.resize(bgr, (1280, 720), interpolation=cv2.INTER_CUBIC)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        for p in pos_paths:
            if os.path.exists(p):
                self.assertTrue(HOME.match(load_rgb_1280(p), offset=(20, 20)), p)
        for p in neg_paths:
            if os.path.exists(p):
                self.assertFalse(HOME.match(load_rgb_1280(p), offset=(20, 20)), p)

    def test_ui_goto_main_clicks_home_once_from_deep_subpage(self):
        ui = _make_ui()
        state = {'page': page_pvp_arena, 'home': True, 'cool_frames': 1}

        def page_appear(page, offset=(30, 30), interval=0):
            if state['page'] is page_main and state['cool_frames'] > 0:
                return False
            return page is state['page']

        def appear_fn(btn, offset=(20, 20), interval=0):
            if btn is HOME:
                if state['page'] is page_pvp_arena:
                    return state['home']
                if state['page'] is page_main and state['cool_frames'] > 0:
                    state['cool_frames'] -= 1
                    return True
            return False

        def on_click(btn):
            if btn is HOME:
                state['page'] = page_main

        ui.ui_page_appear.side_effect = page_appear
        ui.appear.side_effect = appear_fn
        ui.device.click.side_effect = on_click

        timer_inst = MagicMock()
        timer_inst.reached.side_effect = [True, False]
        with patch('module.trickcal.trickcal_ui.Timer', return_value=timer_inst):
            ui.ui_goto(page_main)

        self.assertIs(ui.ui_current, page_main)
        clicked = [c[0][0] for c in ui.device.click.call_args_list]
        self.assertEqual(clicked, [HOME])

    def test_ui_goto_main_runs_ui_additional_before_home(self):
        ui = _make_ui()
        state = {'page': page_pvp_arena, 'popup': True}
        events = []

        def additional():
            if state['popup']:
                events.append('popup')
                state['popup'] = False
                return True
            return False

        def on_click(btn):
            events.append(btn.name)
            if btn is HOME:
                state['page'] = page_main

        ui.ui_additional.side_effect = additional
        ui.ui_page_appear.side_effect = lambda page, offset=(30, 30), interval=0: page is state['page']
        ui.appear.side_effect = lambda btn, offset=(20, 20), interval=0: btn is HOME and state['page'] is page_pvp_arena
        ui.device.click.side_effect = on_click

        ui.ui_goto(page_main)
        self.assertEqual(events, ['popup', 'HOME'])

    def test_ui_goto_main_falls_back_when_home_absent(self):
        # 1) page_order_relic (no HOME) -> BACK -> page_order (has HOME) -> HOME -> page_main
        ui = _make_ui()
        state = {'page': page_order_relic}

        def on_click(btn):
            if btn is BACK and state['page'] is page_order_relic:
                state['page'] = page_order
            elif btn is HOME and state['page'] is page_order:
                state['page'] = page_main

        ui.ui_page_appear.side_effect = lambda page, offset=(30, 30), interval=0: page is state['page']
        ui.appear.side_effect = lambda btn, offset=(20, 20), interval=0: btn is HOME and state['page'] is page_order
        ui.device.click.side_effect = on_click

        ui.ui_goto(page_main)
        clicked = [c[0][0] for c in ui.device.click.call_args_list]
        self.assertEqual(clicked, [BACK, HOME])

        # 2) page_task (no HOME) -> BACK -> page_main
        ui2 = _make_ui()
        state2 = {'page': page_task}
        ui2.ui_page_appear.side_effect = lambda page, offset=(30, 30), interval=0: page is state2['page']
        ui2.appear.return_value = False
        ui2.device.click.side_effect = lambda btn: state2.__setitem__('page', page_main) if btn is BACK else None

        ui2.ui_goto(page_main)
        clicked2 = [c[0][0] for c in ui2.device.click.call_args_list]
        self.assertEqual(clicked2, [BACK])

    def test_ui_goto_non_main_delegates_to_super(self):
        ui = _make_ui()
        with patch.object(UI, 'ui_goto', return_value=None) as mock_super:
            ui.ui_goto(page_adventure)
        mock_super.assert_called_once_with(page_adventure, offset=(30, 30), skip_first_screenshot=True)
        ui.device.click.assert_not_called()


if __name__ == '__main__':
    unittest.main()
