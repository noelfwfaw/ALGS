"""Pages of Hazeworld (苍雾世界).

Every page is identified by a unique button, and `link()` records "click this
-> go there"; `UI.ui_goto()` then finds the shortest path from wherever the
game currently is. Two rules decide the check buttons:

- A check button has to survive the game's own decorations - the side icons of
  the lobby are drawn on an animated scene and the mail icon grows a badge, so
  the lobby is matched on the opaque 作战 button.
- Pages are checked in declaration order, so the more specific one has to come
  first: the battle page and its resource tab share a title, and the expedition
  panel sits on top of the room page.
"""

from module.hazeworld.assets import (BACK_ARROW, BATTLE_CORE_ENTRY,
                                     BATTLE_TAB_RESOURCE, BATTLE_TITLE,
                                     CORE_BTN_HOME, CORE_BTN_SWEEP,
                                     EX_TITLE_LABEL, FRIEND_TAB_LIST,
                                     MAIL_BTN_CLAIM_ALL, MAIN_BTN_BATTLE,
                                     MAIN_BTN_EXERCISE, MAIN_ICON_FRIEND,
                                     MAIN_ICON_MAIL, MAIN_ICON_PASS,
                                     MAIN_ICON_ROOM, MAIN_ICON_TASK,
                                     PASS_BTN_RESOURCE, PROFILE_MEMBER,
                                     ROOM_BTN_COLLECT_ALL,
                                     ROOM_BTN_EXPEDITION,
                                     ROOM_EXP_PANEL_LABEL, SUPPORT_CARD,
                                     SUPPORT_ENTRY, SUPPORT_TITLE,
                                     TASK_POINT_LABEL)
from module.ui.page import Page

"""
Pages of Hazeworld (苍雾世界).

The page graph is built the same way the framework expects: every page is
identified by a unique button, and `link()` records "click this -> go there".
`UI.ui_goto()` then finds the shortest path from wherever the game currently is.
"""

# The lobby is identified by two check points, because both of the obvious ones
# fail now and then: the side icons are drawn on the scene, which is animated,
# and their crop carries a piece of it, while the mail icon gets a badge when
# there is an unread letter. The "作战" button is opaque and always there.
page_main = Page([MAIN_BTN_BATTLE, MAIN_ICON_MAIL])
# The tab bar changes with the selected tab, the "积分点数" label does not.
page_task = Page(TASK_POINT_LABEL)
page_pass = Page(PASS_BTN_RESOURCE)
page_friend = Page(FRIEND_TAB_LIST)
page_mail = Page(MAIL_BTN_CLAIM_ALL)
# The expedition panel is a modal, but it behaves like a page: its label stays
# visible in every state, including under the result popup that covers the
# panel title. It is declared before the room page because the two share the
# screen: the room keeps its title and its bottom bar above and below the
# panel, so a room check point outside of the covered middle would match while
# the panel is open and `ui_ensure(page_room)` would report "already there"
# with the panel still covering the room.
page_expedition = Page(ROOM_EXP_PANEL_LABEL)
# The command room has no bottom tab bar, only the page title. The check point
# is the "collect all" button rather than the title, because the title stays
# readable above the expedition panel: it is the one element of the room the
# panel covers, and it is permanent (it stays drawn and keeps its colour after
# everything has been collected).
page_room = Page(ROOM_BTN_COLLECT_ALL)
# The exercise hall is a full page with its own title. The rank change popup
# covers most of it, but the title stays readable, so this page is matched
# while that popup is open too and has to be checked after it.
page_exercise = Page(EX_TITLE_LABEL)
# The player profile opened by tapping the name plate on page_main.
page_profile = Page(PROFILE_MEMBER)
# The support character panel of the profile, opened by tapping a character
# card. It covers the profile, so the profile check button is not visible here.
page_support = Page(SUPPORT_TITLE)
# The battle dungeon page. Its title is shared by every tab, so this page is
# only matched while the resource tab is closed. Pages are checked in
# declaration order, so page_battle_resource must come first: with that tab
# open both check buttons match and the more specific one has to win.
page_battle_resource = Page(BATTLE_CORE_ENTRY)
page_battle = Page(BATTLE_TITLE)
# The core material stage page of a single core type. The page title changes
# with the selected type, so the sweep button is the check button instead.
page_core = Page(CORE_BTN_SWEEP)

page_main.link(button=MAIN_ICON_TASK, destination=page_task)
page_main.link(button=MAIN_ICON_PASS, destination=page_pass)
page_main.link(button=MAIN_ICON_FRIEND, destination=page_friend)
page_main.link(button=MAIN_ICON_MAIL, destination=page_mail)
page_main.link(button=MAIN_ICON_ROOM, destination=page_room)
page_main.link(button=MAIN_BTN_EXERCISE, destination=page_exercise)
page_main.link(button=SUPPORT_ENTRY, destination=page_profile)
page_main.link(button=MAIN_BTN_BATTLE, destination=page_battle)
page_room.link(button=ROOM_BTN_EXPEDITION, destination=page_expedition)
page_profile.link(button=SUPPORT_CARD, destination=page_support)
page_battle.link(button=BATTLE_TAB_RESOURCE, destination=page_battle_resource)
page_battle_resource.link(button=BATTLE_CORE_ENTRY, destination=page_core)
# The house icon on the core pages jumps straight to the home page, while the
# back arrow only climbs one level. Going home in one hop keeps the walk short,
# and a short walk is what keeps the page graph stable: every extra hop is a
# chance to fire the next tap on a screen that is still fading.
page_core.link(button=CORE_BTN_HOME, destination=page_main)

for _page in [page_task, page_pass, page_friend, page_mail, page_room,
              page_exercise, page_profile, page_battle, page_battle_resource]:
    _page.link(button=BACK_ARROW, destination=page_main)
page_expedition.link(button=BACK_ARROW, destination=page_room)
page_support.link(button=BACK_ARROW, destination=page_profile)
page_core.link(button=BACK_ARROW, destination=page_battle_resource)
