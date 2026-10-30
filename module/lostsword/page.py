from module.base.button import Button
from module.lostsword.assets import (AFFECTION_BTN_DONE,
                                     AFFECTION_BTN_TALK,
                                     AFFECTION_TAP,
                                     ARENA_BTN_CHALLENGE_1,
                                     ARENA_BTN_CHALLENGE_2,
                                     ARENA_BTN_CHALLENGE_3,
                                     ARENA_BTN_CLOSE,
                                     ARENA_BTN_SEASON,
                                     ARENA_BTN_TEAM,
                                     ARENA_CARD,
                                     ARENA_SEASON_FOOTER,
                                     ARENA_TITLE,
                                     BOSS_BTN_CLOSE,
                                     BOSS_BTN_TEAM,
                                     BOSS_CARD,
                                     BOSS_DIALOG_CLOSE,
                                     BOSS_DIALOG_TITLE,
                                     BOSS_TICKET_CLOSE,
                                     BOSS_TICKET_TITLE,
                                     BATTLE_TITLE,
                                     CHAR_BTN,
                                     CHAR_BTN_AFFECTION,
                                     CHAR_TITLE,
                                     DUNGEON_CARD,
                                     DUNGEON_DIALOG_CLOSE,
                                     COPY_BTN_SELECT,
                                     COPY_BTN_SWEEP,
                                     DUNGEON_DIALOG_TITLE,
                                     DUNGEON_TITLE,
                                     EVENT_BTN_SELECT,
                                     EVENT_BTN_START,
                                     EVENT_TAB,
                                     EVENT_TAB_SELECTED,
                                     GUILD_BTN_CLOSE,
                                     GUILD_BTN_DONATE,
                                     GUILD_BTN_INVEST_GOLD,
                                     GUILD_BTN_INVEST_TOKEN,
                                     GUILD_BTN_SIGN,
                                     GUILD_DONATE_CLOSE,
                                     GUILD_TITLE,
                                     MAIL_BTN_CLOSE,
                                     MAIL_TITLE,
                                     STAR_CARD,
                                     STAR_TITLE,
                                     SUMMON_CLOSE,
                                     SUMMON_CONFIRM,
                                     SUMMON_TITLE,
                                     SUMMON_VIEW_ALL,
                                     MAIN_BTN_BATTLE,
                                     MAIN_BTN_MENU,
                                     MAIN_BTN_SHOP,
                                     MAIN_BTN_SUMMON,
                                     MAIN_BTN_TREASURE,
                                     MENU_BTN_CLOSE,
                                     MENU_BTN_GUILD,
                                     MENU_BTN_MAIL,
                                     MAZE_BTN_AUTO,
                                     MAZE_DONE,
                                     MENU_BTN_TASK,
                                     PASS_BTN,
                                     PASS_TITLE,
                                     ROUND_BTN,
                                     ROUND_BTN_UPGRADE,
                                     SHOP_BTN_CLOSE,
                                     SHOP_DIALOG_CLOSE,
                                     SHOP_DIALOG_TITLE,
                                     SHOP_TITLE,
                                     TASK_BTN_CLAIM_ALL,
                                     TASK_BTN_CLOSE,
                                     TREASURE_BTN_CLOSE,
                                     TREASURE_BTN_QUICK,
                                     TREASURE_QUICK_CLOSE,
                                     TREASURE_QUICK_TITLE,
                                     TREASURE_TITLE)
from module.ui.page import Page

"""
Pages of Lost Sword (失落之剑).

Every panel of this game is a modal that dims the lobby without hiding it: the
bottom bar labels still match behind it (similarity 1.00), so the lobby cannot
be identified by them. `MAIN_BTN_BATTLE` is the battle icon of that bar, which
every panel *does* cover (similarity 0.22~0.27), so the lobby is only matched
when no overlay is open.

Pages are declared from the most specific to the least: `ui_get_current_page()`
returns the first page whose check point matches, and a panel stays drawn behind
the dialog that opens on top of it.
"""

