import unittest
from unittest.mock import Mock, call, patch

from module.base.utils import load_image
from module.config import server
from module.exception import TaskFailed


class TestResonanceShop(unittest.TestCase):
    def setUp(self):
        self.addCleanup(server.set_server, server.server)
        server.set_server('resonance')

    def test_currency_is_checked_again_after_selecting_maximum(self):
        from module.resonance import assets
        from module.resonance.shop import GOLD_BALANCE, GOLD_TOTAL, QUANTITY, ResonanceShop

        modal = sum(load_image(button.file) for button in (
            assets.SHOP_MODAL_PRICE, assets.SHOP_MAX, assets.SHOP_CANCEL, assets.SHOP_CONFIRM,
        ))
        gold = modal.copy()
        gold[442:465, 605:628] = assets.TEMPLATE_SHOP_MODAL_GOLD.image
        purple = modal.copy()
        purple[435:473, 596:636] = assets.TEMPLATE_SHOP_MODAL_TICKET.image
        mixed = gold.copy()
        mixed[435:473, 740:780] = assets.TEMPLATE_SHOP_MODAL_TICKET.image

        for initial, after, clicks in (
            (gold, gold, [assets.SHOP_MAX, assets.SHOP_CONFIRM]),
            (gold, purple, [assets.SHOP_MAX]),
            (purple, purple, []),
            (mixed, mixed, []),
            (modal, modal, []),
        ):
            with self.subTest(clicks=clicks):
                task = ResonanceShop.__new__(ResonanceShop)
                task.device = Mock()
                task.device.image = initial
                task.interval_timer = {}
                task.ui_click = Mock()
                task.wait_for_purchase = Mock(return_value=True)
                balance = task.image_crop(GOLD_BALANCE)

                def screenshot():
                    task.device.image = after

                task.device.screenshot.side_effect = screenshot
                with patch.object(QUANTITY, 'ocr', side_effect=['1/10', '10/10']):
                    result = task.confirm_item(None, balance)
                self.assertEqual(task.device.click.call_args_list, [call(button) for button in clicks])
                if assets.SHOP_CONFIRM in clicks:
                    self.assertTrue(result)
                    task.wait_for_purchase.assert_called_once()
                    before, total = task.wait_for_purchase.call_args[0]
                    self.assertIs(before, balance)
                    self.assertEqual(total.shape[:2], (GOLD_TOTAL[3] - GOLD_TOTAL[1], GOLD_TOTAL[2] - GOLD_TOTAL[0]))
                    task.ui_click.assert_not_called()
                else:
                    self.assertFalse(result)
                    task.wait_for_purchase.assert_not_called()
                    self.assertIs(task.ui_click.call_args[0][0], assets.SHOP_CANCEL)

    def test_allow_and_exclude_lists_apply_to_gold_items(self):
        from module.resonance import assets
        from module.resonance.shop import ResonanceShop, filter_names

        task = ResonanceShop.__new__(ResonanceShop)
        task.device = Mock()
        task.device.image = load_image(assets.SHOP_HQ.file) + load_image(assets.SHOP_BATCH_OFF.file)
        for y in (231, 362, 493):
            task.device.image[y:y + 19, 823:842] = assets.TEMPLATE_SHOP_LIST_GOLD.image
        task.read_name = Mock(side_effect=['空白录像带', '拉普拉斯协议', '本源之弦'])
        task.buy_item = Mock()
        include = filter_names(' 空白录像带、拉普拉斯协议\n星云物质（4钛）')
        exclude = filter_names('拉普拉斯协议')
        self.assertEqual(filter_names(None), set())
        self.assertIn('星云物质(4钛)', include)
        task.buy_visible(include, exclude)
        task.buy_item.assert_called_once()
        self.assertEqual(task.buy_item.call_args[0][0], '空白录像带')
        self.assertEqual(task.device.click.call_count, 1)

    def test_missing_reward_popup_checks_gold_without_resubmitting(self):
        from module.resonance import assets
        from module.resonance.shop import GOLD_BALANCE, GOLD_TOTAL, MONEY, ResonanceShop

        for amounts, expected in (
            (['100000', '80000', '20000'], True),
            (['100000', '80000', '100000'], False),
            (['100000', '80000', '50000'], None),
        ):
            with self.subTest(amounts=amounts):
                task = ResonanceShop.__new__(ResonanceShop)
                task.device = Mock()
                task.device.image = load_image(assets.SHOP_HQ.file)
                task.config = Mock()
                task.loop = Mock(return_value=iter(()))
                task.purchase_list_ready = Mock(return_value=True)
                balance, total = task.image_crop(GOLD_BALANCE), task.image_crop(GOLD_TOTAL)
                with patch.object(MONEY, 'ocr', return_value=amounts):
                    if expected is None:
                        with self.assertRaises(TaskFailed):
                            task.wait_for_purchase(balance, total)
                        task.config.task_delay.assert_called_once_with(server_update=True)
                    else:
                        self.assertIs(task.wait_for_purchase(balance, total), expected)
                        task.config.task_delay.assert_not_called()
                task.device.click.assert_not_called()

    def test_another_order_requires_a_changed_stock_display(self):
        from module.resonance import assets
        from module.resonance.shop import ResonanceShop

        task = ResonanceShop.__new__(ResonanceShop)
        task.device = Mock()
        task.device.image = load_image(assets.SHOP_HQ.file) + load_image(assets.SHOP_BATCH_OFF.file)
        task.device.image[231:250, 823:842] = assets.TEMPLATE_SHOP_LIST_GOLD.image
        task.device.image[170:183, 853:892] = 200

        def update_stock(name, balance):
            task.device.image[170:183, 853:865] = 0
            return True

        task.buy_item = Mock(side_effect=update_stock)
        task.buy_visible(set(), set())
        self.assertEqual(task.buy_item.call_count, 2)
        self.assertEqual(task.device.click.call_count, 2)
