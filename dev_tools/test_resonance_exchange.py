import unittest
from unittest.mock import Mock, call, patch

from module.base.utils import load_image
from module.config import server
from module.config.config_generated import GeneratedConfig
from module.exception import TaskFailed


class TestResonanceExchange(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_only_a_named_offer_can_be_confirmed(self):
        from module.resonance import assets
        from module.resonance.exchange import QUANTITY, ResonanceExchange
        from module.resonance.shop import filter_names

        controls = load_image(assets.SHOP_MAX.file) + load_image(assets.SHOP_CONFIRM.file)
        arrow = load_image(assets.EXCHANGE_MODAL_ARROW.file)
        modal = controls + arrow
        multi_material = controls.copy()
        multi_material[211:287, 734:815] = arrow[211:287, 600:681]
        defaults = GeneratedConfig.ResonanceExchange_Include
        for name, included, accepted, frame, quantities in (
            ('进货采买书', defaults, True, modal, ['1/5', '5/5']),
            ('追加注资申请书', defaults, True, modal, ['1/1']),
            ('自观测胶卷', defaults, False, modal, []),
            ('自观测胶卷', defaults + '\n自观测胶卷', True, modal, ['1/5', '5/5']),
            ('仓库扩建许可证', defaults + '\n仓库扩建许可证', True, multi_material, ['1/1']),
        ):
            with self.subTest(name=name, accepted=accepted):
                task = ResonanceExchange.__new__(ResonanceExchange)
                task.device = Mock()
                task.device.image = frame
                task.interval_timer = {}
                task.wait_until_appear = Mock(return_value=True)
                task.ui_click = Mock()
                task.finish_exchange = Mock()
                task.read_offer_name = Mock(return_value=name)
                wanted = filter_names(included)
                with patch.object(QUANTITY, 'ocr', side_effect=quantities):
                    task.exchange_offer(wanted)
                self.assertNotIn(name, wanted)
                if accepted:
                    expected_clicks = [call(assets.SHOP_MAX)] if len(quantities) > 1 else []
                    self.assertEqual(task.device.click.call_args_list, expected_clicks + [call(assets.SHOP_CONFIRM)])
                    task.finish_exchange.assert_called_once_with(name)
                else:
                    task.device.click.assert_not_called()
                    self.assertIs(task.ui_click.call_args[0][0], assets.SHOP_CANCEL)

    def test_reward_popup_is_dismissed_without_more_confirmations(self):
        from module.resonance import assets
        from module.resonance.exchange import ResonanceExchange

        task = ResonanceExchange.__new__(ResonanceExchange)
        task.device = Mock()
        task.interval_timer = {}
        frames = iter([load_image(assets.LOGIN_REWARD.file), load_image(assets.EXCHANGE_HUB.file)])

        def screenshot():
            task.device.image = next(frames)

        task.device.screenshot.side_effect = screenshot
        task.finish_exchange('进货采买书')
        task.device.click.assert_called_once_with(assets.LOGIN_REWARD)

    def test_unresolved_exchange_never_resubmits(self):
        from module.resonance.exchange import ResonanceExchange

        task = ResonanceExchange.__new__(ResonanceExchange)
        task.device = Mock()
        task.config = Mock()
        task.loop = Mock(return_value=iter(()))
        task.appear = Mock(return_value=False)
        with self.assertRaises(TaskFailed):
            task.finish_exchange('追加注资申请书')
        task.device.click.assert_not_called()
        task.config.task_delay.assert_called_once_with(server_update=True)