# The quick-explore dialog. It covers the treasure panel title, so the two never
# match at the same time.
page_treasure_quick = Page(TREASURE_QUICK_TITLE)
# The "是否进行扫荡?" dialog of the boss raid. The dialog does not cover the
# boss page behind it (its "队伍编排" button stays matched), so this has to come
# before that page. It is a page of its own because a dialog left open swallows
# every later click: routing through it lets `ui_ensure(page_boss)` close a stray
# one instead of clicking into a modal.
page_boss_dialog = Page(BOSS_DIALOG_TITLE)
# The 「一键扫荡」 dialog, the paid sweep: it opens when 「扫荡」 is pressed with no
# free try left, and it spends a Boss Raid Ticket if its own 「扫荡」 button is
# pressed. The task never wants it (one tap too far and the user's tickets are
# gone), but it has to be a page of the graph all the same, so that a run that
# stumbles into it closes it instead of leaving a modal on screen.
page_boss_ticket = Page(BOSS_TICKET_TITLE)
# The mailbox. Identified by its own title: the panel is full screen, so nothing
# of the lobby is left to recognise, and the "一键领取" button looks the same
# whether there is mail to claim or not.
page_mail = Page(MAIL_TITLE)
# The treasure panel, identified by its own title rather than by the bottom bar
# entry: the entry is still on screen behind the panel.
page_treasure = Page(TREASURE_TITLE)
# The task panel. Its "全部领取" button is unique to the panel and stays on
# screen whether or not there is something to claim, which is what a check point
# needs; whether the button is enabled is read separately as a colour.
page_task = Page(TASK_BTN_CLAIM_ALL)
# The "购买商品" dialog of the shop. It does not hide the shop title behind it
# (the shop stays matched as well), so it has to come before the shop page, and
# it is a page of its own because a dialog left open would swallow every later
# click: routing through it lets `ui_ensure(page_shop)` close a stray one.
page_shop_dialog = Page(SHOP_DIALOG_TITLE)
# The shop. Its title is the only text that is always drawn: the top tab bar and
# the left column both change with what is selected.
page_shop = Page(SHOP_TITLE)
# The boss raid detail page (领主突袭). Its "队伍编排" button is drawn in every
# state of the page: the sweep counter changes, the "最高分数" row only appears
# after today's battle, but that button stays. Measured 1.00 here, 0.21 on the
# battle tab and 0.19 on the victory page.
page_boss = Page(BOSS_BTN_TEAM)
# The event tab of the battle page. The 「战斗」 heading of `page_battle` stays on
# screen here, so this page has to be declared before it.
page_event = Page(EVENT_TAB_SELECTED)
# A stage page of an event. Its 「选择」 button sits in the bottom right corner
# and the card list behind it does not have one.
page_event_stage = Page(EVENT_BTN_SELECT)
# The sortie page of an event stage, the one 「选择」 opens. Same layout as the
# boss raid sortie page but a different bottom button: 「出发」.
page_event_start = Page(EVENT_BTN_START)
# The battle tab (战斗), the page with the 普通 / 副本 / 挑战 / 公会 / 活动 cards.
# Its own heading is the check point, not a card: the game remembers the tab it
# was left on (measured: back from the arena on 「活动」), and the cards only
# exist under 「普通」.
page_battle = Page(BATTLE_TITLE)
# A stage page under the 副本 tab. Its 「选择」 button is on every one of them
# (the sweepable stages add 「扫荡」 next to it, the limited ones only have 选择),
# while the card list behind it does not have it at all.
page_copy_stage = Page([COPY_BTN_SELECT, COPY_BTN_SWEEP])
# 星辰轮回, opened from the last card of the battle page. Full screen with the
# three adventure areas on the left and the score table on the right.
page_star = Page(STAR_TITLE)
# The squad dungeon detail page (小队副本). Built like the boss raid page - same
# 「队伍编排」 button, same left column - so it is matched by its boss name instead,
# and it has to come before `page_boss` because that page's check point matches
# here as well.
page_dungeon = Page(DUNGEON_TITLE)
# Its "是否前往小队副本房间?" confirm dialog covers the middle only, so the page
# below keeps matching and the dialog has to be a page of its own, declared first.
page_dungeon_dialog = Page(DUNGEON_DIALOG_TITLE)
# The arena list (竞技场). The 「对战对手」 heading is drawn whatever the three
# cards hold, while the side panel carries numbers that change every battle.
page_arena = Page(ARENA_TITLE)
# The versus page of one arena battle. Its 「编排进攻队伍」 button is the only
# thing that stays: the cards and the opponent change with the list.
page_arena_preview = Page(ARENA_BTN_TEAM)
# The season mission panel of the arena. Identified by its footnote rather than
# by the 「全部领取」 button: that button and the one of the task panel match each
# other's screenshots (same label, 170 pixels apart), so either of them used as a
# check point made the two pages claim each other. The footnote exists only here.
page_arena_season = Page(ARENA_SEASON_FOOTER)
# The 公会捐献 dialog. Its check point is the X in its own corner, because the
# dialog leaves the guild title behind it completely untouched - `GUILD_TITLE`
# still matches 1.00 through the dim layer - so nothing of the page below can
# tell the two apart. Being a page of its own also means a dialog left open by
# a dead run is closed by `ui_goto(page_guild)` instead of swallowing clicks.
page_guild_donate = Page(GUILD_DONATE_CLOSE)
# The guild, opened from the menu grid. Its title is the check point: the tab
# row highlights whatever is selected, and the two bottom buttons and both
# investment rows carry badges that come and go.
page_guild = Page(GUILD_TITLE)
# The menu. Identified by the "任务" text of its icon grid: the icon itself
# carries a red dot that disappears once the tasks are claimed, which drops the
# match from 1.00 to 0.74, so only the text is used.
page_menu = Page(MENU_BTN_TASK)
# The battle pass panel, opened from the lobby's left column. Full screen; the
# season it shows is picked by the game, not by the graph.
page_pass = Page(PASS_TITLE)
# The 「返回」 button of the defeat page. The page has no page of its own - it is
# handled as an overlay, see `ui_additional()`.
MAIN_DEFEAT_BACK = Button(area=(896, 628, 1014, 668), color=(0, 0, 0),  # alas-lint: allow - a click point alias used by the page graph
                          button=(896, 628, 1014, 668), name='MAIN_DEFEAT_BACK')

