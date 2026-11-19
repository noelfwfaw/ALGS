# -*- coding: utf-8 -*-
"""离线回归：`rogue_route.best_path` 必须返回**到达最末有效层**的完整路径。

不连设备、不读截图，只用内存里的 RouteNode 手工搭连通图。

覆盖的回归点：
* 前缀陷阱：首层休息 85 分 → 精英 → 精英 累计只有 9 分，而事件线 50 分；
  旧实现按"所有层取最高累计分"会返回休息那段前缀（其实 85 分前缀仍高于 50，
  所以只要允许前缀参与比较就会选错），必须返回完整的事件线。
* 完整优先：前缀分数比任何完整路径都高时，仍然只返回完整路径。
* 连通性、分数、平局与"走不到底返回空"的既有规则不变。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from module.chaoszero import rogue_route as route  # noqa: E402


def build(layers):
    """按层搭节点：(x, y, kind) 的三层列表 → 已填 tier/row 的节点。"""
    nodes = []
    for tier, column in enumerate(layers):
        for row, (x, y, kind) in enumerate(column):
            node = route.RouteNode(x, y, kind)
            node.tier = tier
            node.row = row
            nodes.append(node)
    return nodes


STRESS_STATE = {'stress': 35, 'avoid_elite': True}


def two_three_tier_lines():
    """压力 35、避开精英的两条 3 层路线。

    第一条：休息→精英→精英，走到底 9 分（85 / -38 / -38）。
    第二条：事件→战斗→航点，走到底 50 分（25 / 15 / 10）。
    休息那条前缀就是 85 分，是"按最高累计分取前缀"最容易踩的坑。
    """
    nodes = build([
        [(100, 100, route.KIND_REST), (100, 300, route.KIND_EVENT)],
        [(300, 100, route.KIND_ELITE), (300, 300, route.KIND_BATTLE)],
        [(500, 100, route.KIND_ELITE), (500, 300, route.KIND_BEACON)],
    ])
    edges = [(0, 2), (2, 4), (1, 3), (3, 5)]
    return nodes, edges


class TestBestPathReachesLastTier(unittest.TestCase):
    def test_two_three_tier_lines_returns_complete_second_line(self):
        nodes, edges = two_three_tier_lines()
        path = route.best_path(nodes, route.ROUTE_BALANCE, STRESS_STATE, edges)
        self.assertEqual([node.kind for node in path],
                         [route.KIND_EVENT, route.KIND_BATTLE, route.KIND_BEACON])
        self.assertEqual([node.tier for node in path], [0, 1, 2])

    def test_branch_and_junk_state_does_not_rescue_elite_line(self):
        nodes, edges = two_three_tier_lines()
        state = {'stress': 35, 'avoid_elite': True, 'junk': True, 'need_spark': True}
        path = route.best_path(nodes, route.ROUTE_BATTLE, state, edges)
        self.assertEqual(len(path), 3)
        self.assertEqual(path[-1].tier, 2)
        self.assertNotEqual(path[-1].kind, route.KIND_ELITE)

    def test_prefix_never_chosen_even_when_it_scores_higher(self):
        # 首层休息 85 分，唯一出口是精英；完整路线只有战斗线 30/30/30 = 90，
        # 这里把完整路线压到 3 层各 10 分（航点线）低于前缀 85，验证仍然走完整线。
        nodes = build([
            [(100, 100, route.KIND_REST), (100, 300, route.KIND_BEACON)],
            [(300, 100, route.KIND_ELITE), (300, 300, route.KIND_BEACON)],
            [(500, 300, route.KIND_BEACON)],
        ])
        edges = [(0, 2), (1, 3), (3, 4)]  # 休息 → 精英 之后断链
        path = route.best_path(nodes, route.ROUTE_BALANCE, STRESS_STATE, edges)
        self.assertEqual([node.kind for node in path],
                         [route.KIND_BEACON, route.KIND_BEACON, route.KIND_BEACON])

    def test_fallback_link_tiers_also_requires_last_tier(self):
        # 不传 edges：退回 link_tiers 的高度差近似，同样只收完整路径。
        nodes, _ = two_three_tier_lines()
        path = route.best_path(nodes, route.ROUTE_BALANCE, STRESS_STATE)
        self.assertEqual([node.tier for node in path], [0, 1, 2])

    def test_no_complete_route_returns_empty(self):
        nodes = build([
            [(100, 100, route.KIND_REST)],
            [(300, 100, route.KIND_EVENT)],
            [(500, 500, route.KIND_EVENT)],  # 第 3 层和上排高度差超出行距，连线不通
        ])
        edges = [(0, 1)]
        self.assertEqual(route.best_path(nodes, route.ROUTE_BALANCE, STRESS_STATE, edges), [])
        self.assertEqual(route.best_path([], route.ROUTE_BALANCE, STRESS_STATE, []), [])

    def test_tie_on_complete_routes_keeps_deterministic_choice(self):
        nodes = build([
            [(100, 100, route.KIND_BATTLE), (100, 300, route.KIND_BATTLE)],
            [(300, 100, route.KIND_BATTLE), (300, 300, route.KIND_BATTLE)],
            [(500, 100, route.KIND_BATTLE), (500, 300, route.KIND_BATTLE)],
        ])
        edges = [(0, 2), (2, 4), (1, 3), (3, 5)]
        first = route.best_path(nodes, route.ROUTE_BALANCE, {}, edges)
        second = route.best_path(nodes, route.ROUTE_BALANCE, {}, edges)
        self.assertEqual([node.x for node in first], [node.x for node in second])
        self.assertEqual(len(first), 3)

    def test_plan_covers_every_tier_kind(self):
        nodes, edges = two_three_tier_lines()
        plan = route.plan(nodes, route.ROUTE_BALANCE, STRESS_STATE, edges)
        self.assertEqual([entry[0]['kind'] for entry in plan],
                         [route.KIND_EVENT, route.KIND_BATTLE, route.KIND_BEACON])


if __name__ == '__main__':
    unittest.main()
