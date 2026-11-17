"""Equipment assignment shared by event rewards and shop purchases."""

import gzip
import json
import os
import re

import cv2
import numpy as np

from module.base.timer import Timer
from module.chaoszero import rogue_cards
from module.chaoszero.assets import (ROGUE_EQUIP_EMPTY_SLOTS, ROGUE_EQUIP_SALVAGE, ROGUE_EQUIP_SALVAGE_CONFIRM,
                                   ROGUE_SHOP_EQUIPMENT_TYPES, ROGUE_SHOP_REFRESH_CONFIRM,
                                   ROGUE_SHOP_REFRESH_PAID)
from module.exception import TaskFailed
from module.logger import logger
from module.ocr.ocr import Ocr


ROOT = os.path.dirname(__file__)
SLOT_X = (971, 1062, 1153)
ROW_Y = (231, 391, 551)
SHOP_FREE_REFRESH_COUNT = Ocr((370, 651, 392, 695), alphabet='0123456789', name='ROGUE_SHOP_FREE_REFRESH_COUNT')
SHOP_EQUIPMENT_ICONS = ((124, 508, 155, 539), (375, 532, 406, 563), (874, 527, 905, 558))


def key(text):
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', (text or '').lower())


class RelicLibrary:
    def __init__(self):
        with gzip.open(os.path.join(ROOT, 'rogue_relics.json.gz'), 'rt', encoding='utf-8') as stream:
            data = json.load(stream)
        self.items = data['items']
        self.characters = data['characters']
        # Wiki 有同名同部位同唯一属性的多个来源版本，按同一种装备识别。
        groups = {}
        for item in self.items:
            signature = (key(item['name']), item['slot'], item['unique'])
            if signature not in groups:
                groups[signature] = dict(item, aliases=[])
            groups[signature]['aliases'].extend(self.aliases(item))
        self.item_index = list(groups.values())
        self.faces = None

    @staticmethod
    def aliases(record):
        return [record['id'], record['name']] + list(record.get('names', {}).values()) + record.get('aliases', [])

    def lookup(self, text, characters=False, fuzzy=False):
        table = self.characters if characters else self.item_index
        exact = [r for r in table if key(text) in {key(a) for a in self.aliases(r)}]
        if len(exact) == 1:
            return exact[0]
        if not fuzzy or not rogue_cards.normalize(text):
            return None
        ranked = sorted([(max(rogue_cards.name_score(text, a) for a in self.aliases(r)), r)
                         for r in table], key=lambda pair: pair[0], reverse=True)
        if ranked[0][0] >= 0.75 and ranked[0][0] - ranked[1][0] >= 0.08:
            return ranked[0][1]
        return None

    def rules(self, text):
        result = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                raise ValueError('Equipment rule requires 装备名 = 角色名: ' + line)
            equipment, character = line.split('=', 1)
            item = self.lookup(equipment.strip())
            actor = self.lookup(character.strip(), characters=True)
            if item is None or actor is None:
                raise ValueError('Unknown equipment or character: ' + line)
            if item['id'] in result and result[item['id']] != actor['id']:
                raise ValueError('Conflicting equipment recipient: ' + line)
            result[item['id']] = actor['id']
        return result

    def identify_characters(self, image):
        sift = cv2.SIFT_create(nfeatures=300, contrastThreshold=0.02)
        if self.faces is None:
            self.faces = []
            with np.load(os.path.join(ROOT, 'rogue_equipment_faces.npz'), allow_pickle=False) as archive:
                for character in self.characters:
                    face = cv2.imdecode(archive[character['id']], cv2.IMREAD_GRAYSCALE)
                    points, descriptors = sift.detectAndCompute(face, None)
                    self.faces.append((character, points, descriptors))
        identities = []
        for row in range(3):
            grey = cv2.cvtColor(image[147 + row * 160:286 + row * 160, 803:930], cv2.COLOR_RGB2GRAY)
            points, descriptors = sift.detectAndCompute(grey, None)
            ranked = []
            if descriptors is not None:
                for character, ref_points, ref in self.faces:
                    if ref is None or len(ref) < 2:
                        continue
                    pairs = cv2.BFMatcher().knnMatch(descriptors, ref, k=2)
                    good = [a for a, b in pairs if a.distance < 0.7 * b.distance]
                    inliers = 0
                    if len(good) >= 4:
                        src = np.float32([points[m.queryIdx].pt for m in good])
                        dst = np.float32([ref_points[m.trainIdx].pt for m in good])
                        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3)
                        inliers = int(mask.sum()) if mask is not None else 0
                    ranked.append((inliers, character))
            ranked.sort(key=lambda pair: pair[0], reverse=True)
            actor = None
            if len(ranked) >= 2 and ranked[0][0] >= 8 and ranked[0][0] - ranked[1][0] >= 4:
                actor = ranked[0][1]['id']
            identities.append(actor)
        # 同一角色不能占两个队伍位，重复结果不能拿来执行指定规则。
        return [actor if actor and identities.count(actor) == 1 else None for actor in identities]