# The character grid, opened from the bottom bar. Its 「角色」 heading is the
# check point; a detail page shows the character name there instead (0.79).
page_character = Page(CHAR_TITLE)
# One character's detail page. The affection entry at the bottom left is an icon
# whose label changes with the character (羁绊延续 / 心生好感 / ...), so the icon
# is what is matched.
page_character_detail = Page(CHAR_BTN_AFFECTION)
# The affection panel of that character. Both talk buttons match here - the one
# with tries left and the finished one - because whatever is under it is the
# panel either way.
page_affection = Page([AFFECTION_BTN_TALK, AFFECTION_BTN_DONE])
# A running conversation: the continue arrow at the bottom right.
page_talk = Page(AFFECTION_TAP)
# The maze map, opened from the last card of the battle page. Its 「自动进行」
# button is drawn whether or not a run is left today (the panel it raises tells).
page_maze = Page([MAZE_BTN_AUTO, MAZE_DONE])
# The round table panel, opened from the menu grid. Its 「升级」 button is drawn
# whether or not the resources are enough (the colour tells, read separately),
# and it covers the menu behind it.
page_round = Page(ROUND_BTN_UPGRADE)
# The summon page, and both of its free pools. They share one page: the banner
# list and the 「召唤」 heading stay on screen while the panel on their right is
# swapped for 领取角色 / 领取宠物, so the heading (checked 1.00 on the page, 0.99
# on a pool, 0.52 on the lobby) covers all three.
page_summon = Page(SUMMON_TITLE)
# The two steps after a draw. Both are a single card over a dimmed panel with one
# button at the bottom, and that button is the only thing that differs: 查看全部
# then 确认. Each button as a check point scores 1.00 on its own step and 0.68 on
# the other, which is what tells them apart.
page_summon_result = Page(SUMMON_VIEW_ALL)
page_summon_confirm = Page(SUMMON_CONFIRM)
# The lobby. The battle icon is opaque art and gets covered by every modal.
page_main = Page(MAIN_BTN_BATTLE)

