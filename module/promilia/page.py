"""Promilia page declarations."""

from module.promilia.assets import (ACTIVITY_CLOSE, ACTIVITY_DAILY_ACTIVE,
                                    ACTIVITY_ENTRY, ACTIVITY_WEEKLY_ACTIVE,
                                    MAIN_ICONS)
from module.ui.page import Page


# The rabbit HUD icon stays fixed while the world background changes.
MAIN_HUD_ICON = MAIN_ICONS.crop((160, 5, 200, 55), name='MAIN_HUD_ICON')


page_main = Page([MAIN_HUD_ICON])
page_activity = Page([ACTIVITY_DAILY_ACTIVE, ACTIVITY_WEEKLY_ACTIVE])
page_main.link(button=ACTIVITY_ENTRY, destination=page_activity)
page_activity.link(button=ACTIVITY_CLOSE, destination=page_main)
