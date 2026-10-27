"""Expedition tables of the command room.

Pure data: the config value of a team maps to the bar of that expedition in the
left column, and its duration maps to the button that picks it. Kept in one place
because both the panel code and the task flow read them.
"""

from module.hazeworld.assets import (EXP_HOURS_4, EXP_HOURS_8, EXP_HOURS_12,
                                    EXP_TASK_1, EXP_TASK_2, EXP_TASK_3,
                                    EXP_TASK_4, EXP_TASK_5)

# Config value of HazeworldRoom_TeamNTask -> the bar of that expedition in the
# left column. Keep in sync with the option list in argument.yaml.
EXPEDITION_TASKS = {
    'Training': EXP_TASK_1,
    'Defense': EXP_TASK_2,
    'Attack': EXP_TASK_3,
    'Firepower': EXP_TASK_4,
    'Support': EXP_TASK_5,
}

EXPEDITION_HOURS = {
    4: EXP_HOURS_4,
    8: EXP_HOURS_8,
    12: EXP_HOURS_12,
}

# No expedition lasts longer than the longest duration on offer, so a countdown
# beyond that is a misread rather than a team that is out for a year.
EXPEDITION_MAX = max(EXPEDITION_HOURS)