page_main.link(button=MAIN_BTN_TREASURE, destination=page_treasure)
page_main.link(button=MAIN_BTN_MENU, destination=page_menu)
page_main.link(button=MAIN_BTN_BATTLE, destination=page_battle)
page_main.link(button=PASS_BTN, destination=page_pass)
page_main.link(button=CHAR_BTN, destination=page_character)
page_main.link(button=MAIN_BTN_SUMMON, destination=page_summon)
page_summon.link(button=SUMMON_CLOSE, destination=page_main)
# 查看全部 opens the list of what was drawn, 确认 closes it and lands back on the
# pool. They are two states of one screen rather than two pages of a graph, so
# both links lead to the pool: walking home from either one presses its own
# button once and re-reads the screen, which is the only exit the game offers.
page_summon_result.link(button=SUMMON_VIEW_ALL, destination=page_summon)
page_summon_confirm.link(button=SUMMON_CONFIRM, destination=page_summon)
page_character.link(button=ARENA_BTN_CLOSE, destination=page_main)
page_character_detail.link(button=ARENA_BTN_CLOSE, destination=page_character)
page_affection.link(button=ARENA_BTN_CLOSE, destination=page_character_detail)
page_pass.link(button=ARENA_BTN_CLOSE, destination=page_main)
# The 领主突袭 card opens the detail page. It is also this page's check point,
# which is fine: it is the only card the tasks below ever click.
page_battle.link(button=EVENT_TAB, destination=page_event)
page_event.link(button=ARENA_BTN_CLOSE, destination=page_battle)
# The stage page and the sortie page are two levels of the same event: the X of
# the stage page goes up to the sortie page (measured), and the X of the sortie
# page leaves the event.
page_event_stage.link(button=ARENA_BTN_CLOSE, destination=page_event_start)
page_event_start.link(button=ARENA_BTN_CLOSE, destination=page_event)
page_battle.link(button=BOSS_CARD, destination=page_boss)
page_battle.link(button=DUNGEON_CARD, destination=page_dungeon)
page_battle.link(button=STAR_CARD, destination=page_star)
page_star.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_copy_stage.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_dungeon.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_dungeon_dialog.link(button=DUNGEON_DIALOG_CLOSE, destination=page_dungeon)
page_battle.link(button=ARENA_CARD, destination=page_arena)
page_maze.link(button=ARENA_BTN_CLOSE, destination=page_battle)
# All three cards lead to the same versus page: which one is fought is decided
# by the task, not by the page graph.
page_arena.link(button=ARENA_BTN_CHALLENGE_1, destination=page_arena_preview)
page_arena.link(button=ARENA_BTN_CHALLENGE_2, destination=page_arena_preview)
page_arena.link(button=ARENA_BTN_CHALLENGE_3, destination=page_arena_preview)
page_arena.link(button=ARENA_BTN_CLOSE, destination=page_battle)
page_arena.link(button=ARENA_BTN_SEASON, destination=page_arena_season)
page_arena_preview.link(button=ARENA_BTN_CLOSE, destination=page_arena)
page_arena_season.link(button=ARENA_BTN_CLOSE, destination=page_arena)
# The round X in the top right corner closes one layer: the boss page goes back
# to the battle tab, the battle tab back to the lobby. Same asset, same spot.
page_battle.link(button=BOSS_BTN_CLOSE, destination=page_main)
page_boss.link(button=BOSS_BTN_CLOSE, destination=page_battle)
page_boss_dialog.link(button=BOSS_DIALOG_CLOSE, destination=page_boss)
page_boss_ticket.link(button=BOSS_TICKET_CLOSE, destination=page_boss)
page_menu.link(button=MENU_BTN_MAIL, destination=page_mail)
page_menu.link(button=MENU_BTN_TASK, destination=page_task)
page_menu.link(button=MENU_BTN_GUILD, destination=page_guild)
page_menu.link(button=MAIN_BTN_SHOP, destination=page_shop)
page_menu.link(button=MENU_BTN_CLOSE, destination=page_main)
page_menu.link(button=ROUND_BTN, destination=page_round)
page_round.link(button=ARENA_BTN_CLOSE, destination=page_menu)
# The 捐献 button of the guild raises the 公会捐献 dialog on top of the page, and
# the dialog's own X closes it back onto the page. The guild's X in the top
# right corner is the same round key as the menu's, but drawn at a different
# size over a different background: the menu asset scores 0.69 there, so this
# corner has an asset of its own.
page_guild.link(button=GUILD_BTN_DONATE, destination=page_guild_donate)
page_guild_donate.link(button=GUILD_DONATE_CLOSE, destination=page_guild)
page_guild.link(button=GUILD_BTN_CLOSE, destination=page_menu)
# The mailbox X is its own round button, not the plain X of the menu and task
# panels, so it needs its own asset.
page_mail.link(button=MAIL_BTN_CLOSE, destination=page_main)
# Closing the task panel closes the menu behind it as well: one click lands on
# the lobby directly (verified, 3.7 difference against a clean lobby frame).
page_task.link(button=TASK_BTN_CLOSE, destination=page_main)
# The shop X is the round button in its own corner, 15 pixels left of the menu X.
page_shop.link(button=SHOP_BTN_CLOSE, destination=page_main)
page_shop_dialog.link(button=SHOP_DIALOG_CLOSE, destination=page_shop)
page_treasure.link(button=TREASURE_BTN_CLOSE, destination=page_main)
page_treasure.link(button=TREASURE_BTN_QUICK, destination=page_treasure_quick)
page_treasure_quick.link(button=TREASURE_QUICK_CLOSE, destination=page_treasure)

