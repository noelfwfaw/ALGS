"""Offline unit tests for Season Chaos (賽季卡厄思) configuration and entry flow."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from module.config.server import set_server

set_server('chaoszero')

from module.chaoszero import rogue_events, rogue_route
from module.chaoszero.rogue import (
    ChaoszeroRogue,
    SCULPT_BTN_POINT,
    SCULPT_CARD_POINT,
    SCULPT_CONFIRM_POINT,
    SCULPT_EXIT_CARD_POINT,
    SCULPT_LEAVE_POINT,
    SEASON_DIFF_ENTER,
    SEASON_LOCKED_AREA,
    SEASON_POPUP_CLOSE,
    SEASON_TIER_Y,
)
from module.exception import RequestHumanTakeover


UPLOADED = Path(
    'C:/Users/14494/.gemini/antigravity/brain/13f03cda-c1d1-419a-8ba6-f6233f3d96d8/.user_uploaded'
)
FILES = {
    'lobby': 'media_1795348115545_991804fb.jpg',
    'season_hub': 'media_1795348115495_906d8a23.jpg',
    'season_diff': 'media_1795348115539_72ad32d3.jpg',
    'team_on': 'media_1795348115507_608b3b0a.jpg',
    'team_off': 'media_1795348115541_2a950c5c.jpg',
    'locked': 'media_1795350552404_418c83a4.jpg',
    'pure_white_mem': 'media_1795353466079_3bd61e99.jpg',
    'reward_list': 'media_1795353550288_f84d7c13.jpg',
    'get_card_popup': 'media_1795353590704_e9148a86.jpg',
    'get_buff_popup': 'media_1795353626393_c47eb6e6.jpg',
    'season_map': 'media_1795353648432_3e1f3dde.jpg',
    'engrave_collapsed': 'media_1795353798656_4f7d2663.jpg',
    'engrave_expanded': 'media_1795353802660_e7fd2c09.jpg',
    'mem_choose_1': 'media_1795354198003_05059fc1.jpg',
    'mem_choose_2': 'media_1795354198004_cb4bc887.jpg',
    'mem_choose_3': 'media_1795354198026_17a87da3.jpg',
    'mem_choose_4_sel': 'media_1795354198073_e68e4a61.jpg',
    'mem_choose_5': 'media_1795354833757_d136f677.jpg',
    'mem_assign_member': 'media_1795354845469_f3d52297.jpg',
    'oath_two_cards': 'media_1795355008622_6696db35.jpg',
    'corridor_continue': 'media_1795355017699_edbb6e6c.jpg',
    'sculpt_1_entry': 'media_1795355187108_011f1e12.jpg',
    'sculpt_2_workshop': 'media_1795355187230_be821620.jpg',
    'sculpt_3_compare': 'media_1795355187285_7b4630f6.jpg',
    'sculpt_4_popup': 'media_1795355187329_b1ad9552.jpg',
    'sculpt_5_corridor': 'media_1795355187367_d89eced7.jpg',
    'checkpoint_continue': 'media_1795355187415_eae42c46.jpg',
    'floor2_end_memory_end': 'media_1795355187491_979b8e2d.jpg',
    'floor2_end_map': 'media_1795355995988_f6663a5b.jpg',
    'season_rest': 'media_1795358431691_86cf792e.jpg',
    'season_rest_shop_1': 'media_1795359677290_2088b493.jpg',
    'season_rest_shop_2': 'media_1795359701943_cfcca755.jpg',
    'season_rest_shop_3': 'media_1795359701979_8aec080a.jpg',
    'season_rest_shop_4': 'media_1795359702026_eb4cfc3f.jpg',
    'season_rest_shop_5': 'media_1795359702083_a42db1b2.jpg',
    'season_rest_shop_6': 'media_1795359702120_3a7a051b.jpg',
    'flash_card_rows': 'media_1795361450176_f95d0c87.png',
}


def load_frames():
    frames = {}
    for key, filename in FILES.items():
        path = UPLOADED / filename
        if not path.exists():
            return None
        im = cv2.resize(cv2.imread(str(path)), (1280, 720), interpolation=cv2.INTER_CUBIC)
        frames[key] = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)
    return frames


FRAMES = load_frames()


class DummyDevice:
    def __init__(self, image):
        self.image = image.copy()
        self.has_cached_image = True
        self.click_record = []
        self.clicks = []
        self.drags = []
        self.on_click = None
        self.on_drag = None

    def screenshot(self):
        return self.image

    def click(self, button, record_check=True):
        self.clicks.append((button.name, button.button))
        if self.on_click:
            self.on_click(button)

    def drag(self, p1, p2, **kwargs):
        self.drags.append((p1, p2, kwargs.get('name')))
        if self.on_drag:
            self.on_drag(p1, p2)

    def stuck_record_clear(self):
        pass

    def stuck_record_add(self, button):
        pass

    def click_record_clear(self):
        self.click_record.clear()

    def click_record_check(self, button):
        return False


def paint_glow_at(image, yc):
    """Paint the glowing selection ring around `yc` and dim other rows."""
    out = image.copy()
    # Dim default IX glow at y=340..396
    out[135:570, 50:126] = np.minimum(out[135:570, 50:126], 60)
    out[yc - 20:yc + 21, 62:114] = [255, 220, 245]
    return out


def make_task(frame_key='season_diff', **cfg_overrides):
    task = ChaoszeroRogue.__new__(ChaoszeroRogue)
    task.device = DummyDevice(FRAMES[frame_key])
    defaults = dict(
        ChaoszeroRogue_RogueWorld='賽季卡厄思',
        ChaoszeroRogue_RogueSeasonDifficulty=8,
        ChaoszeroRogue_RogueSeasonSavePt='170pt',
        ChaoszeroRogue_RogueDreamMode='開啟',
        ChaoszeroRogue_RogueDistortionAdapt=True,
    )
    defaults.update(cfg_overrides)
    task.config = SimpleNamespace(**defaults)
    task.rogue_dump_unknown = Mock()
    task.rogue_state_save = Mock()
    task.rogue_state_load = Mock(return_value=None)
    return task


@unittest.skipIf(FRAMES is None, 'User Season Chaos screenshots not present')
class SeasonChaosTest(unittest.TestCase):
    def test_page_detection_across_all_screenshots(self):
        expected = {
            'lobby': ('lobby', False, False, False, False),
            'season_hub': ('season-hub', True, False, False, False),
            'season_diff': ('season-diff', False, True, False, False),
            'team_on': ('team', False, False, True, True),
            'team_off': ('team', False, False, True, True),
        }
        for key, (page, hub, diff, team, s_team) in expected.items():
            task = make_task(key)
            self.assertEqual(task._rogue_detect_entry_page(), page, key)
            self.assertEqual(task.rogue_season_hub_appear(), hub, key)
            self.assertEqual(task.rogue_season_diff_appear(), diff, key)
            self.assertEqual(task.rogue_team_appear(), team, key)
            self.assertEqual(task.rogue_season_team_appear(), s_team, key)
            self.assertTrue(task.rogue_outside_appear(), key)
            self.assertFalse(task._season_locked_popup_appear(), key)

        locked_task = make_task('locked')
        self.assertTrue(locked_task._season_locked_popup_appear())

    def test_dream_and_distortion_toggles(self):
        for key, dist_val in (('team_on', True), ('team_off', False)):
            task = make_task(key)
            self.assertIs(task.rogue_dream_state(), True, key)
            self.assertIs(task.rogue_distortion_state(), dist_val, key)

        task = make_task('team_off', ChaoszeroRogue_RogueDistortionAdapt=True)
        task.device.on_click = (
            lambda btn: setattr(task.device, 'image', FRAMES['team_on'].copy())
            if btn.name == 'ROGUE_DISTORTION' else None
        )
        self.assertTrue(task.rogue_distortion_set(True))
        self.assertEqual(len(task.device.clicks), 1)
        self.assertEqual(task.device.clicks[0][0], 'ROGUE_DISTORTION')

        task_on = make_task('team_on', ChaoszeroRogue_RogueDistortionAdapt=True)
        self.assertTrue(task_on.rogue_distortion_set(True))
        self.assertEqual(len(task_on.device.clicks), 0)

    def test_save_pt_ocr_and_reroll(self):
        task = make_task('season_diff')
        self.assertEqual(task.rogue_season_read_save_pt(), 170)

        task_off = make_task('season_diff', ChaoszeroRogue_RogueSeasonSavePt='關閉')
        self.assertEqual(task_off.rogue_season_parse_target_pt(), 0)
        self.assertTrue(task_off.rogue_season_reroll_pt(0))
        self.assertEqual(len(task_off.device.clicks), 0)

        state = {'pt': 130, 'clicks': 0}
        task_reroll = make_task('season_diff', ChaoszeroRogue_RogueSeasonSavePt='170pt')
        task_reroll.rogue_season_read_save_pt = lambda: state['pt']

        def fake_reroll_click(btn):
            if btn.name == 'ROGUE_SEASON_REROLL':
                state['clicks'] += 1
                state['pt'] = 150 if state['clicks'] == 1 else 170
                task_reroll.device.image[300:340, 900:1100] ^= state['clicks'] * 40

        task_reroll.device.on_click = fake_reroll_click
        self.assertTrue(task_reroll.rogue_season_reroll_pt(170))
        self.assertEqual(state['clicks'], 2)

        task_stuck = make_task('season_diff', ChaoszeroRogue_RogueSeasonSavePt='170pt')
        task_stuck.rogue_season_read_save_pt = lambda: 130
        with self.assertRaises(RequestHumanTakeover):
            task_stuck.rogue_season_reroll_pt(170)

    def test_difficulty_scroll_tap_and_locked_error(self):
        task = make_task('season_diff')
        task.wait_until_still = Mock(return_value=True)
        # Clear glow first so tapping (88, y) is exercised
        task.device.image = paint_glow_at(FRAMES['season_diff'], 369)
        self.assertEqual(task._season_glow_y(), 369)

        def on_click(btn):
            if btn.name == 'ROGUE_SEASON_DIFF':
                cy = (btn.button[1] + btn.button[3]) // 2
                if cy >= SEASON_TIER_Y[10] - 10:
                    task.device.image = FRAMES['locked'].copy()
                else:
                    task.device.image = paint_glow_at(FRAMES['season_diff'], cy)
            elif btn.name == 'ROGUE_SEASON_LOCKED_CLOSE':
                task.device.image = paint_glow_at(FRAMES['season_diff'], 369)

        task.device.on_click = on_click
        self.assertTrue(task.rogue_season_difficulty_set(8))
        self.assertEqual(task.device.drags[0][0], (88, 560))
        self.assertEqual(task._season_glow_y(), SEASON_TIER_Y[8])

        task.device.drags.clear()
        self.assertTrue(task.rogue_season_difficulty_set(3))
        self.assertEqual(task.device.drags[0][0], (88, 180))
        self.assertEqual(task._season_glow_y(), SEASON_TIER_Y[3])

        task.device.drags.clear()
        self.assertTrue(task.rogue_season_difficulty_set(6))
        self.assertEqual(len(task.device.drags), 4)
        self.assertEqual(task.device.drags[-1][0], (88, 450))
        self.assertEqual(task._season_glow_y(), SEASON_TIER_Y[6])

        # Locked difficulty dismisses overlay and raises RequestHumanTakeover
        with self.assertRaises(RequestHumanTakeover):
            task.rogue_season_difficulty_set(10)
        self.assertFalse(task._season_locked_popup_appear())

    def test_full_entry_chain_simulation_and_event_packs(self):
        self.assertIn('uk_404_s01', rogue_events.packs_for_world('賽季卡厄思'))
        task = make_task(
            'lobby',
            ChaoszeroRogue_RogueWorld='賽季卡厄思',
            ChaoszeroRogue_RogueSeasonDifficulty=8,
            ChaoszeroRogue_RogueSeasonSavePt='170pt',
            ChaoszeroRogue_RogueDreamMode='開啟',
            ChaoszeroRogue_RogueDistortionAdapt=False,
        )
        task.wait_until_still = Mock(return_value=True)
        stage = {'page': 'lobby'}

        def sim_click(btn):
            p = stage['page']
            if p == 'lobby':
                stage['page'] = 'season_hub'
                task.device.image = FRAMES['season_hub'].copy()
            elif p == 'season_hub':
                stage['page'] = 'season_diff'
                task.device.image = FRAMES['season_diff'].copy()
            elif p == 'season_diff':
                cx, cy = (btn.button[0] + btn.button[2]) // 2, (btn.button[1] + btn.button[3]) // 2
                if (cx, cy) == SEASON_DIFF_ENTER:
                    stage['page'] = 'team_on'
                    task.device.image = FRAMES['team_on'].copy()
                elif btn.name == 'ROGUE_SEASON_DIFF':
                    task.device.image = paint_glow_at(FRAMES['season_diff'], cy)
            elif p == 'team_on' and btn.name == 'ROGUE_DISTORTION':
                stage['page'] = 'team_off'
                task.device.image = FRAMES['team_off'].copy()

        task.device.on_click = sim_click
        self.assertTrue(task.rogue_enter_team(reselect_world=True))
        self.assertEqual(stage['page'], 'team_off')

    def test_season_popups_and_reward_list(self):
        for key in ('pure_white_mem', 'get_card_popup', 'get_buff_popup'):
            task = make_task(key)
            self.assertTrue(task.rogue_season_popup_appear(), key)
        for key in ('reward_list', 'season_map'):
            task = make_task(key)
            self.assertFalse(task.rogue_season_popup_appear(), key)

        reward_task = make_task('reward_list')
        primary = reward_task.rogue_primary_point()
        self.assertIsNotNone(primary)
        self.assertGreater(primary[0], 1000)

    def test_season_map_with_purple_enhancement_badges(self):
        image = FRAMES['season_map']
        nodes = rogue_route.read_nodes(image)
        edges = rogue_route.read_edges(image, nodes)
        self.assertEqual(len(nodes), 13)
        self.assertEqual(len(edges), 14)
        self.assertEqual(nodes[0].kind, rogue_route.KIND_BATTLE)
        elite = [n for n in nodes if n.tier == 5 and n.y < 400]
        self.assertEqual(len(elite), 1)
        self.assertEqual(elite[0].kind, rogue_route.KIND_ELITE)
        plan = rogue_route.plan(nodes, edges=edges)
        self.assertEqual(len(plan), 6)

        # Ensure a merged purple badge on an elite diamond is trimmed cleanly.
        glow_path = Path(__file__).parent / 'fixtures' / 'chaoszero' / 'rogue_route_glowing_preview.png'
        glow = cv2.cvtColor(cv2.imread(str(glow_path)), cv2.COLOR_BGR2RGB)
        badge = image[368 - 55:368 - 10, 341 + 18:341 + 49]
        bhsv = cv2.cvtColor(badge, cv2.COLOR_RGB2HSV).astype(np.int32)
        bmask = (bhsv[:, :, 2] > 60) & (bhsv[:, :, 1] > 40)
        glow[476 - 55 + 5:476 - 10 + 5, 341 + 18 - 6:341 + 49 - 6][bmask] = badge[bmask]
        merged_nodes = rogue_route.read_nodes(glow)
        tier0 = sorted((n for n in merged_nodes if n.tier == 0), key=lambda n: n.y)
        self.assertEqual([n.kind for n in tier0], ['event', 'elite', 'event'])

    def test_engrave_memory_card_stages(self):
        t1 = make_task('engrave_collapsed')
        self.assertEqual(t1.rogue_engrave_stage(), 1)
        t2 = make_task('engrave_expanded')
        self.assertEqual(t2.rogue_engrave_stage(), 2)
        for key in ('season_map', 'mem_choose_1', 'oath_two_cards'):
            self.assertEqual(make_task(key).rogue_engrave_stage(), 0, key)

    def test_memory_card_recognition_reroll_and_selection(self):
        expected_cards = {
            'mem_choose_1': ['記憶：貪婪', '記憶：怨懟', None],
            'mem_choose_2': ['記憶：貪婪', '記憶：渴望', '記憶：金光'],
            'mem_choose_3': ['記憶：女子', '記憶：王國', '記憶：萬花筒'],
            'mem_choose_4_sel': ['記憶：貪婪', '記憶：壓抑', '記憶：金光'],
            'mem_choose_5': ['記憶：喪失', '記憶：王國', '記憶：渴望'],
        }
        expected_reroll = {
            'mem_choose_1': [True, True, True],
            'mem_choose_2': [False, True, True],
            'mem_choose_3': [True, True, True],
            'mem_choose_4_sel': [False, False, False],
            'mem_choose_5': [True, False, False],
        }
        for key, cards in expected_cards.items():
            task = make_task(key)
            task.card_reader = None
            self.assertTrue(task.rogue_memory_choose_appear(), key)
            got = [task.rogue_memory_identify_card(c) for c in (1, 2, 3)]
            self.assertEqual(got, cards, key)
            rerolls = [task.rogue_memory_can_reroll(c) for c in (1, 2, 3)]
            self.assertEqual(rerolls, expected_reroll[key], key)

        press = Mock()
        press.reached.return_value = True

        cx = lambda btn: (btn[0] + btn[2]) // 2
        cy = lambda btn: (btn[1] + btn[3]) // 2

        # Reroll col 1 when target is missing and col 1 still has charges
        t_reroll_1 = make_task('mem_choose_1', ChaoszeroRogue_RogueSeasonMemoryCard='記憶：壓抑')
        t_reroll_1.card_reader = None
        t_reroll_1.core_started = True
        self.assertTrue(t_reroll_1.handle_rogue_memory_choose(press))
        self.assertEqual(t_reroll_1.device.clicks[-1][0], 'ROGUE_MEMORY_REROLL')
        self.assertEqual(cx(t_reroll_1.device.clicks[-1][1]), 320)

        # Skip col 1 (0/4) and reroll col 2 on mem_choose_2
        t_reroll_2 = make_task('mem_choose_2', ChaoszeroRogue_RogueSeasonMemoryCard='記憶：壓抑')
        t_reroll_2.card_reader = None
        t_reroll_2.core_started = True
        self.assertTrue(t_reroll_2.handle_rogue_memory_choose(press))
        self.assertEqual(t_reroll_2.device.clicks[-1][0], 'ROGUE_MEMORY_REROLL')
        self.assertEqual(cx(t_reroll_2.device.clicks[-1][1]), 640)

        # Select matching card (col 2), then confirm when primary button is orange
        t_match = make_task('mem_choose_4_sel', ChaoszeroRogue_RogueSeasonMemoryCard='記憶：壓抑')
        t_match.card_reader = None
        t_match.core_started = True
        self.assertTrue(t_match.handle_rogue_memory_choose(press))
        self.assertTrue(t_match.memory_card_matched)
        self.assertEqual(t_match.memory_selected_col, 2)
        self.assertEqual(t_match.device.clicks[-1][0], 'ROGUE_MEMORY_CARD')
        self.assertEqual(cx(t_match.device.clicks[-1][1]), 640)
        self.assertTrue(t_match.handle_rogue_memory_choose(press))
        self.assertEqual(t_match.device.clicks[-1][0], 'ROGUE_MEMORY_OK')
        self.assertEqual(cx(t_match.device.clicks[-1][1]), 1137)

        # Fallback when target not found and all columns are 0/4
        t_fallback = make_task('mem_choose_4_sel', ChaoszeroRogue_RogueSeasonMemoryCard='記憶：萬花筒')
        t_fallback.card_reader = None
        t_fallback.core_started = True
        self.assertTrue(t_fallback.handle_rogue_memory_choose(press))
        self.assertFalse(t_fallback.memory_card_matched)
        self.assertEqual(t_fallback.memory_selected_col, 1)
        self.assertEqual(t_fallback.device.clicks[-1][0], 'ROGUE_MEMORY_CARD')
        self.assertEqual(cx(t_fallback.device.clicks[-1][1]), 320)
        self.assertTrue(t_fallback.handle_rogue_memory_choose(press))
        self.assertEqual(t_fallback.device.clicks[-1][0], 'ROGUE_MEMORY_OK')

    def test_mandatory_memory_card_combatant_assignment_and_oath_confirm(self):
        press = Mock()
        press.reached.return_value = True
        cy = lambda btn: (btn[1] + btn[3]) // 2

        # Matched memory card -> pick RogueSeasonMemoryMember slot 2, then confirm once orange
        t_ok = make_task(
            'mem_assign_member',
            ChaoszeroRogue_RogueSeasonMemoryMember=2,
            ChaoszeroRogue_RogueSeasonMemoryFallbackMember=3,
        )
        t_ok.memory_card_matched = True
        t_ok.rogue_card_page_record = Mock()
        t_ok.rogue_primary_point = Mock(side_effect=[None, (1137, 669)])
        self.assertTrue(t_ok.handle_rogue_card_reward(press))
        self.assertEqual(t_ok.device.clicks[-1][0], 'ROGUE_MEMORY_ASSIGN_MEMBER')
        self.assertEqual(cy(t_ok.device.clicks[-1][1]), 352)
        self.assertTrue(t_ok.handle_rogue_card_reward(press))
        self.assertEqual(t_ok.device.clicks[-1][0], 'ROGUE_MEMORY_ASSIGN_OK')

        # Unmatched memory card -> pick RogueSeasonMemoryFallbackMember slot 3, then confirm
        t_fb = make_task(
            'mem_assign_member',
            ChaoszeroRogue_RogueSeasonMemoryMember=2,
            ChaoszeroRogue_RogueSeasonMemoryFallbackMember=3,
        )
        t_fb.memory_card_matched = False
        t_fb.rogue_card_page_record = Mock()
        t_fb.rogue_primary_point = Mock(side_effect=[None, (1137, 669)])
        self.assertTrue(t_fb.handle_rogue_card_reward(press))
        self.assertEqual(t_fb.device.clicks[-1][0], 'ROGUE_MEMORY_ASSIGN_MEMBER')
        self.assertEqual(cy(t_fb.device.clicks[-1][1]), 489)
        self.assertTrue(t_fb.handle_rogue_card_reward(press))
        self.assertEqual(t_fb.device.clicks[-1][0], 'ROGUE_MEMORY_ASSIGN_OK')

        # Two Oaths and Floor-2 corridor continuation are handled cleanly by primary button
        for key, min_x in (('oath_two_cards', 1100), ('corridor_continue', 1100)):
            task = make_task(key)
            self.assertFalse(task.rogue_season_popup_appear(), key)
            self.assertFalse(task.rogue_memory_choose_appear(), key)
            self.assertFalse(task.rogue_card_reward_appear(), key)
            self.assertEqual(task.rogue_engrave_stage(), 0, key)
            pt = task.rogue_primary_point()
            self.assertIsNotNone(pt, key)
            self.assertGreater(pt[0], min_x, key)

    def test_sculpt_entry_workshop_popups_and_floor3_transition(self):
        press = Mock()
        press.reached.return_value = True
        center = lambda btn: ((btn[0] + btn[2]) // 2, (btn[1] + btn[3]) // 2)

        # 1. `sculpt_1_entry`: collapsed left card `雕琢記憶` (shards=5), expanded stage 2, and exit when done
        t_entry = make_task('sculpt_1_entry')
        t_entry.card_reader = None
        self.assertEqual(t_entry.rogue_memory_shard_count(), 5)
        self.assertEqual(t_entry.rogue_sculpt_entry_stage(), 1)
        self.assertTrue(t_entry.handle_rogue_sculpt_entry(press))
        self.assertEqual(t_entry.device.clicks[-1][0], 'ROGUE_SCULPT_ENTRY')
        self.assertEqual(center(t_entry.device.clicks[-1][1]), SCULPT_CARD_POINT)

        # When already sculpted (`sculpt_done=True`), choose right-hand `離開` card instead
        t_entry.sculpt_done = True
        self.assertIsNone(t_entry.rogue_option_check_point(SCULPT_EXIT_CARD_POINT[0]))
        self.assertTrue(t_entry.handle_rogue_sculpt_entry(press))
        self.assertEqual(t_entry.device.clicks[-1][0], 'ROGUE_SCULPT_EXIT')
        self.assertEqual(center(t_entry.device.clicks[-1][1]), SCULPT_EXIT_CARD_POINT)

        # Synthetic expanded left card (-44px) + white confirmation checkmark
        expanded_img = FRAMES['sculpt_1_entry'].copy()
        expanded_img[510:555, 320:430] = FRAMES['sculpt_1_entry'][554:599, 320:430]
        expanded_img[555:605, 320:430] = 0
        expanded_img[678:698, 458:486] = 245
        t_exp = make_task('sculpt_1_entry')
        t_exp.device.image = expanded_img
        t_exp.card_reader = None
        self.assertEqual(t_exp.rogue_sculpt_entry_stage(), 2)
        self.assertTrue(t_exp.handle_rogue_sculpt_entry(press))
        self.assertEqual(center(t_exp.device.clicks[-1][1]), SCULPT_CONFIRM_POINT)

        # 2. `sculpt_2_workshop`: sculpts using right button (`記憶雕琢`), leaves when shards == 0
        t_work = make_task('sculpt_2_workshop')
        t_work.card_reader = None
        self.assertTrue(t_work.rogue_sculpt_workshop_appear())
        self.assertEqual(t_work.rogue_memory_shard_count(), 5)
        self.assertTrue(t_work.rogue_sculpt_available())
        self.assertTrue(t_work.handle_rogue_sculpt_workshop(press))
        self.assertEqual(t_work.device.clicks[-1][0], 'ROGUE_SCULPT_ACTION')
        self.assertEqual(center(t_work.device.clicks[-1][1]), SCULPT_BTN_POINT)

        zero_shard_img = FRAMES['sculpt_2_workshop'].copy()
        zero_shard_img[24:56, 740:795] = FRAMES['sculpt_5_corridor'][24:56, 740:795]
        t_empty = make_task('sculpt_2_workshop')
        t_empty.device.image = zero_shard_img
        t_empty.card_reader = None
        self.assertEqual(t_empty.rogue_memory_shard_count(), 0)
        self.assertFalse(t_empty.rogue_sculpt_available())
        self.assertTrue(t_empty.handle_rogue_sculpt_workshop(press))
        self.assertTrue(t_empty.sculpt_done)
        self.assertEqual(t_empty.device.clicks[-1][0], 'ROGUE_SCULPT_LEAVE')
        self.assertEqual(center(t_empty.device.clicks[-1][1]), SCULPT_LEAVE_POINT)

        # 3. `sculpt_3_compare` & `sculpt_4_popup`: `雕琢成功` banner + center-bottom close/confirm
        for key in ('sculpt_3_compare', 'sculpt_4_popup'):
            task = make_task(key)
            self.assertTrue(task.rogue_season_popup_appear(), key)
        cx, cy = SEASON_POPUP_CLOSE
        self.assertTrue(475 <= cx <= 804 and 640 <= cy <= 694)
        btn_patch = FRAMES['sculpt_3_compare'][cy - 20:cy + 20, cx - 80:cx + 80].astype(int)
        orange_ratio = ((btn_patch[:, :, 0] > 200) & (btn_patch[:, :, 1] > 110)
                        & (btn_patch[:, :, 1] < 185) & (btn_patch[:, :, 2] < 80)).mean()
        self.assertGreater(orange_ratio, 0.5)

        # 4. `sculpt_5_corridor` & `checkpoint_continue`: primary button `結算` / `繼續進行`
        for key in ('sculpt_5_corridor', 'checkpoint_continue'):
            task = make_task(key)
            pt = task.rogue_primary_point()
            self.assertIsNotNone(pt, key)
            self.assertGreater(pt[0], 1100, key)

        # 5. `floor2_end_memory_end`: `為記憶的盡頭` detected (no false match elsewhere)
        t_end = make_task('floor2_end_memory_end')
        self.assertTrue(t_end.rogue_memory_end_appear())
        for key in ('sculpt_5_corridor', 'checkpoint_continue', 'oath_two_cards'):
            self.assertFalse(make_task(key).rogue_memory_end_appear(), key)

        # 6. `floor2_end_map`: 2D preview diamonds stay classified without errors
        map_img = FRAMES['floor2_end_map']
        self.assertEqual(rogue_route.icon_kind(map_img, 477, 260), rogue_route.KIND_REST)
        self.assertEqual(rogue_route.icon_kind(map_img, 641, 476), rogue_route.KIND_BEACON)

    def test_season_safe_area_detection_and_meditate_disabled(self):
        t_rest = make_task('season_rest')
        self.assertTrue(t_rest.rogue_rest_appear())
        self.assertFalse(t_rest.rogue_meditate_available())
        self.assertIsNotNone(t_rest.rogue_secondary_point())

        for unknown_name in ('unknown_224002.png', 'unknown_224006.png', 'unknown_224011.png'):
            path = Path('log/rogue_pages') / unknown_name
            if path.exists():
                t_unknown = make_task('season_rest')
                t_unknown.device.image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
                self.assertTrue(t_unknown.rogue_rest_appear(), unknown_name)
                self.assertFalse(t_unknown.rogue_meditate_available(), unknown_name)

        # Ensure non-rest screenshots do not false-match at similarity=0.82
        for key in ('season_map', 'sculpt_2_workshop', 'reward_list', 'oath_two_cards'):
            self.assertFalse(make_task(key).rogue_rest_appear(), key)

        # Shop truck feature (`ROGUE_REST_SHOP`) across all 6 swaying frames vs non-shop frames
        press = Mock()
        press.reached.return_value = True

        def setup_shop_task(frame_key):
            t = make_task(frame_key)
            t.shop_cooldown = Mock()
            t.shop_cooldown.reached.return_value = True
            t.shop_retry = 0
            t.remove_done = 0
            t.rogue_shop_remove_needed = Mock(return_value=True)
            t.rogue_delete_times = Mock(return_value=3)
            t.equipment = Mock()
            t.equipment.shop_target_slots.return_value = []
            return t

        for i in range(1, 7):
            key = f'season_rest_shop_{i}'
            t_shop = setup_shop_task(key)
            self.assertTrue(t_shop.rogue_rest_appear(), key)
            self.assertTrue(t_shop.rogue_meditate_available(), key)
            self.assertTrue(t_shop.rogue_visit_rest_shop(press), key)
            self.assertEqual(t_shop.device.clicks[-1][0], 'ROGUE_REST_SHOP')
            btn = t_shop.device.clicks[-1][1]
            cx = (btn[0] + btn[2]) // 2
            cy = (btn[1] + btn[3]) // 2
            self.assertTrue(400 <= cx <= 650 and 140 <= cy <= 280, (key, cx, cy))

        t_noshop = setup_shop_task('season_rest')
        self.assertFalse(t_noshop.rogue_visit_rest_shop(press))
        for unknown_name in ('unknown_224002.png', 'unknown_224006.png', 'unknown_224011.png'):
            path = Path('log/rogue_pages') / unknown_name
            if path.exists():
                t_unk = setup_shop_task('season_rest')
                t_unk.device.image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
                self.assertFalse(t_unk.rogue_visit_rest_shop(press), unknown_name)

    def test_flash_card_picker_with_per_character_rows(self):
        task = make_task('flash_card_rows')
        self.assertTrue(task.rogue_flash_card_appear())
        points = task.rogue_flash_card_points()
        self.assertEqual(len(points), 6)
        self.assertEqual([p[0] for p in points[:2]], [449, 664])
        self.assertTrue(all(p[4] >= 188 for p in points[:2]))
        self.assertEqual(len(task._flash_points_merged()), 6)

        med_path = Path('log/rogue_card_pages/meditate/231840.png')
        if med_path.exists():
            t_med = make_task('flash_card_rows')
            t_med.device.image = cv2.cvtColor(cv2.imread(str(med_path)), cv2.COLOR_BGR2RGB)
            t_med.card_reader = None
            t_med.rogue_spark_filter = lambda: {'一縷光芒': ['3']}
            t_med.rogue_member_spark_cards = lambda: None
            t_med.meditate_pending = ['一縷光芒']
            picked = t_med.rogue_meditate_card()
            self.assertIsNotNone(picked)
            self.assertEqual(picked[1], '一縷光芒')
            self.assertGreaterEqual(picked[2], 0.60)


if __name__ == '__main__':
    unittest.main()
