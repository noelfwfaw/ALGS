import argparse
import json
import queue
import threading
import time
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional

# Import fake module before import pywebio to avoid importing unnecessary module PIL
from module.webui.fake_pil_module import import_fake_pil_module

import_fake_pil_module()

from pywebio import config as webconfig
from pywebio.input import file_upload, input, input_group, select
from pywebio.output import (
    Output,
    clear,
    close_popup,
    popup,
    put_button,
    put_buttons,
    put_collapse,
    put_column,
    put_error,
    put_html,
    put_link,
    put_loading,
    put_markdown,
    put_row,
    put_scope,
    put_table,
    put_text,
    put_warning,
    toast,
    use_scope,
)
from pywebio.pin import pin, pin_on_change
from pywebio.session import download, go_app, info, local, register_thread, run_js, set_env
from starlette.responses import FileResponse

import module.webui.lang as lang
from module.config.config import AlasConfig, Function
from module.config.deep import deep_get, deep_iter, deep_set
from module.config.env import IS_ON_PHONE_CLOUD
from module.config.server import VALID_SERVER, to_server
from module.config.utils import (
    alas_instance,
    alas_template,
    dict_to_kv,
    filepath_args,
    filepath_config,
    read_file,
)
from module.logger import logger
from module.ocr.rpc import start_ocr_server_process, stop_ocr_server_process
from module.submodule.submodule import load_config
from module.submodule.utils import get_available_func, get_config_mod
from module.webui.base import Frame
from module.webui.discord_presence import close_discord_rpc, init_discord_rpc
from module.webui.fastapi import asgi_app
from module.webui.lang import _t, t
from module.webui.patch import fix_py37_subprocess_communicate, patch_executor, patch_mimetype
from module.webui.pin import put_input, put_select
from module.webui.process_manager import ProcessManager
from module.webui.remote_access import RemoteAccess
from module.webui.setting import State
from module.webui.updater import updater
from module.webui.utils import (
    Icon,
    Switch,
    TaskHandler,
    add_css,
    filepath_css,
    get_alas_config_listen_path,
    get_localstorage,
    get_window_visibility_state,
    login,
    parse_pin_value,
    raise_exception,
    re_fullmatch,
    to_pin_value,
)
from module.chaoszero import rogue_events, rogue_spark_catalog as rogue_cards
from module.webui.widgets import (
    BinarySwitchButton,
    RichLog,
    T_Output_Kwargs,
    put_arg_select,
    put_icon_buttons,
    put_loading_text,
    put_none,
    put_output,
)

patch_executor()
patch_mimetype()
fix_py37_subprocess_communicate()
task_handler = TaskHandler()

ROGUE_SECTIONS = {
    "Route": (
        "RogueWorld",
        "RogueSeasonDifficulty",
        "RogueSeasonSavePt",
        "RogueDreamMode",
        "RogueDistortionAdapt",
        "RogueRoute",
        "RogueAvoidElite",
        "RogueHerald",
    ),
    "Build": (
        "RogueMember",
        "RogueSlot1Member",
        "RogueSlot2Member",
        "RogueSlot3Member",
        "RogueSparkFilter",
        "RogueGodSparkFilter",
        "RogueGodSparkFirst",
        "RogueSparkCheck",
        "RogueSparkCheckCard",
        "RogueRemoveMember",
        "RogueDelete",
        "RogueDeleteFilter",
        "RogueMeditate",
        "RogueCopyMember",
        "RogueCopyCard",
        "RogueSeasonMemoryCard",
        "RogueSeasonMemoryMember",
        "RogueSeasonMemoryFallbackMember",
        "RogueEquipFilter",
        "RoguePick",
    ),
    "Fate": ("RogueFateMainFilter", "RogueFateCoreFilter", "RogueFateCapture"),
    "Events": ("RogueEventPick", "RogueEventCapture"),
    "Settlement": ("RogueSaveKeep", "RogueRuns", "RogueLoop", "RogueStopBeacon", "RogueCure"),
}
ROGUE_SLOT_MEMBER_ARGS = ("RogueSlot1Member", "RogueSlot2Member", "RogueSlot3Member")
ROGUE_BUILD_PICKERS = {
    "RogueSparkFilter": "rogue_spark_picker",
    "RogueGodSparkFilter": "rogue_spark_picker",
    "RogueSparkCheckCard": "rogue_spark_check_picker",
    "RogueDeleteFilter": "rogue_remove_picker",
}
ROGUE_HIDDEN_BUILD_ARGS = (*ROGUE_BUILD_PICKERS, "RogueDelete")
ROGUE_PICKER_WATCH_ARGS = ROGUE_SLOT_MEMBER_ARGS + ("RogueRemoveMember",)
ROGUE_SPARK_WATCH_PATHS = {
    f"ChaoszeroRogue.ChaoszeroRogue.{arg}" for arg in ROGUE_PICKER_WATCH_ARGS
}
ROGUE_CIRCLED_INDEX = ("①", "②", "③", "④", "⑤", "⑥")
ROGUE_SPARK_CUSTOM_OPTION = "__custom__"
ROGUE_CARD_POSITIONS = {1: "Left", 2: "Middle", 3: "Right"}
ROGUE_PARTY_SLOTS = {1: "Slot1", 2: "Slot2", 3: "Slot3"}
ROGUE_POSITION_LABELS = {
    "RoguePick": ROGUE_CARD_POSITIONS,
    "RogueHerald": ROGUE_CARD_POSITIONS,
    "RogueMember": ROGUE_PARTY_SLOTS,
    "RogueRemoveMember": ROGUE_PARTY_SLOTS,
    "RogueCopyMember": {0: "FollowSparkMember", **ROGUE_PARTY_SLOTS},
    "RogueSeasonMemoryMember": ROGUE_PARTY_SLOTS,
    "RogueSeasonMemoryFallbackMember": ROGUE_PARTY_SLOTS,
    "RogueSaveKeep": {0: "DecomposeAll", **ROGUE_PARTY_SLOTS},
}
ROGUE_SELECTOR_ROUTE = "/rogue-events"
ROGUE_SELECTOR_DIR = Path(__file__).resolve().parents[2] / "dev_tools" / "rogue_events"