class Equipment:
    def __init__(self, task):
        self.task = task
        self.library = RelicLibrary()
        node = task.config.data.get('ChaoszeroRogue', {})
        node = node.get('ChaoszeroRogue') or node
        self.rules = self.library.rules(str(node.get('RogueEquipFilter') or ''))
        self.reader = rogue_cards.CardReader()
        self.page = None
        self.shop_context = None
        self.shop_seen = set()
        self.shop_refresh = None
        self.shop_refresh_confirmed = False
        self.shop_templates = None
        self.empty_template = None
        self.list_tries = 0
        self.list_wait = None
        self.shop_opening = None

    def fail(self, message):
        self.task.rogue_dump_unknown()
        raise TaskFailed(message)

    def wait_for_read(self, reason):
        if self.page is None:
            self.page = {'identity': None, 'phase': 'read'}
        if 'read_wait' not in self.page:
            self.page['read_wait'] = Timer(6, count=1).start()
            logger.info('Wait for %s to become readable' % reason)
        elif self.page['read_wait'].reached():
            self.fail('%s could not be read, stop for review' % reason.capitalize())
        return True

    def empty_slots(self, image):
        if self.empty_template is None:
            source = cv2.imread(ROGUE_EQUIP_EMPTY_SLOTS.file, cv2.IMREAD_GRAYSCALE)
            if source is None:
                self.fail('Equipment empty-slot template is missing')
            self.empty_template = [source[206:257, 945 + 91 * col:998 + 91 * col] for col in range(3)]
        grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        return [[float(cv2.matchTemplate(grey[206 + 160 * row:257 + 160 * row,
                                                945 + 91 * col:998 + 91 * col], template,
                                         cv2.TM_CCOEFF_NORMED).max()) >= 0.90
                 for col, template in enumerate(self.empty_template)] for row in range(3)]

    @staticmethod
    def selected_row(image):
        selected = []
        for row in range(3):
            patch = image[159 + 160 * row:272 + 160 * row, 776:781].astype(int)
            red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
            gold = (red > 180) & (green > 105) & (blue < 215) & (red > green * 1.02)
            if int(gold.sum()) >= 60:
                selected.append(row)
        return selected[0] if len(selected) == 1 else None

    def recipients(self, item, image):
        preferred = self.rules.get(item['id'])
        if preferred:
            actors = self.library.identify_characters(image)
            if any(actor is None for actor in actors):
                self.fail('Equipment character recognition is uncertain, stop before assigning or salvaging')
            return [r for r, actor in enumerate(actors) if actor == preferred]
        empty = self.empty_slots(image)
        return [r for r in range(3) if empty[r][item['slot']]]

    def salvage_point(self):
        if self.task.appear(ROGUE_EQUIP_SALVAGE, offset=(300, 5), similarity=.90):
            x1, y1, x2, y2 = ROGUE_EQUIP_SALVAGE.button
            return (x1 + x2) // 2, (y1 + y2) // 2
        return None

    def no_recipient(self, shop):
        if shop:
            self.task.tap_point(465, 670, name='ROGUE_EQUIP_CANCEL')
            self.page['phase'] = 'submitted'
            self.page['wait'] = Timer(6, count=1).start()
        else:
            point = self.salvage_point()
            if point is None:
                self.wait_for_read('equipment salvage button')
                return
            self.page['salvage'] = True
            self.task.tap_point(*point, name='ROGUE_EQUIP_SALVAGE')
            self.page['phase'] = 'submitted'
            self.page['wait'] = Timer(6, count=1).start()

    def list_items(self, image):
        art = image[130:620, 320:480]
        mask = ((art.max(axis=2) > 65) & (np.ptp(art, axis=2) > 35)).astype('uint8') * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), 'uint8'))
        candidates = []
        for x, y, width, height, _ in cv2.connectedComponentsWithStats(mask, connectivity=8)[2][1:]:
            if not (90 <= width <= 170 and 150 <= height <= 260):
                continue
            # 提示可能遮住卡面顶部，用底边定位标题；部分装备没有放大镜。
            cy = int(y + height) + 130 - 198
            _, item = self.read_item(image, (525, cy - 17, 890, cy + 20))
            if item:
                candidates.append((cy, item))
        candidates.sort(key=lambda pair: (pair[1]['id'] not in self.rules, pair[0]))
        return candidates

    def read_item(self, image, area):
        text = self.reader.read_name(image, area, scale=1.5, raw=True)
        item = self.library.lookup(text, fuzzy=True)
        if item is None:
            # 紫色装备名转普通灰度对比不足，保留最亮色通道再读一次。
            crop = image[area[1]:area[3], area[0]:area[2]].max(axis=2)
            bright = np.repeat(crop[:, :, None], 3, axis=2)
            alternative = self.reader.read_name(bright, (0, 0, bright.shape[1], bright.shape[0]), scale=1.2, raw=True)
            match = self.library.lookup(alternative, fuzzy=True)
            if match:
                return alternative, match
        return text, item

    @staticmethod
    def list_selected(image, cy):
        patch = image[cy - 22:cy + 8, 311:341]
        red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
        orange = (red > 220) & (green > 65) & (green < 180) & (blue < 100)
        white = (red > 235) & (green > 235) & (blue > 235)
        return int(orange.sum()) >= 250 and int(white.sum()) >= 20

    def handle(self, press):
        task = self.task
        if task.appear(ROGUE_SHOP_REFRESH_CONFIRM, offset=(8, 8), similarity=.90):
            state = self.page
            if self.shop_refresh is None and state and state.get('shop_refresh_recheck'):
                if state['wait'].reached():
                    self.fail('Shop refresh dialog could not be cancelled, stop for review')
                return True
            if self.shop_refresh is not None and self.shop_refresh[1].reached():
                self.fail('Shop refresh confirmation did not close, stop for review')
            if not press.reached():
                return True
            if self.shop_refresh is None:
                # 重启后看不到原来的免费判定，取消弹窗再检查完整商店页。
                press.reset()
                task.tap_point(435, 454, name='ROGUE_SHOP_REFRESH_RECHECK')
                self.page = {'identity': None, 'phase': 'recheck', 'shop_refresh_recheck': True,
                             'wait': Timer(6, count=1).start()}
            elif not self.shop_refresh_confirmed:
                point = task.rogue_confirm_point((630, 420, 1060, 495), size=((300, 440), (35, 80)))
                if point:
                    press.reset()
                    task.tap_point(*point, name='ROGUE_SHOP_REFRESH_CONFIRM')
                    self.shop_refresh_confirmed = True
                    self.shop_refresh = (self.shop_refresh[0], Timer(6, count=1).start())
            return True
        if self.shop_refresh is not None:
            if task.rogue_shop_appear() or task.rogue_shop_sold_appear():
                return False
            if self.shop_refresh[1].reached():
                self.fail('Shop free refresh did not return to the shop, stop for review')
            return True
        if task.appear(ROGUE_EQUIP_SALVAGE_CONFIRM, offset=(8, 8), similarity=0.90):
            state = self.page
            if state and state.get('wait') is not None and state['wait'].reached():
                self.fail('Equipment salvage dialog did not close, stop for review')
            if not press.reached() or (state and (state.get('salvage_confirmed') or state['phase'] == 'recheck')):
                return True
            if state and state.get('salvage'):
                point = task.rogue_confirm_point((630, 420, 1060, 495), size=((300, 440), (35, 80)))
                if point:
                    press.reset()
                    task.tap_point(*point, name='ROGUE_EQUIP_SALVAGE_CONFIRM')
                    state['salvage_confirmed'] = True
                    state['wait'] = Timer(6, count=1).start()
            else:
                # 重启后先取消弹窗；被弹窗遮住的槽位不能用来重新判断是否应提炼。
                press.reset()
                task.tap_point(435, 454, name='ROGUE_EQUIP_SALVAGE_RECHECK')
                self.page = {'identity': None, 'phase': 'recheck', 'wait': Timer(6, count=1).start()}
            return True
        if not task.rogue_equip_appear():
            self.page = None
            self.list_tries = 0
            self.list_wait = None
            if self.shop_opening is not None:
                if self.shop_opening.reached():
                    self.shop_opening = None
                    if task.rogue_shop_appear() or task.rogue_shop_sold_appear():
                        return False
                    self.fail('Unknown shop equipment preview, stop for review')
                return True
            return False
        if not press.reached():
            return True
        from_shop = self.shop_opening is not None
        self.shop_opening = None
        image = task.device.image
        prompt = self.reader.read_name(image, (1000, 78, 1275, 120), scale=1.5)
        if '請選擇裝備' in prompt:
            if self.list_wait is not None:
                if self.list_wait.reached():
                    self.fail('Equipment reward did not open assignment after confirmation, stop for review')
                return True
            cards = self.list_items(image)
            if cards:
                self.page = None
                if self.list_selected(image, cards[0][0]):
                    point = task.rogue_confirm_point((630, 630, 1275, 705), size=((200, 380), (35, 80)))
                    if point:
                        press.reset()
                        task.tap_point(*point, name='ROGUE_EQUIP_CHOOSE')
                        self.list_wait = Timer(6, count=1).start()
                    return True
                if self.list_tries >= 3:
                    self.fail('Equipment selection did not open assignment, stop for review')
                press.reset()
                self.list_tries += 1
                task.tap_point(420, cards[0][0] + 65, name='ROGUE_EQUIP_ITEM')
                return True
            return self.wait_for_read('equipment reward list')
        if '請選擇戰鬥員' not in prompt:
            return self.wait_for_read('equipment page prompt')
        self.list_tries = 0
        self.list_wait = None
        cancel = self.reader.read_name(image, (445, 650, 520, 690), scale=1.5)
        if from_shop or (self.page and self.page['identity'] and self.page['identity'][1]) or cancel == '取消':
            shop = True
        elif self.salvage_point() is not None:
            shop = False
        else:
            # 没读到“取消”不能推断是事件页，否则可能误买未配置的商店装备。
            return self.wait_for_read('equipment page mode')
        name, item = self.read_item(image, (278, 278, 645, 316))
        if item is None:
            return self.wait_for_read('equipment name')
        if self.page:
            self.page.pop('read_wait', None)
        identity = (item['id'], shop)
        if self.page is None or self.page['identity'] != identity:
            self.page = {'identity': identity, 'rows': self.recipients(item, image),
                         'index': 0, 'tries': 0, 'phase': 'select'}
            logger.info('Equipment %s, slot=%s, unique=%s, candidates=%s'
                        % (item['name'], item['slot'], item['unique'], self.page['rows']))
        state = self.page
        if state['phase'] == 'submitted':
            if state['wait'].reached():
                self.fail('Equipment page did not close after submission, stop for review')
            return True
        press.reset()
        if shop and item['id'] not in self.rules:
            self.no_recipient(shop)
            return True
        if state['index'] >= len(state['rows']):
            self.no_recipient(shop)
            return True
        row = state['rows'][state['index']]
        if state['phase'] == 'confirm':
            if self.selected_row(image) == row:
                point = task.rogue_confirm_point((630, 630, 1275, 705), size=((200, 380), (35, 80)))
                if point:
                    logger.info('Equip %s to row %s%s' % (item['name'], row + 1, ' (purchase)' if shop else ''))
                    task.tap_point(*point, name='ROGUE_EQUIP_BUY' if shop else 'ROGUE_EQUIP_OK')
                    state['phase'] = 'submitted'
                    state['wait'] = Timer(6, count=1).start()
                    return True
                # 游戏按钮同时校验唯一跨部位冲突、购买余额等限制；灰色时绝不提交。
                state['index'] += 1
                state['tries'] = 0
                state['phase'] = 'select'
                return True
            if state['tries'] >= 3:
                state['index'] += 1
                state['tries'] = 0
                state['phase'] = 'select'
                return True
        state['tries'] += 1
        state['phase'] = 'confirm'
        task.tap_point(SLOT_X[item['slot']], ROW_Y[row], name='ROGUE_EQUIP_SLOT')
        return True

    def shop_equipment_slots(self):
        if self.shop_templates is None:
            bank = cv2.imread(ROGUE_SHOP_EQUIPMENT_TYPES.file, cv2.IMREAD_GRAYSCALE)
            if bank is None:
                self.fail('Shop equipment type template is missing')
            self.shop_templates = [bank[y1:y2, x1:x2] for x1, y1, x2, y2 in SHOP_EQUIPMENT_ICONS]
        grey = cv2.cvtColor(self.task.device.image, cv2.COLOR_RGB2GRAY)
        slots = []
        for col in range(5):
            patch = grey[495:575, 110 + col * 250:171 + col * 250]
            if any(cv2.matchTemplate(patch, icon, cv2.TM_CCOEFF_NORMED).max() >= .90
                   for icon in self.shop_templates):
                slots.append(col)
        return slots

    def shop_free_refresh_count(self):
        text = SHOP_FREE_REFRESH_COUNT.ocr(self.task.device.image)
        if re.fullmatch(r'\d{1,2}', text):
            return int(text)
        return None

    def handle_shop(self, press):
        if not self.rules:
            return False
        context = (self.task.core_started, self.task.route_step)
        if self.shop_context != context:
            self.shop_context = context
            self.shop_seen.clear()
            self.shop_refresh = None
            self.shop_refresh_confirmed = False
        if self.shop_refresh is not None:
            before, wait = self.shop_refresh
            label = self.reader.read_name(self.task.device.image, (175, 650, 250, 695), scale=1.5)
            count = None
            if label in ('免費', '免费'):
                count = self.shop_free_refresh_count()
            elif self.task.appear(ROGUE_SHOP_REFRESH_PAID, offset=(8, 5), similarity=.90):
                count = 0
            if count is not None and count < before:
                logger.info('Free shop refresh confirmed: %s -> %s' % (before, count))
                self.shop_refresh = None
                self.shop_refresh_confirmed = False
                self.shop_seen.clear()
            elif wait.reached():
                self.fail('Shop free refresh result was not confirmed, stop for review')
            else:
                return True
        for col in self.shop_equipment_slots():
            if col in self.shop_seen:
                continue
            if press.reached():
                press.reset()
                self.shop_seen.add(col)
                self.shop_opening = Timer(6, count=1).start()
                # 货架名称小且可能换行；免费打开详情认全名，只有命中指定规则才购买。
                self.task.tap_point(140 + col * 250, 390, name='ROGUE_SHOP_EQUIPMENT')
            return True
        if not press.reached():
            return True
        free = self.reader.read_name(self.task.device.image, (175, 650, 250, 695), scale=1.5)
        if free not in ('免費', '免费'):
            return False
        free_remaining = self.shop_free_refresh_count()
        if free_remaining is None:
            self.fail('Shop remaining free refreshes were not recognized, stop for review')
        if free_remaining == 0:
            return False
        press.reset()
        self.shop_refresh = (free_remaining, Timer(6, count=1).start())
        self.shop_refresh_confirmed = False
        logger.info('Use free shop refresh (%s free remaining)' % free_remaining)
        self.task.tap_point(100, 672, name='ROGUE_SHOP_REFRESH_FREE')
        return True