# The reward popup is a full screen "tap to continue": no close button, no other
# way out than tapping it. Its middle is a golden band that holds the item icons;
# tapping an icon opens the item detail page instead, which nothing handles. The
# band covers y 231~581 and x 166~1114, so the tap below lands on a blank part of
# the panel. One tap is consumed by the popup and by the panel underneath, so the
# caller must re-enter the panel instead of assuming it is still open.
REWARD_POPUP_CLOSE = Button(area=(975, 615, 1025, 655), color=(0, 0, 0),  # alas-lint: allow - a click point alias used by the page graph
                            button=(975, 615, 1025, 655), name='REWARD_POPUP_CLOSE')

# The tab row of the battle page. The selected tab is drawn on a cream pill
# (mean 193~208), an idle one on the dark panel (mean 60~71).
BATTLE_TAB_NORMAL = Button(area=(130, 71, 272, 107), color=(0, 0, 0),  # alas-lint: allow - a click point alias used by the page graph
                           button=(130, 71, 272, 107), name='BATTLE_TAB_NORMAL')
BATTLE_TAB_SELECTED_MEAN = 130

# The boss raid puts its 「扫荡」 button under the spot above, so dismissing the
# reward popup there also starts another sweep. This point is the blank band at
# the top of the boss page (above the enemy panel) and under the popup it is
# black background, so one tap both closes the popup and hits nothing else. It is
# also where the victory page is tapped through.
BOSS_RESULT_TAP = Button(area=(600, 70, 680, 110), color=(0, 0, 0),  # alas-lint: allow - a click point alias used by the page graph
                         button=(600, 70, 680, 110), name='BOSS_RESULT_TAP')