class AlasGUI(Frame):
    ALAS_MENU: Dict[str, Dict[str, List[str]]]
    ALAS_ARGS: Dict[str, Dict[str, Dict[str, Dict[str, str]]]]
    theme = "default"

    def initial(self) -> None:
        self.ALAS_MENU = read_file(filepath_args("menu", self.alas_mod))
        self.ALAS_ARGS = read_file(filepath_args("args", self.alas_mod))
        self._init_alas_config_watcher()

    def __init__(self) -> None:
        super().__init__()
        # modified keys, return values of pin_wait_change()
        self.modified_config_queue = queue.Queue()
        # alas config name
        self.alas_name = ""
        self.alas_mod = "alas"
        self.alas_config = AlasConfig("template")
        self.initial()
        # rendered state cache
        self.rendered_cache = []
        self.inst_cache = []
        self.load_home = False
        self.af_flag = False
        self._rogue_spark_active = False
        self._rogue_hidden_values = {}
        self._rogue_picker_lock = threading.RLock()

    @use_scope("aside", clear=True)
    def set_aside(self) -> None:
        # TODO: update put_icon_buttons()

        current_date = datetime.now().date()
        if current_date.month == 4 and current_date.day == 1:
            self.af_flag = True

        put_icon_buttons(
            Icon.DEVELOP,
            buttons=[{"label": t("Gui.Aside.Home"), "value": "Home", "color": "aside"}],
            onclick=[self.ui_develop],
        )
        put_scope("aside_instance", [
            put_scope(f"alas-instance-{i}", [])
            for i, _ in enumerate(alas_instance())
        ])
        self.set_aside_status()
        put_icon_buttons(
            Icon.SETTING,
            buttons=[
                {
                    "label": t("Gui.AddAlas.Manage"),
                    "value": "AddAlas",
                    "color": "aside",
                }
            ],
            onclick=[lambda: go_app("manage", new_window=False)],
        )


    @use_scope("aside_instance")
    def set_aside_status(self) -> None:
        flag = True

        def update(name, seq):
            with use_scope(f"alas-instance-{seq}", clear=True):
                icon_html = Icon.RUN
                rendered_state = ProcessManager.get_manager(inst).state
                if rendered_state == 1 and self.af_flag:
                    icon_html = icon_html[:31] + ' anim-rotate' + icon_html[31:]
                put_icon_buttons(
                    icon_html,
                    buttons=[{"label": name, "value": name, "color": "aside"}],
                    onclick=self.ui_alas,
                )
            return rendered_state

        if not len(self.rendered_cache) or self.load_home:
            # Reload when add/delete new instance | first start app.py | go to HomePage (HomePage load call force reload)
            flag = False
            self.inst_cache.clear()
            self.inst_cache = alas_instance()
        if flag:
            for index, inst in enumerate(self.inst_cache):
                # Check for state change
                state = ProcessManager.get_manager(inst).state
                if state != self.rendered_cache[index]:
                    self.rendered_cache[index] = update(inst, index)
                    flag = False
        else:
            self.rendered_cache.clear()
            clear("aside_instance")
            for index, inst in enumerate(self.inst_cache):
                self.rendered_cache.append(update(inst, index))
            self.load_home = False
        if not flag:
            # Redraw lost focus, now focus on aside button
            aside_name = get_localstorage("aside")
            self.active_button("aside", aside_name)

        return

    @use_scope("header_status")
    def set_status(self, state: int) -> None:
        """
        Args:
            state (int):
                1 (running)
                2 (not running)
                3 (warning, stop unexpectedly)
                4 (stop for update)
                0 (hide)
                -1 (*state not changed)
        """
        if state == -1:
            return
        clear()

        if state == 1:
            put_loading_text(t("Gui.Status.Running"), color="success")
        elif state == 2:
            put_loading_text(t("Gui.Status.Inactive"), color="secondary", fill=True)
        elif state == 3:
            put_loading_text(t("Gui.Status.Warning"), shape="grow", color="warning")
        elif state == 4:
            put_loading_text(t("Gui.Status.Updating"), shape="grow", color="success")

    @classmethod
    def set_theme(cls, theme="default") -> None:
        cls.theme = theme
        State.deploy_config.Theme = theme
        State.theme = theme
        webconfig(theme=theme)

    @use_scope("menu", clear=True)
    def alas_set_menu(self) -> None:
        """
        Set menu
        """
        put_buttons(
            [
                {
                    "label": t("Gui.MenuAlas.Overview"),
                    "value": "Overview",
                    "color": "menu",
                }
            ],
            onclick=[self.alas_overview],
        ).style(f"--menu-Overview--")

        tool_tasks = set(get_available_func())
        for menu, task_data in self.ALAS_MENU.items():
            is_tool_menu = task_data.get("page") == "tool"

            if task_data.get("menu") == "collapse":
                task_btn_list = [
                    put_buttons(
                        [
                            {
                                "label": t(f"Task.{task}.name"),
                                "value": task,
                                "color": "menu",
                            }
                        ],
                        onclick=self.alas_daemon_overview if (is_tool_menu or task in tool_tasks) else self.alas_set_group,
                    ).style(f"--menu-{task}--")
                    for task in task_data.get("tasks", [])
                ]
                put_collapse(title=t(f"Menu.{menu}.name"), content=task_btn_list)
            else:
                title = t(f"Menu.{menu}.name")
                put_html(
                    '<div class="hr-task-group-box">'
                    '<span class="hr-task-group-line"></span>'
                    f'<span class="hr-task-group-text">{title}</span>'
                    '<span class="hr-task-group-line"></span>'
                    '</div>'
                )
                for task in task_data.get("tasks", []):
                    put_buttons(
                        [
                            {
                                "label": t(f"Task.{task}.name"),
                                "value": task,
                                "color": "menu",
                            }
                        ],
                        onclick=self.alas_daemon_overview if (is_tool_menu or task in tool_tasks) else self.alas_set_group,
                    ).style(f"--menu-{task}--").style(f"padding-left: 0.75rem")

        self.alas_overview()

    @use_scope("content", clear=True)
    def alas_set_group(self, task: str) -> None:
        """
        Set arg groups from dict
        """
        self._rogue_spark_active = False
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        put_scope("_groups", [put_none(), put_scope("groups"), put_scope("navigator")])

        task_help: str = t(f"Task.{task}.help")
        if task_help:
            put_scope(
                "group__info",
                scope="groups",
                content=[put_text(task_help).style("font-size: 1rem")],
            )

        if task == "ResonanceTrade":
            self._init_resonance_market_card()

        config = self.alas_config.read_file(self.alas_name)
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if task == group[0] == "ChaoszeroRogue":
                remaining = arg_dict.copy()
                for section, names in ROGUE_SECTIONS.items():
                    settings = {name: remaining.pop(name) for name in names if name in remaining}
                    if self.set_group(group, settings, config, task, section=section):
                        self.set_navigator(group, section=section)
                arg_dict = remaining
            if self.set_group(group, arg_dict, config, task):
                self.set_navigator(group)

    @use_scope("groups")
    def set_group(self, group, arg_dict, config, task, section=None):
        group_name = group[0]
        section_name = f"{group_name}_{section}" if section else group_name
        title = f"Gui.Rogue.{section}" if section else f"{group_name}._info.name"
        server = to_server(deep_get(config, "Alas.Emulator.PackageName", "cn"))

        output_list: List[Output] = []
        seen_rogue_scopes = set()
        for arg, arg_dict in deep_iter(arg_dict, depth=1):
            output_kwargs: T_Output_Kwargs = arg_dict.copy()

            # Skip hide
            display: Optional[str] = output_kwargs.pop("display", None)
            if display == "hide":
                continue
            # Disable
            elif display == "disabled":
                output_kwargs["disabled"] = True
            # Output type
            output_kwargs["widget_type"] = output_kwargs.pop("type")

            arg_name = arg[0]  # [arg_name,]
            if group_name == "ChaoszeroRogue" and arg_name in ROGUE_HIDDEN_BUILD_ARGS:
                if arg_name in ROGUE_BUILD_PICKERS:
                    self._rogue_hidden_values[arg_name] = str(
                        deep_get(config, [task, group_name, arg_name], output_kwargs["value"]) or ""
                    )
                    scope_name = ROGUE_BUILD_PICKERS[arg_name]
                    if scope_name not in seen_rogue_scopes:
                        seen_rogue_scopes.add(scope_name)
                        scope_out = put_scope(scope_name)
                        scope_out.spec["scope"] = f"#pywebio-scope-group_{section_name}"
                        output_list.append(scope_out)
                continue
            # Internal pin widget name
            output_kwargs["name"] = f"{task}_{group_name}_{arg_name}"
            # Display title
            output_kwargs["title"] = t(f"{group_name}.{arg_name}.name")

            # Get value from config
            value = deep_get(
                config, [task, group_name, arg_name], output_kwargs["value"]
            )
            # idk
            value = str(value) if isinstance(value, datetime) else value
            if (
                group_name == "ChaoszeroRogue"
                and arg_name in ("RogueFateMainFilter", "RogueFateCoreFilter")
                and isinstance(value, str)
                and "\n" in value
            ):
                value = " > ".join(line.strip() for line in value.splitlines() if line.strip())
            # Default value
            output_kwargs["value"] = value
            # Options
            options = output_kwargs.pop("option", [])
            server_options = output_kwargs.get(f"option_{server}")
            if output_kwargs["widget_type"] == "select" and isinstance(server_options, list) and server_options:
                options = server_options
            position_labels = ROGUE_POSITION_LABELS.get(arg_name) if section else None
            if group_name == "ChaoszeroRogue" and arg_name in ROGUE_SLOT_MEMBER_ARGS:
                options, options_label = self._rogue_character_options()
                output_kwargs["widget_type"] = "select"
                value = str(value or "")
                if value not in options:
                    value = ""
                output_kwargs["value"] = value
                output_kwargs["options"] = options
                output_kwargs["options_label"] = options_label
            elif position_labels and type(value) is int and value in position_labels:
                output_kwargs["widget_type"] = "select"
                options = list(position_labels)
                output_kwargs["options"] = options
                output_kwargs["options_label"] = [t(f"Gui.Rogue.{position_labels[opt]}") for opt in options]
            else:
                position_labels = None
                output_kwargs["options"] = options
            if group_name == "ChaoszeroRogue" and arg_name in ROGUE_PICKER_WATCH_ARGS:
                self._rogue_hidden_values[arg_name] = str(value if value is not None else "")
            if (
                task == "GemsFarming"
                and group_name == "Campaign"
                and arg_name == "Event"
                and output_kwargs["widget_type"] == "select"
                and len(options) == 1
            ):
                continue
            if output_kwargs["widget_type"] == "select" and len(options) == 1:
                only_option = options[0]
                if only_option in output_kwargs.get("option_bold", []):
                    output_kwargs["widget_type"] = "state"
            # Options label
            if not (group_name == "ChaoszeroRogue" and arg_name in ROGUE_SLOT_MEMBER_ARGS) and not position_labels:
                output_kwargs["options_label"] = [t(f"{group_name}.{arg_name}.{opt}") for opt in options]
            # Help
            arg_help = t(f"{group_name}.{arg_name}.help")
            if arg_help == "" or not arg_help:
                arg_help = None
            output_kwargs["help"] = arg_help
            # Invalid feedback
            output_kwargs["invalid_feedback"] = t("Gui.Text.InvalidFeedBack", value)

            o = put_output(output_kwargs)
            if o is not None:
                # output will inherit current scope when created, override here
                o.spec["scope"] = f"#pywebio-scope-group_{section_name}"
                output_list.append(o)

        if not output_list:
            return 0

        with use_scope(f"group_{section_name}"):
            put_text(t(title))
            group_help = "" if section else t(f"{group_name}._info.help")
            if group_help != "":
                put_text(group_help)
            put_html('<hr class="hr-group">')
            if section == "Events":
                put_scope("rogue_event_selector", [
                    put_link(t("Gui.Rogue.OpenSelector"), url=f".{ROGUE_SELECTOR_ROUTE}/index.html", new_window=True),
                    put_text(t("Gui.Rogue.SelectorHelp")).style("--arg-help--"),
                ])
            for output in output_list:
                output.show()
            if section == "Events":
                put_scope("rogue_event_recorder")

        if section == "Build":
            self._rogue_spark_active = True
            self._render_rogue_pickers(config)
        elif section == "Events":
            self._render_rogue_event_recorder()

        return len(output_list)

    @staticmethod
    def _rogue_character_options():
        chars, _ = rogue_cards.spark_catalog()
        ordered = sorted(chars, key=lambda entry: (rogue_cards.character_name(entry, lang.LANG), entry["id"]))
        options = [""] + [entry["id"] for entry in ordered]
        labels = [t("Gui.Rogue.Unselected")] + [rogue_cards.character_name(entry, lang.LANG) for entry in ordered]
        return options, labels

    def _get_rogue_picker_lock(self):
        lock = getattr(self, "_rogue_picker_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._rogue_picker_lock = lock
        return lock

    def _rogue_pin_or_config(self, config, arg_name: str, default: str = "") -> str:
        if arg_name in self._rogue_hidden_values:
            return self._rogue_hidden_values[arg_name]
        pin_name = f"ChaoszeroRogue_ChaoszeroRogue_{arg_name}"
        try:
            value = pin[pin_name]
            if value is not None:
                return str(value)
        except Exception:
            pass
        if config is None:
            config = self.alas_config.read_file(self.alas_name)
        return str(deep_get(config, ["ChaoszeroRogue", "ChaoszeroRogue", arg_name], default) or "")

    def _rogue_selected_slots(self, config=None):
        chars, _ = rogue_cards.spark_catalog()
        char_map = {entry["id"]: entry for entry in chars}
        selected, seen_chars = [], set()
        for slot_idx, (slot_arg, label_key) in enumerate(zip(ROGUE_SLOT_MEMBER_ARGS, ("Slot1", "Slot2", "Slot3")), 1):
            cid = self._rogue_pin_or_config(config, slot_arg, "").strip()
            if cid and cid in char_map and cid not in seen_chars:
                seen_chars.add(cid)
                selected.append((slot_idx, t(f"Gui.Rogue.{label_key}"), cid, rogue_cards.character_name(char_map[cid], lang.LANG)))
        return selected

    def _rogue_remove_slot(self, config=None) -> int:
        raw = self._rogue_pin_or_config(config, "RogueRemoveMember", "1").strip()
        try:
            slot = int(raw)
        except (TypeError, ValueError):
            slot = 1
        return slot if slot in (1, 2, 3) else 1

    def _render_rogue_pickers(self, config=None) -> None:
        with self._get_rogue_picker_lock():
            self._render_rogue_spark_picker(config)
            self._render_rogue_remove_picker(config)

    def _render_rogue_spark_picker(self, config=None) -> None:
        if not self._rogue_spark_active:
            return
        with self._get_rogue_picker_lock():
            _, by_char = rogue_cards.spark_catalog()
            spark_text = self._rogue_pin_or_config(config, "RogueSparkFilter", "")
            god_text = self._rogue_pin_or_config(config, "RogueGodSparkFilter", "")
            rules = rogue_cards.parse_spark_filter(spark_text)
            god_rules = rogue_cards.parse_god_spark_filter(god_text)
            norm_rules = {rogue_cards.normalize(k): v for k, v in rules.items()}
            norm_god_rules = {rogue_cards.normalize(k): v for k, v in god_rules.items()}
            selected = [item for item in self._rogue_selected_slots(config) if item[2] in by_char]
            targets = {}

            with use_scope("rogue_spark_picker", clear=True):
                put_text(t("Gui.Rogue.SparkPickerTitle")).style("--arg-title--")
                if not selected:
                    put_text(t("Gui.Rogue.SparkPickerEmpty")).style("--arg-help--")
                for _, slot_label, cid, char_name in selected:
                    put_text(f"{slot_label} · {char_name}").style("--arg-title--")
                    for card in by_char[cid]:
                        card_name = card["name"]
                        raw_val = rules.get(card_name) or norm_rules.get(rogue_cards.normalize(card_name), "")
                        norm_choice = rogue_cards.parse_form_choice(raw_val)
                        neutral_label = f"{ROGUE_CIRCLED_INDEX[5]} {t('Gui.Rogue.SparkFormNeutral')}"
                        options = (
                            [""]
                            + [str(f["index"]) for f in card["forms"]]
                            + [rogue_cards.NEUTRAL_FORM_VALUE]
                        )
                        options_label = (
                            [t("Gui.Rogue.SparkFormAuto")]
                            + [f"{ROGUE_CIRCLED_INDEX[f['index'] - 1]} {f['desc']}" for f in card["forms"]]
                            + [neutral_label]
                        )
                        help_text = None
                        if norm_choice == rogue_cards.NEUTRAL_FORM_VALUE:
                            current = rogue_cards.NEUTRAL_FORM_VALUE
                            help_text = neutral_label
                        elif norm_choice in options and norm_choice != "":
                            current = norm_choice
                            form = card["forms"][int(norm_choice) - 1]
                            help_text = f"{ROGUE_CIRCLED_INDEX[form['index'] - 1]} {form['desc']}"
                        elif raw_val:
                            current = ROGUE_SPARK_CUSTOM_OPTION
                            options.append(ROGUE_SPARK_CUSTOM_OPTION)
                            options_label.append(f"{t('Gui.Rogue.SparkFormCustom')}: {raw_val}")
                            help_text = raw_val
                        else:
                            current = ""

                        if rules.get(card_name) and help_text:
                            targets[card_name] = f"{card_name} · {help_text}"
                        pin_name = f"rogue_spark_card_{card['id']}"
                        put_arg_select({
                            "name": pin_name,
                            "title": card_name,
                            "value": current,
                            "options": options,
                            "options_label": options_label,
                            "help": help_text,
                        }).show()
                        pin_on_change(
                            name=pin_name,
                            onchange=partial(self._on_rogue_spark_card_change, card_name),
                            clear=True,
                        )

                        selected_gods = list(
                            god_rules.get(card_name)
                            or norm_god_rules.get(rogue_cards.normalize(card_name), [])
                        )
                        avail_gods = []
                        avail_god_labels = []
                        for entry in rogue_cards.god_spark_option_entries(card, current):
                            desc = entry['desc']
                            if desc in selected_gods:
                                continue
                            tags = [
                                tag for tag in (
                                    entry.get('god_name'),
                                    '出擊' if entry.get('is_sortie') else '',
                                ) if tag
                            ]
                            avail_gods.append(desc)
                            avail_god_labels.append(
                                f"{desc} ({' · '.join(tags)})" if tags else desc
                            )
                        god_help = (
                            t("Gui.Rogue.GodSparkOrderPrefix", items=" > ".join(
                                f"{idx}. {item}" for idx, item in enumerate(selected_gods, 1)
                            ))
                            if selected_gods
                            else t("Gui.Rogue.GodSparkHelpEmpty")
                        )
                        god_pin_name = f"rogue_god_spark_add_{card['id']}"
                        put_arg_select({
                            "name": god_pin_name,
                            "title": f"{card_name} · {t('Gui.Rogue.GodSparkTitle')}",
                            "value": "",
                            "options": [""] + avail_gods,
                            "options_label": [t("Gui.Rogue.GodSparkAdd")] + avail_god_labels,
                            "help": god_help,
                        }).show()
                        pin_on_change(
                            name=god_pin_name,
                            onchange=partial(self._on_rogue_god_spark_add, card_name),
                            clear=True,
                        )
                        if selected_gods:
                            buttons = []
                            for idx, desc in enumerate(selected_gods):
                                if idx > 0:
                                    buttons.append({"label": f"↑ {idx + 1}", "value": f"up:{idx}"})
                                buttons.append({"label": f"× {idx + 1}. {desc}", "value": f"del:{idx}"})
                            if len(selected_gods) >= 2:
                                buttons.append({"label": t("Gui.Rogue.GodSparkClear"), "value": "clear", "color": "danger"})
                            put_buttons(
                                buttons=buttons,
                                onclick=partial(self._on_rogue_god_spark_action, card_name),
                                small=True,
                            )

            with use_scope("rogue_spark_check_picker", clear=True):
                target = self._rogue_pin_or_config(config, "RogueSparkCheckCard")
                pin_name = "rogue_spark_check_card"
                put_arg_select({
                    "name": pin_name,
                    "title": t("ChaoszeroRogue.RogueSparkCheckCard.name"),
                    "help": t("ChaoszeroRogue.RogueSparkCheckCard.help"),
                    "value": target if target in targets else "",
                    "options": ["", *targets],
                    "options_label": [t("Gui.Rogue.Unselected"), *targets.values()],
                }).show()
                pin_on_change(name=pin_name, onchange=self._on_rogue_spark_check_card_change, clear=True)

    def _render_rogue_remove_picker(self, config=None) -> None:
        if not self._rogue_spark_active:
            return
        with self._get_rogue_picker_lock():
            by_char = rogue_cards.deck_catalog()
            delete_text = self._rogue_pin_or_config(config, "RogueDeleteFilter", "")
            rules = dict(rogue_cards.parse_delete_filter(delete_text))
            norm_rules = {rogue_cards.normalize(k): v for k, v in rules.items() if rogue_cards.normalize(k)}
            selected = [item for item in self._rogue_selected_slots(config) if item[2] in by_char]
            preferred_slot = self._rogue_remove_slot(config)
            ordered = [item for item in selected if item[0] == preferred_slot] + [
                item for item in selected if item[0] != preferred_slot
            ]
            kind_key = {"basic": "CardKindBasic", "spark": "CardKindSpark", "unique": "CardKindUnique"}

            with use_scope("rogue_remove_picker", clear=True):
                put_text(t("Gui.Rogue.RemovePickerTitle")).style("--arg-title--")
                if not ordered:
                    put_text(t("Gui.Rogue.RemovePickerEmpty")).style("--arg-help--")
                    return
                for slot_idx, slot_label, cid, char_name in ordered:
                    header = (
                        f"{slot_label} · {char_name}（{t('Gui.Rogue.PriorityTag')}）"
                        if slot_idx == preferred_slot
                        else f"{slot_label} · {char_name}"
                    )
                    put_text(header).style("--arg-title--")
                    for card in by_char[cid]:
                        card_name = card["name"]
                        max_count = card["count"]
                        raw_count = rules.get(card_name)
                        if raw_count is None:
                            raw_count = norm_rules.get(rogue_cards.normalize(card_name), 0)
                        current = str(min(max_count, max(0, int(raw_count))))
                        options = ["0"] + [str(n) for n in range(1, max_count + 1)]
                        options_label = [t("Gui.Rogue.RemoveKeep")] + [
                            t("Gui.Rogue.RemoveOne") if n == 1 else t("Gui.Rogue.RemoveCount", count=n)
                            for n in range(1, max_count + 1)
                        ]
                        pin_name = f"rogue_remove_card_{card['id']}"
                        put_arg_select({
                            "name": pin_name,
                            "title": card_name,
                            "value": current,
                            "options": options,
                            "options_label": options_label,
                            "help": t(f"Gui.Rogue.{kind_key[card['kind']]}", count=max_count),
                        }).show()
                        pin_on_change(
                            name=pin_name,
                            onchange=partial(self._on_rogue_remove_card_change, card_name),
                            clear=True,
                        )

    def _update_rogue_hidden_filter(self, arg_name: str, updater, *args) -> None:
        current = self._rogue_pin_or_config(None, arg_name, "")
        updated = updater(current, *args)
        self._rogue_hidden_values[arg_name] = updated
        self.modified_config_queue.put({
            "name": f"ChaoszeroRogue.ChaoszeroRogue.{arg_name}",
            "value": updated,
        })

    def _on_rogue_spark_card_change(self, card_name: str, new_value: str) -> None:
        if new_value == ROGUE_SPARK_CUSTOM_OPTION:
            return
        with self._get_rogue_picker_lock():
            self._update_rogue_hidden_filter("RogueSparkFilter", rogue_cards.update_spark_filter, card_name, new_value)
            self._render_rogue_spark_picker()

    def _on_rogue_god_spark_add(self, card_name: str, new_affix: str) -> None:
        affix = (new_affix or "").strip()
        if not affix:
            return
        with self._get_rogue_picker_lock():
            god_rules = rogue_cards.parse_god_spark_filter(self._rogue_pin_or_config(None, "RogueGodSparkFilter", ""))
            norm_rules = {rogue_cards.normalize(k): v for k, v in god_rules.items()}
            items = list(god_rules.get(card_name) or norm_rules.get(rogue_cards.normalize(card_name), []))
            if affix not in items:
                items.append(affix)
            self._update_rogue_hidden_filter("RogueGodSparkFilter", rogue_cards.update_god_spark_filter, card_name, items)
            self._render_rogue_spark_picker()

    def _on_rogue_god_spark_action(self, card_name: str, action: str) -> None:
        with self._get_rogue_picker_lock():
            god_rules = rogue_cards.parse_god_spark_filter(self._rogue_pin_or_config(None, "RogueGodSparkFilter", ""))
            norm_rules = {rogue_cards.normalize(k): v for k, v in god_rules.items()}
            items = list(god_rules.get(card_name) or norm_rules.get(rogue_cards.normalize(card_name), []))
            if action == "clear":
                items = []
            elif isinstance(action, str) and ":" in action:
                op, raw_idx = action.split(":", 1)
                try:
                    idx = int(raw_idx)
                except ValueError:
                    return
                if op == "up" and 1 <= idx < len(items):
                    items[idx - 1], items[idx] = items[idx], items[idx - 1]
                elif op == "del" and 0 <= idx < len(items):
                    items.pop(idx)
            self._update_rogue_hidden_filter("RogueGodSparkFilter", rogue_cards.update_god_spark_filter, card_name, items)
            self._render_rogue_spark_picker()

    def _on_rogue_spark_check_card_change(self, value: str) -> None:
        with self._get_rogue_picker_lock():
            self._update_rogue_hidden_filter("RogueSparkCheckCard", lambda _: value or "")

    def _on_rogue_remove_card_change(self, card_name: str, new_value: str) -> None:
        with self._get_rogue_picker_lock():
            self._update_rogue_hidden_filter("RogueDeleteFilter", rogue_cards.update_delete_filter, card_name, new_value)

    def _render_rogue_event_recorder(self) -> None:
        summary = rogue_events.summarize_seen_events()
        total_seen = sum(item["seen"] for item in summary)
        total_all = sum(item["total"] for item in summary)
        with use_scope("rogue_event_recorder", clear=True):
            put_html('<hr class="hr-group">')
            put_text(t("Gui.Rogue.EventRecorderTitle")).style("--arg-title--")
            put_text(t("Gui.Rogue.EventRecorderHelp", seen=total_seen, total=total_all)).style("--arg-help--")
            put_buttons(
                buttons=[
                    {"label": t("Gui.Rogue.EventRecorderRefresh"), "value": "refresh"},
                    {"label": t("Gui.Rogue.EventRecorderClear"), "value": "clear", "color": "danger"},
                ],
                onclick=[self._render_rogue_event_recorder, self._clear_rogue_event_recorder],
                small=True,
            )
            for item in summary:
                lines = [
                    f"{'✓' if is_seen else '○'} {ev_name} ({ev_id})"
                    for ev_id, ev_name, is_seen in item["events"]
                ]
                put_collapse(
                    title=f"{item['world']}　{item['seen']} / {item['total']}",
                    content=[put_text("\n".join(lines)).style("white-space: pre-wrap; font-size: 0.85rem;")],
                )

    def _clear_rogue_event_recorder(self) -> None:
        rogue_events.clear_seen_events()
        self._render_rogue_event_recorder()
        toast(t("Gui.Rogue.EventRecorderCleared"), color="success")

    @use_scope("navigator")
    def set_navigator(self, group, section=None):
        name = f"{group[0]}_{section}" if section else group[0]
        js = f"""
            $("#pywebio-scope-groups").scrollTop(
                $("#pywebio-scope-group_{name}").position().top
                + $("#pywebio-scope-groups").scrollTop() - 59
            )
        """
        put_button(
            label=t(f"Gui.Rogue.{section}" if section else f"{group[0]}._info.name"),
            onclick=lambda: run_js(js),
            color="navigator",
        )

    @use_scope("content", clear=True)
    def alas_overview(self) -> None:
        self._rogue_spark_active = False
        self.init_menu(name="Overview")
        self.set_title(t(f"Gui.MenuAlas.Overview"))

        put_scope("overview", [put_scope("schedulers"), put_scope("logs")])

        with use_scope("schedulers"):
            put_scope(
                "scheduler-bar",
                [
                    put_text(t("Gui.Overview.Scheduler")).style(
                        "font-size: 1.25rem; margin: auto .5rem auto;"
                    ),
                    put_scope("scheduler_btn"),
                ],
            )
            put_scope(
                "running",
                [
                    put_text(t("Gui.Overview.Running")),
                    put_html('<hr class="hr-group">'),
                    put_scope("running_tasks"),
                ],
            )
            put_scope(
                "pending",
                [
                    put_text(t("Gui.Overview.Pending")),
                    put_html('<hr class="hr-group">'),
                    put_scope("pending_tasks"),
                ],
            )
            put_scope(
                "waiting",
                [
                    put_text(t("Gui.Overview.Waiting")),
                    put_html('<hr class="hr-group">'),
                    put_scope("waiting_tasks"),
                ],
            )

        switch_scheduler = BinarySwitchButton(
            label_on=t("Gui.Button.Stop"),
            label_off=t("Gui.Button.Start"),
            onclick_on=lambda: self.alas.stop(),
            onclick_off=lambda: self.alas.start(None, updater.event),
            get_state=lambda: self.alas.alive,
            color_on="off",
            color_off="on",
            scope="scheduler_btn",
        )

        log = RichLog("log")

        with use_scope("logs"):
            put_scope(
                "log-bar",
                [
                    put_text(t("Gui.Overview.Log")).style(
                        "font-size: 1.25rem; margin: auto .5rem auto;"
                    ),
                    put_scope(
                        "log-bar-btns",
                        [
                            put_scope("log_scroll_btn"),
                        ],
                    ),
                    # Last on purpose: the bar wraps, and a full-width block
                    # placed before it would push the scroll button onto a
                    # second line of its own.
                    put_scope("start_all_btn"),
                ],
            )
            put_scope("log", [put_html("")])

        with use_scope("start_all_btn"):
            for group in self.alas_game_groups():
                # One `put_button` per game instead of one `put_buttons`: that
                # renders a joined button group (no gap, square ends), which
                # reads as one solid block. Separate buttons let the stylesheet
                # wrap them into rows - see `#pywebio-scope-start_all_btn`.
                #
                # They live in the log bar, not in the scheduler bar: the
                # scheduler column is 16~20rem wide (`alas-pc.css`) and those
                # seven rows were taking the space the running / pending /
                # waiting panels need. The log column is the wide one.
                put_button(
                    label=t("Gui.Button.StartAll", t(f"Menu.{group}.name")),
                    onclick=partial(self.alas_start_all, group),
                    color="on",
                )

        log.console.width = log.get_width()

        switch_log_scroll = BinarySwitchButton(
            label_on=t("Gui.Button.ScrollON"),
            label_off=t("Gui.Button.ScrollOFF"),
            onclick_on=lambda: log.set_scroll(False),
            onclick_off=lambda: log.set_scroll(True),
            get_state=lambda: log.keep_bottom,
            color_on="on",
            color_off="off",
            scope="log_scroll_btn",
        )

        self.task_handler.add(switch_scheduler.g(), 1, True)
        self.task_handler.add(switch_log_scroll.g(), 1, True)
        self.task_handler.add(self.alas_update_overview_task, 10, True)
        self.task_handler.add(log.put_log(self.alas), 0.25, True)

    def _init_alas_config_watcher(self) -> None:
        def put_queue(path, value):
            self.modified_config_queue.put({"name": path, "value": value})
            if path in ROGUE_SPARK_WATCH_PATHS:
                arg_name = path.rsplit(".", 1)[-1]
                self._rogue_hidden_values[arg_name] = "" if value is None else str(value)
                if self._rogue_spark_active:
                    if arg_name == "RogueRemoveMember":
                        self._render_rogue_remove_picker()
                    else:
                        self._render_rogue_pickers()

        for path in get_alas_config_listen_path(self.ALAS_ARGS):
            pin_on_change(
                name="_".join(path),
                onchange=partial(put_queue, ".".join(path)),
                clear=True,
            )
        logger.info("Init config watcher done.")

    def _alas_thread_update_config(self) -> None:
        modified = {}
        while self.alive:
            try:
                d = self.modified_config_queue.get(timeout=10)
                config_name = self.alas_name
                config_updater = self.alas_config
            except queue.Empty:
                continue
            modified[d["name"]] = d["value"]
            while True:
                try:
                    d = self.modified_config_queue.get(timeout=1)
                    modified[d["name"]] = d["value"]
                except queue.Empty:
                    self._save_config(modified, config_name, config_updater)
                    modified.clear()
                    break

    def _save_config(
            self,
            modified: Dict[str, str],
            config_name: str,
            config_updater: AlasConfig = State.config_updater,
    ) -> None:
        try:
            valid = []
            invalid = []
            config = config_updater.read_file(config_name)
            n = datetime.now()
            for p, v in deep_iter(config, depth=3):
                if p[-1].endswith('un') and not isinstance(v, bool):
                    if (v - n).days >= 31:
                        deep_set(config, p, '')
            for k, v in modified.copy().items():
                valuetype = deep_get(self.ALAS_ARGS, k + ".valuetype")
                v = parse_pin_value(v, valuetype)
                validate = deep_get(self.ALAS_ARGS, k + ".validate")
                if not len(str(v)):
                    default = deep_get(self.ALAS_ARGS, k + ".value")
                    modified[k] = default
                    deep_set(config, k, default)
                    valid.append(k)
                    pin["_".join(k.split("."))] = default

                elif not validate or re_fullmatch(validate, v):
                    deep_set(config, k, v)
                    modified[k] = v
                    valid.append(k)
                    for set_key, set_value in config_updater.save_callback(k, v):
                        modified[set_key] = set_value
                        deep_set(config, set_key, set_value)
                        valid.append(set_key)
                        pin["_".join(set_key.split("."))] = to_pin_value(set_value)
                else:
                    modified.pop(k)
                    invalid.append(k)
                    logger.warning(f"Invalid value {v} for key {k}, skip saving.")
            self.pin_remove_invalid_mark(valid)
            self.pin_set_invalid_mark(invalid)
            if modified:
                toast(
                    t("Gui.Toast.ConfigSaved"),
                    duration=1,
                    position="right",
                    color="success",
                )
                logger.info(
                    f"Save config {filepath_config(config_name)}, {dict_to_kv(modified)}"
                )
                config_updater.write_file(config_name, config)
        except Exception as e:
            logger.exception(e)

    def alas_update_overview_task(self) -> None:
        if not self.visible:
            return
        self.alas_config.load()
        self.alas_config.get_next_task()

        if len(self.alas_config.pending_task) >= 1:
            if self.alas.alive:
                running = self.alas_config.pending_task[:1]
                pending = self.alas_config.pending_task[1:]
            else:
                running = []
                pending = self.alas_config.pending_task[:]
        else:
            running = []
            pending = []
        waiting = self.alas_config.waiting_task

        def put_task(func: Function):
            with use_scope(f"overview-task_{func.command}"):
                col_items = [
                    put_text(t(f"Task.{func.command}.name")).style("--arg-title--"),
                    put_text(str(func.next_run)).style("--arg-help--"),
                ]
                if func.command == "ResonanceTrade" and self.alas_name:
                    from module.resonance.market import format_market_summary, load_market_status
                    from module.resonance.profit_log import summarize_profit_history

                    record = load_market_status(self.alas_name)
                    if record:
                        summary = format_market_summary(record)
                        col_items.append(
                            put_text(summary["overview_line"]).style(
                                f"--arg-help--; color: {summary['color']}; font-weight: 500;"
                            )
                        )
                    ps = summarize_profit_history(self.alas_name)
                    if ps["overview_line"]:
                        col_items.append(
                            put_text(ps["overview_line"]).style("--arg-help--")
                        )
                put_column(col_items, size="auto " * len(col_items))
                put_button(
                    label=t("Gui.Button.Setting"),
                    onclick=lambda: self.alas_set_group(func.command),
                    color="off",
                )

        clear("running_tasks")
        clear("pending_tasks")
        clear("waiting_tasks")
        with use_scope("running_tasks"):
            if running:
                for task in running:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
        with use_scope("pending_tasks"):
            if pending:
                for task in pending:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")
        with use_scope("waiting_tasks"):
            if waiting:
                for task in waiting:
                    put_task(task)
            else:
                put_text(t("Gui.Overview.NoTask")).style("--overview-notask-text--")

    def alas_update_daemon_round(self, task: str):
        """返回一个周期回调：读配置里的 Round，重绘工具页顶部的「第 N 轮」。

        参数区只在页面渲染时读一次配置，而刷初始一轮要十几分钟，用户不可能每轮
        手动刷新页面。这里用 `clear()` + `use_scope()` 每秒重绘一小块，
        和 `alas_update_overview_task()` 是同一套机制。
        """

        # 轮数一轮才变一次，没必要每秒重绘 DOM：记下上次的值，变了才重画。
        last = {"value": None}

        def _update():
            if not self.alas_name:
                return
            try:
                # ❗不能用 `self.alas_config.read_file()`：它会走 `config_update()`，
                # 把 `display: hide` 且非 stored 的字段强制重置成模板默认值（见
                # config_updater.config_update），读到的永远是 0。
                # 也不能用 utils.read_file()：它每秒打一行 `read: ./config/alas.json`。
                # 直接读原始 json，既拿到脚本写进去的真实轮数，又不刷屏。
                with open(filepath_config(self.alas_name), "r", encoding="utf-8") as f:
                    config = json.load(f)
                value = deep_get(config, [task, task, "Round"], 0)
            except Exception:
                # 任务进程正在写配置文件时可能读到半个 json，下一拍再来。
                return
            if value == last["value"]:
                return
            last["value"] = value
            clear("daemon_round")
            with use_scope("daemon_round"):
                put_text(t("Gui.Overview.Round", value=value)).style(
                    "font-size: 1.25rem; margin: .5rem 0;"
                )

        return _update

    def _init_resonance_market_card(self) -> None:
        """Render live ResonanceTrade market quality and 30-day profit cards with polling."""
        from module.resonance.market import load_market_status
        from module.resonance.profit_log import summarize_profit_history

        with use_scope("groups"):
            put_scope(
                "group_ResonanceMarketStatus",
                [
                    put_row(
                        [
                            put_text("实时行情状态").style(
                                "font-size: 1.25rem; font-weight: 500; margin: auto .25rem;"
                            ),
                            put_button(
                                label="立即检测行情",
                                onclick=self._on_click_check_resonance_market,
                                color="info",
                            ),
                        ],
                        size="1fr auto",
                    ),
                    put_html('<hr class="hr-group">'),
                    put_scope("resonance_market_body"),
                ],
            ).style("--group-card--")
            put_scope(
                "group_ResonanceProfitLog",
                [
                    put_text("跑商利润记录（近30天 · 按05:00日结）").style(
                        "font-size: 1.25rem; font-weight: 500; margin: 0 .25rem;"
                    ),
                    put_html('<hr class="hr-group">'),
                    put_scope("resonance_profit_body"),
                ],
            ).style("--group-card--")
        self._render_resonance_market_body(load_market_status(self.alas_name))
        self._render_resonance_profit_body(summarize_profit_history(self.alas_name))
        self.task_handler.add(self._alas_update_resonance_market_status(), 3, True)

    def _render_resonance_market_body(self, record) -> None:
        clear("resonance_market_body")
        with use_scope("resonance_market_body"):
            if not record:
                put_text("尚未检测行情，点击右上角「立即检测行情」或启动跑商后自动更新。").style(
                    "--arg-help--"
                )
                return
            from module.resonance.market import format_market_summary

            summary = format_market_summary(record)
            put_text(summary["badge"]).style(
                f"--arg-title--; color: {summary['color']}; font-weight: 600;"
            )
            for line in summary["detail_lines"]:
                put_text(line).style("--arg-help--")

    def _render_resonance_profit_body(self, summary) -> None:
        from module.resonance.profit_log import format_delta_html

        clear("resonance_profit_body")
        with use_scope("resonance_profit_body"):
            if summary["active_days"] == 0:
                put_text("暂无跑商利润记录，完成自动卖出后将自动统计每日利润与涨跌。").style(
                    "--arg-help--"
                )
                return
            today_html = (
                f"今日利润：<b>{summary['today_total']:,}</b>"
                f"（{summary['today_count']} 笔，均笔 {summary['today_avg']:,}）"
                f" ｜ 较前日：{format_delta_html(summary['today_delta_text'], summary['today_delta_color'])}"
            )
            put_html(today_html).style("--arg-title--")
            best = summary["best_day"]
            best_part = f" ｜ 最高单日：{best[0]} ({best[1]:,})" if best else ""
            put_text(
                f"近30天累计：{summary['total_30d']:,}（{summary['active_days']} 天 / "
                f"{summary['count_30d']} 笔，日均 {summary['avg_day_30d']:,}）{best_part}"
            ).style("--arg-help--")
            if summary["today_trades"]:
                trade_rows = [
                    [
                        tr.get("time", ""),
                        f"{tr.get('from') or '?'} -> {tr.get('to') or '?'}",
                        f"{tr.get('profit', 0):+,}" + (" (预估)" if tr.get("estimated") else ""),
                    ]
                    for tr in summary["today_trades"]
                ]
                put_collapse(
                    f"今日交易明细（{summary['today_count']} 笔）",
                    [put_table(trade_rows, header=["时间", "路线", "单次利润"])],
                    open=False,
                )
            daily_rows = [
                [
                    row["date"],
                    row["count"],
                    f"{row['total']:,}",
                    put_html(format_delta_html(row["delta_text"], row["delta_color"])),
                ]
                for row in summary["daily_rows"]
            ]
            put_collapse(
                f"近30天每日利润与涨跌（{summary['active_days']} 天）",
                [put_table(daily_rows, header=["日期", "笔数", "当日利润", "较前日涨跌"])],
                open=True,
            )

    def _alas_update_resonance_market_status(self):
        """Return a 3s polling callback refreshing Resonance market & profit cards on updates."""
        from module.resonance.market import load_market_status
        from module.resonance.profit_log import load_profit_days, summarize_profit_history

        last = {
            "market": load_market_status(self.alas_name),
            "profit": load_profit_days(self.alas_name),
        }

        def _update():
            if not self.alas_name or not self.visible or self.page != "ResonanceTrade":
                return
            record = load_market_status(self.alas_name)
            if record != last["market"]:
                last["market"] = record
                self._render_resonance_market_body(record)
            profit_days = load_profit_days(self.alas_name)
            if profit_days != last["profit"]:
                last["profit"] = profit_days
                self._render_resonance_profit_body(summarize_profit_history(self.alas_name))

        return _update

    def _on_click_check_resonance_market(self) -> None:
        if not self.alas_name:
            return
        from module.resonance.market import load_market_status, refresh_market_status_for_webui

        clear("resonance_market_body")
        with use_scope("resonance_market_body"):
            put_text("正在拉取科伦巴最新行情...").style("--arg-help--")
        toast("正在检测科伦巴实时行情...", duration=2, position="right", color="info")
        try:
            with open(filepath_config(self.alas_name), "r", encoding="utf-8") as f:
                cfg = json.load(f)
            trade_cfg = deep_get(cfg, ["ResonanceTrade", "ResonanceTrade"], {})
            record = refresh_market_status_for_webui(self.alas_name, trade_cfg)
            self._render_resonance_market_body(record)
            if record:
                toast(
                    f"行情指数 {record['index']:.1f} 已更新",
                    duration=2,
                    position="right",
                    color="success",
                )
        except Exception as e:
            logger.exception(e)
            self._render_resonance_market_body(load_market_status(self.alas_name))
            toast(f"行情检测失败: {e}", duration=3, position="right", color="error")

    def alas_game_groups(self) -> List[str]:
        """
        Menu groups that are games, in the order of the sidebar.

        A group is a game when its name is a registered asset namespace, which
        is what `module/config/server.py` holds. The GUI keeps no list of its
        own, so registering a game is enough to get its button.

        Returns:
            List[str]: Menu group names, such as `['Hazeworld', 'Lostsword']`.
        """
        return [group for group in self.ALAS_MENU if group.lower() in VALID_SERVER]

    def alas_start_all(self, group: str) -> None:
        """
        Make every enabled task of one game due now, then start the scheduler.

        The tasks are made due instead of being called one after another: the
        scheduler is what knows the order (`SCHEDULER_PRIORITY`), how to switch
        the game once instead of per task, and how to handle a failure, a delay
        or the session claim. Calling tasks directly would run them in the order
        they are listed in `task.yaml`, which is not the order they are meant to
        run in.

        A task the user switched off in its own `Scheduler.Enable` is left
        alone: the button means "run everything I have switched on", not "turn
        everything on". The number of skipped tasks is reported, so a skip is
        never silent.

        Args:
            group (str): Menu group of the game, such as `Hazeworld`.
        """
        tasks = deep_get(self.ALAS_MENU, [group, 'tasks'], default=[])
        config = self.alas_config.read_file(self.alas_name)
        now = datetime.now().replace(microsecond=0)

        tool_tasks = set(get_available_func())
        queued = []
        skipped = []
        for task in tasks:
            if task in tool_tasks:
                continue
            if deep_get(config, [task, 'Scheduler', 'Enable'], default=False):
                deep_set(config, [task, 'Scheduler', 'NextRun'], now)
                queued.append(task)
            else:
                skipped.append(task)

        if queued:
            # Written before the scheduler starts: a task list written after it
            # has read the config is only picked up by the next reload, and a
            # reload that lands in the same second as the read is missed
            # (`ConfigWatcher` compares whole seconds).
            self.alas_config.write_file(self.alas_name, config)
            logger.info(f'Start all tasks of `{group}`: {queued}, disabled: {skipped}')

        toast(
            t("Gui.Toast.StartAll", len(queued), len(skipped)),
            duration=3,
            position="right",
            color="success" if queued else "warn",
        )

        if queued and not self.alas.alive:
            self.alas.start(None, updater.event)

        self.alas_update_overview_task()

    @use_scope("content", clear=True)
    def alas_daemon_overview(self, task: str) -> None:
        self._rogue_spark_active = False
        self.init_menu(name=task)
        self.set_title(t(f"Task.{task}.name"))

        log = RichLog("log")

        if self.is_mobile:
            put_scope(
                "daemon-overview",
                [
                    put_scope("scheduler-bar"),
                    put_scope("groups"),
                    put_scope("log-bar"),
                    put_scope("log", [put_html("")]),
                ],
            )
        else:
            put_scope(
                "daemon-overview",
                [
                    put_none(),
                    put_scope(
                        "_daemon",
                        [
                            put_scope(
                                "_daemon_upper",
                                [put_scope("scheduler-bar"), put_scope("log-bar")],
                            ),
                            put_scope("groups"),
                            put_scope("log", [put_html("")]),
                        ],
                    ),
                    put_none(),
                ],
            )

        log.console.width = log.get_width()

        with use_scope("scheduler-bar"):
            put_text(t("Gui.Overview.Scheduler")).style(
                "font-size: 1.25rem; margin: auto .5rem auto;"
            )
            put_scope("scheduler_btn")

        switch_scheduler = BinarySwitchButton(
            label_on=t("Gui.Button.Stop"),
            label_off=t("Gui.Button.Start"),
            onclick_on=lambda: self.alas.stop(),
            onclick_off=lambda: self.alas.start(task),
            get_state=lambda: self.alas.alive,
            color_on="off",
            color_off="on",
            scope="scheduler_btn",
        )

        with use_scope("log-bar"):
            put_text(t("Gui.Overview.Log")).style(
                "font-size: 1.25rem; margin: auto .5rem auto;"
            )
            put_scope(
                "log-bar-btns",
                [
                    put_scope("log_scroll_btn"),
                ],
            )

        switch_log_scroll = BinarySwitchButton(
            label_on=t("Gui.Button.ScrollON"),
            label_off=t("Gui.Button.ScrollOFF"),
            onclick_on=lambda: log.set_scroll(False),
            onclick_off=lambda: log.set_scroll(True),
            get_state=lambda: log.keep_bottom,
            color_on="on",
            color_off="off",
            scope="log_scroll_btn",
        )

        config = self.alas_config.read_file(self.alas_name)
        # 工具页也要能看到任务说明（测试状态、已知限制都写在 Task.<name>.help 里）。
        # `alas_set_group()` 本来就有这一句，工具页以前没有 —— 工具大多还在试验阶段，
        # 说明比参数本身更重要。
        task_help = t(f"Task.{task}.help")
        if task_help:
            with use_scope("groups"):
                put_text(task_help).style("font-size: 1rem")
        # 长循环工具（刷初始）的当前轮数：单独显示，免得在几百行日志里翻。
        # 只有定义过 `{task}.{task}.Round` 的工具才显示，其它工具页不受影响。
        if deep_get(self.ALAS_ARGS, f"{task}.{task}.Round", None) is not None:
            with use_scope("groups"):
                put_scope("daemon_round")
            self.task_handler.add(self.alas_update_daemon_round(task), 1, True)
        for group, arg_dict in deep_iter(self.ALAS_ARGS[task], depth=1):
            if group[0] == "Storage":
                continue
            self.set_group(group, arg_dict, config, task)

        run_js(
            """
            $("#pywebio-scope-log").css(
                "grid-row-start",
                -2 - $("#pywebio-scope-_daemon").children().filter(
                    function(){
                        return $(this).css("display") === "none";
                    }
                ).length
            );
            $("#pywebio-scope-log").css(
                "grid-row-end",
                -1
            );
        """
        )

        self.task_handler.add(switch_scheduler.g(), 1, True)
        self.task_handler.add(switch_log_scroll.g(), 1, True)
        self.task_handler.add(log.put_log(self.alas), 0.25, True)

    @use_scope("menu", clear=True)
    def dev_set_menu(self) -> None:
        self.init_menu(collapse_menu=False, name="Develop")

        put_button(
            label=t("Gui.MenuDevelop.HomePage"),
            onclick=self.show,
            color="menu",
        ).style(f"--menu-HomePage--")

        # put_button(
        #     label=t("Gui.MenuDevelop.Translate"),
        #     onclick=self.dev_translate,
        #     color="menu",
        # ).style(f"--menu-Translate--")

        put_button(
            label=t("Gui.MenuDevelop.Update"),
            onclick=self.dev_update,
            color="menu",
        ).style(f"--menu-Update--")

        put_button(
            label=t("Gui.MenuDevelop.Remote"),
            onclick=self.dev_remote,
            color="menu",
        ).style(f"--menu-Remote--")

        put_button(
            label=t("Gui.MenuDevelop.Utils"),
            onclick=self.dev_utils,
            color="menu",
        ).style(f"--menu-Utils--")

    def dev_translate(self) -> None:
        go_app("translate", new_window=True)
        lang.TRANSLATE_MODE = True
        self.show()

    @use_scope("content", clear=True)
    def dev_update(self) -> None:
        self.init_menu(name="Update")
        self.set_title(t("Gui.MenuDevelop.Update"))

        if State.restart_event is None:
            put_warning(t("Gui.Update.DisabledWarn"))

        put_row(
            content=[put_scope("updater_loading"), None, put_scope("updater_state")],
            size="auto .25rem 1fr",
        )

        put_scope("updater_btn")
        put_scope("updater_info")

        def update_table():
            if not updater.updater_available(log=False):
                return
            with use_scope("updater_info", clear=True):
                local_commit = updater.get_commit(short_sha1=True)
                upstream_commit = updater.get_commit(
                    f"origin/{updater.Branch}", short_sha1=True
                )
                put_table(
                    [
                        [t("Gui.Update.Local"), *local_commit],
                        [t("Gui.Update.Upstream"), *upstream_commit],
                    ],
                    header=[
                        "",
                        "SHA1",
                        t("Gui.Update.Author"),
                        t("Gui.Update.Time"),
                        t("Gui.Update.Message"),
                    ],
                )
            with use_scope("updater_detail", clear=True):
                put_text(t("Gui.Update.DetailedHistory"))
                history = updater.get_commit(
                    f"origin/{updater.Branch}", n=20, short_sha1=True
                )
                put_table(
                    [commit for commit in history],
                    header=[
                        "SHA1",
                        t("Gui.Update.Author"),
                        t("Gui.Update.Time"),
                        t("Gui.Update.Message"),
                    ],
                )

        def u(state):
            if state == -1:
                return
            clear("updater_loading")
            clear("updater_state")
            clear("updater_btn")
            if state == 0:
                put_loading("border", "secondary", "updater_loading").style(
                    "--loading-border-fill--"
                )
                put_text(t("Gui.Update.UpToDate"), scope="updater_state")
                put_button(
                    t("Gui.Button.CheckUpdate"),
                    onclick=updater.check_update,
                    color="info",
                    scope="updater_btn",
                )
                update_table()
            elif state == 1:
                put_loading("grow", "success", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.HaveUpdate"), scope="updater_state")
                put_button(
                    t("Gui.Button.ClickToUpdate"),
                    onclick=updater.run_update,
                    color="success",
                    scope="updater_btn",
                )
                update_table()
            elif state == "checking":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateChecking"), scope="updater_state")
            elif state == "failed":
                put_loading("grow", "danger", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.UpdateFailed"), scope="updater_state")
                put_button(
                    t("Gui.Button.RetryUpdate"),
                    onclick=updater.run_update,
                    color="primary",
                    scope="updater_btn",
                )
            elif state == "start":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateStart"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                )
            elif state == "wait":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateWait"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                )
            elif state == "run update":
                put_loading("border", "primary", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateRun"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                    disabled=True,
                )
            elif state == "reload":
                put_loading("grow", "success", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.UpdateSuccess"), scope="updater_state")
                update_table()
            elif state == "finish":
                put_loading("grow", "success", "updater_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Update.UpdateFinish"), scope="updater_state")
                update_table()
            elif state == "cancel":
                put_loading("border", "danger", "updater_loading").style(
                    "--loading-border--"
                )
                put_text(t("Gui.Update.UpdateCancel"), scope="updater_state")
                put_button(
                    t("Gui.Button.CancelUpdate"),
                    onclick=updater.cancel,
                    color="danger",
                    scope="updater_btn",
                    disabled=True,
                )
            elif state == "unavailable":
                put_text(t("Gui.Update.NoGitRepo"), scope="updater_state")
            else:
                put_text(
                    "Something went wrong, please contact develops",
                    scope="updater_state",
                )
                put_text(f"state: {state}", scope="updater_state")

        updater_switch = Switch(
            status=u, get_state=lambda: updater.state, name="updater"
        )

        update_table()
        self.task_handler.add(updater_switch.g(), delay=0.5, pending_delete=True)

        updater.check_update()

    @use_scope("content", clear=True)
    def dev_utils(self) -> None:
        self.init_menu(name="Utils")
        self.set_title(t("Gui.MenuDevelop.Utils"))
        put_button(label="Raise exception", onclick=raise_exception)

        def _force_restart():
            if State.restart_event is not None:
                toast("Alas will restart in 3 seconds", duration=0, color="error")
                clearup()
                State.restart_event.set()
            else:
                toast("Reload not enabled", color="error")

        put_button(label="Force restart", onclick=_force_restart)

    @use_scope("content", clear=True)
    def dev_remote(self) -> None:
        self.init_menu(name="Remote")
        self.set_title(t("Gui.MenuDevelop.Remote"))
        put_row(
            content=[put_scope("remote_loading"), None, put_scope("remote_state")],
            size="auto .25rem 1fr",
        )
        put_scope("remote_info")

        def u(state):
            if state == -1:
                return
            clear("remote_loading")
            clear("remote_state")
            clear("remote_info")
            if state in (1, 2):
                put_loading("grow", "success", "remote_loading").style(
                    "--loading-grow--"
                )
                put_text(t("Gui.Remote.Running"), scope="remote_state")
                put_text(t("Gui.Remote.EntryPoint"), scope="remote_info")
                entrypoint = RemoteAccess.get_entry_point()
                if entrypoint:
                    if State.electron:  # Prevent click into url in electron client
                        put_text(entrypoint, scope="remote_info").style(
                            "text-decoration-line: underline"
                        )
                    else:
                        put_link(name=entrypoint, url=entrypoint, scope="remote_info")
                else:
                    put_text("Loading...", scope="remote_info")
            elif state in (0, 3):
                put_loading("border", "secondary", "remote_loading").style(
                    "--loading-border-fill--"
                )
                if (
                        State.deploy_config.EnableRemoteAccess
                        and State.deploy_config.Password
                ):
                    put_text(t("Gui.Remote.NotRunning"), scope="remote_state")
                else:
                    put_text(t("Gui.Remote.NotEnable"), scope="remote_state")
                put_text(t("Gui.Remote.ConfigureHint"), scope="remote_info")
                url = "http://app.azurlane.cloud" + (
                    "" if State.deploy_config.Language.startswith("zh") else "/en.html"
                )
                put_html(
                    f'<a href="{url}" target="_blank">{url}</a>', scope="remote_info"
                )
                if state == 3:
                    put_warning(
                        t("Gui.Remote.SSHNotInstall"),
                        closable=False,
                        scope="remote_info",
                    )

        remote_switch = Switch(
            status=u, get_state=RemoteAccess.get_state, name="remote"
        )

        self.task_handler.add(remote_switch.g(), delay=1, pending_delete=True)

    def ui_develop(self) -> None:
        if not self.is_mobile:
            self.show()
            return
        self.init_aside(name="Home")
        self.set_title(t("Gui.Aside.Home"))
        self.dev_set_menu()
        self.alas_name = ""
        if hasattr(self, "alas"):
            del self.alas
        self.state_switch.switch()

    def ui_alas(self, config_name: str) -> None:
        if config_name == self.alas_name:
            self.expand_menu()
            return
        self.init_aside(name=config_name)
        clear("content")
        self.alas_name = config_name
        self.alas_mod = get_config_mod(config_name)
        self.alas = ProcessManager.get_manager(config_name)
        self.alas_config = load_config(config_name)
        self.state_switch.switch()
        self.initial()
        self.alas_set_menu()

    def ui_add_alas(self) -> None:
        with popup(t("Gui.AddAlas.PopupTitle")) as s:

            def get_unused_name():
                all_name = alas_instance()
                for i in range(2, 100):
                    if f"alas{i}" not in all_name:
                        return f"alas{i}"
                else:
                    return ""

            def add():
                name = pin["AddAlas_name"]
                origin = pin["AddAlas_copyfrom"]

                if name in alas_instance():
                    err = "Gui.AddAlas.FileExist"
                elif set(name) & set(".\\/:*?\"'<>|"):
                    err = "Gui.AddAlas.InvalidChar"
                elif name.lower().startswith("template"):
                    err = "Gui.AddAlas.InvalidPrefixTemplate"
                else:
                    err = ""
                if err:
                    clear(s)
                    put(name, origin)
                    put_error(t(err), scope=s)
                    return

                r = load_config(origin).read_file(origin)
                State.config_updater.write_file(name, r, get_config_mod(origin))
                self.set_aside()
                self.active_button("aside", self.alas_name)
                close_popup()

            def put(name=None, origin=None):
                put_input(
                    name="AddAlas_name",
                    label=t("Gui.AddAlas.NewName"),
                    value=name or get_unused_name(),
                    scope=s,
                )
                put_select(
                    name="AddAlas_copyfrom",
                    label=t("Gui.AddAlas.CopyFrom"),
                    options=alas_template() + alas_instance(),
                    value=origin or "template-alas",
                    scope=s,
                )
                put_buttons(
                    buttons=[
                        {"label": t("Gui.AddAlas.Confirm"), "value": "confirm"},
                        {"label": t("Gui.AddAlas.Manage"), "value": "manage"},
                    ],
                    onclick=[
                        add,
                        lambda: go_app("manage", new_window=False),
                    ],
                    scope=s,
                )

            put()

    def show(self) -> None:
        self._show()
        self.load_home = True
        # Create state_switch before rendering aside buttons, so that
        # ui_alas() (invoked by clicking aside buttons, possibly before
        # the rest of show() finishes on slow machines) never touches an
        # uninitialized member. Reuse existing instance on repeated
        # show() calls (language/theme change, ui_develop) to keep the
        # original single-instance semantics and avoid resetting its
        # internal state generator.
        if not hasattr(self, "state_switch"):
            self.state_switch = Switch(
                status=self.set_status,
                get_state=lambda: getattr(getattr(self, "alas", -1), "state", 0),
                name="state",
            )
        self.set_aside()
        self.init_aside(name="Home")
        self.dev_set_menu()
        self.init_menu(name="HomePage")
        self.alas_name = ""
        if hasattr(self, "alas"):
            del self.alas
        self.set_status(0)

        def set_language(l):
            lang.set_language(l)
            self.show()

        def set_theme(t):
            self.set_theme(t)
            run_js("location.reload()")

        with use_scope("content"):
            put_text("Select your language / 选择语言").style("text-align: center")
            put_buttons(
                [
                    {"label": "简体中文", "value": "zh-CN"},
                    {"label": "繁體中文", "value": "zh-TW"},
                    {"label": "English", "value": "en-US"},
                    {"label": "日本語", "value": "ja-JP"},
                ],
                onclick=lambda l: set_language(l),
            ).style("text-align: center")
            put_text("Change theme / 更改主题").style("text-align: center")
            put_buttons(
                [
                    {"label": "Light", "value": "default", "color": "light"},
                    {"label": "Dark", "value": "dark", "color": "dark"},
                ],
                onclick=lambda t: set_theme(t),
            ).style("text-align: center")

            # show something
            put_markdown(
                """
            AlGS is a free, open-source multi-game task scheduler built on the AzurLaneAutoScript (Alas) framework. If you paid for it from any channel, please refund.
            AlGS 是一款免费开源的多游戏任务调度脚本，基于 AzurLaneAutoScript (Alas) 框架改造。如果你在任何渠道付费购买了本软件，请退款。
            Project repository 项目地址：`https://github.com/noelfwfaw/ALGS`
            Framework upstream 框架上游：`https://github.com/LmeSzinc/AzurLaneAutoScript`
            """
            ).style("text-align: center")

        if lang.TRANSLATE_MODE:
            lang.reload()

            def _disable():
                lang.TRANSLATE_MODE = False
                self.show()

            toast(
                _t("Gui.Toast.DisableTranslateMode"),
                duration=0,
                position="right",
                onclick=_disable,
            )

    def run(self) -> None:
        # setup gui
        set_env(title="Alas", output_animation=False)
        add_css(filepath_css("alas"))
        if self.is_mobile:
            add_css(filepath_css("alas-mobile"))
        else:
            add_css(filepath_css("alas-pc"))

        if self.theme == "dark":
            add_css(filepath_css("dark-alas"))
        else:
            add_css(filepath_css("light-alas"))

        # Auto refresh when lost connection
        # [For develop] Disable by run `reload=0` in console
        run_js(
            """
        reload = 1;
        WebIO._state.CurrentSession.on_session_close(
            ()=>{
                setTimeout(
                    ()=>{
                        if (reload == 1){
                            location.reload();
                        }
                    }, 4000
                )
            }
        );
        """
        )

        aside = get_localstorage("aside")
        self.show()

        # init config watcher
        self._init_alas_config_watcher()

        # save config
        _thread_save_config = threading.Thread(target=self._alas_thread_update_config)
        register_thread(_thread_save_config)
        _thread_save_config.start()

        visibility_state_switch = Switch(
            status={
                True: [
                    lambda: self.__setattr__("visible", True),
                    lambda: self.alas_update_overview_task()
                    if self.page == "Overview"
                    else 0,
                    lambda: self.task_handler._task.__setattr__("delay", 15),
                ],
                False: [
                    lambda: self.__setattr__("visible", False),
                    lambda: self.task_handler._task.__setattr__("delay", 1),
                ],
            },
            get_state=get_window_visibility_state,
            name="visibility_state",
        )

        def goto_update():
            self.ui_develop()
            self.dev_update()

        update_switch = Switch(
            status={
                1: lambda: toast(
                    t("Gui.Toast.ClickToUpdate"),
                    duration=0,
                    position="right",
                    color="success",
                    onclick=goto_update,
                )
            },
            get_state=lambda: updater.state,
            name="update_state",
        )

        self.task_handler.add(self.state_switch.g(), 2)
        self.task_handler.add(self.set_aside_status, 2)
        self.task_handler.add(visibility_state_switch.g(), 15)
        self.task_handler.add(update_switch.g(), 1)
        self.task_handler.start()

        # Return to previous page
        if aside not in ["Home", None]:
            self.ui_alas(aside)


def app_manage():
    def _import():
        resp = file_upload(
            label=t("Gui.AppManage.Import"),
            placeholder=t("Gui.Text.ChooseFile"),
            help_text=t("Gui.AppManage.OverrideWarning"),
            accept=".json",
            required=False,
            max_size="1M",
        )

        if resp is None:
            return

        file: bytes = resp["content"]
        file_name: str = resp["filename"]

        if IS_ON_PHONE_CLOUD:
            config_name = mod_name = "alas"
        elif len(file_name.split(".")) == 2:
            config_name, _ = file_name.split(".")
            mod_name = "alas"
        else:
            config_name, mod_name, _ = file_name.rsplit(".", maxsplit=2)

        config = json.loads(file.decode(encoding="utf-8"))
        State.config_updater.write_file(config_name, config, mod_name)
        toast(t("Gui.AppManage.ImportSuccess"), color="success")

        _show_table()

    def _export(config_name: str):
        mod_name = get_config_mod(config_name)
        if mod_name == "alas":
            filename = f"{config_name}.json"
        else:
            filename = f"{config_name}.{mod_name}.json"
        with open(filepath_config(config_name, mod_name), "rb") as f:
            download(filename, f.read())

    def _new():
        def get_unused_name():
            all_name = alas_instance()
            for i in range(2, 100):
                if f"alas{i}" not in all_name:
                    return f"alas{i}"
            else:
                return ""

        def validate(s: str):
            if s in alas_instance():
                return t("Gui.AppManage.NameExist")
            if set(s) & set(".\\/:*?\"'<>|"):
                return t("Gui.AppManage.InvalidChar")
            if s.lower().startswith("template"):
                return t("Gui.AppManage.InvalidPrefixTemplate")
            return None

        resp = input_group(
            label=t("Gui.AppManage.TitleNew"),
            inputs=[
                input(
                    label=t("Gui.AppManage.NewName"),
                    name="config_name",
                    value=get_unused_name(),
                    validate=validate,
                ),
                select(
                    label=t("Gui.AppManage.CopyFrom"),
                    name="copy_from",
                    options=alas_template() + alas_instance(),
                    value="template-alas",
                ),
            ],
            cancelable=True,
        )

        if resp is None:
            return

        config_name = resp["config_name"]
        origin = resp["copy_from"]

        r = load_config(origin).read_file(origin)
        State.config_updater.write_file(config_name, r, get_config_mod(origin))
        toast(t("Gui.AppManage.NewSuccess"), color="success")
        _show_table()

    def _show_table():
        clear("config_table")
        put_table(
            tdata=[
                (
                    name,
                    get_config_mod(name),
                    put_buttons(
                        buttons=[
                            {"label": t("Gui.AppManage.Export"), "value": name},
                            # {
                            #     "label": t("Gui.AppManage.Delete"),
                            #     "value": name,
                            #     "disabled": True,
                            #     "color": "danger",
                            # },
                        ],
                        onclick=[
                            partial(_export, name),
                            # partial(_delete, name),
                        ],
                        group=True,
                        small=True,
                    ),
                )
                for name in alas_instance()
            ],
            header=[
                t("Gui.AppManage.Name"),
                t("Gui.AppManage.Mod"),
                t("Gui.AppManage.Actions"),
            ],
            scope="config_table",
        )

    set_env(title="Alas", output_animation=False)
    run_js("$('head').append('<style>.footer{display:none}</style>')")

    put_html(f"<h2>{t('Gui.AppManage.PageTitle')}</h2>")
    put_scope("config_table")
    put_buttons(
        buttons=[
            {
                "label": t("Gui.AppManage.New"),
                "value": "new",
                "disabled": IS_ON_PHONE_CLOUD,
            },
            {"label": t("Gui.AppManage.Import"), "value": "import"},
            {"label": t("Gui.AppManage.Back"), "value": "back"},
        ],
        onclick=[
            (lambda: None) if IS_ON_PHONE_CLOUD else _new,
            _import,
            partial(go_app, "index", new_window=False),
        ],
    )
    _show_table()


def debug():
    """For interactive python.
    $ python3
    >>> from module.webui.app import *
    >>> debug()
    >>>
    """
    startup()
    AlasGUI().run()


def startup():
    State.init()
    lang.reload()
    updater.event = State.manager.Event()
    if updater.delay > 0:
        task_handler.add(updater.check_update, updater.delay)
    task_handler.add(updater.schedule_update(), 86400)
    task_handler.start()
    if State.deploy_config.DiscordRichPresence:
        init_discord_rpc()
    if State.deploy_config.StartOcrServer:
        start_ocr_server_process(State.deploy_config.OcrServerPort)
    if (
            State.deploy_config.EnableRemoteAccess
            and State.deploy_config.Password is not None
    ):
        task_handler.add(RemoteAccess.keep_ssh_alive(), 60)


def clearup():
    """
    Notice: Ensure run it before uvicorn reload app,
    all process will NOT EXIT after close electron app.
    """
    logger.info("Start clearup")
    RemoteAccess.kill_ssh_process()
    close_discord_rpc()
    stop_ocr_server_process()
    for alas in ProcessManager._processes.values():
        alas.stop()
    State.clearup()
    task_handler.stop()
    logger.info("Alas closed.")


def app():
    parser = argparse.ArgumentParser(description="Alas web service")
    parser.add_argument(
        "-k", "--key", type=str, help="Password of alas. No password by default"
    )
    parser.add_argument(
        "--cdn",
        action="store_true",
        help="Use jsdelivr cdn for pywebio static files (css, js). Self host cdn by default.",
    )
    parser.add_argument(
        "--run",
        nargs="+",
        type=str,
        help="Run alas by config names on startup",
    )
    args, _ = parser.parse_known_args()

    # Apply config
    AlasGUI.set_theme(theme=State.deploy_config.Theme)
    lang.LANG = State.deploy_config.Language
    key = args.key or State.deploy_config.Password
    cdn = args.cdn if args.cdn else State.deploy_config.CDN
    runs = None
    if args.run:
        runs = args.run
    elif State.deploy_config.Run:
        # TODO: refactor poor_yaml_read() to support list
        tmp = State.deploy_config.Run.split(",")
        runs = [l.strip(" ['\"]") for l in tmp if len(l)]
    instances: List[str] = runs

    logger.hr("Webui configs")
    logger.attr("Theme", State.deploy_config.Theme)
    logger.attr("Language", lang.LANG)
    logger.attr("Password", True if key else False)
    logger.attr("CDN", cdn)
    logger.attr("IS_ON_PHONE_CLOUD", IS_ON_PHONE_CLOUD)

    from deploy.atomic import atomic_failure_cleanup
    atomic_failure_cleanup('./config')

    def index():
        if key is not None and not login(key):
            logger.warning(f"{info.user_ip} login failed.")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        gui = AlasGUI()
        local.gui = gui
        gui.run()

    def manage():
        if key is not None and not login(key):
            logger.warning(f"{info.user_ip} login failed.")
            time.sleep(1.5)
            run_js("location.reload();")
            return
        app_manage()

    app = asgi_app(
        applications=[index, manage],
        cdn=cdn,
        static_dir=None,
        debug=True,
        on_startup=[
            startup,
            lambda: ProcessManager.restart_processes(
                instances=instances, ev=updater.event
            ),
        ],
        on_shutdown=[clearup],
    )
    # Expose only bundled selector assets, never the workspace or user configuration.
    for filename in ("index.html", "events.js"):
        app.add_route(
            f"{ROGUE_SELECTOR_ROUTE}/{filename}",
            lambda request, filename=filename: FileResponse(str(ROGUE_SELECTOR_DIR / filename)),
            include_in_schema=False,
        )

    return app
