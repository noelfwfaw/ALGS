import os
import threading
from typing import Dict

from module.config.deep import deep_iter
from module.config.utils import LANGUAGES, filepath_i18n, read_file
from module.submodule.utils import list_mod_dir
from module.webui.setting import State

LANG = "zh-CN"
TRANSLATE_MODE = False


def set_language(s: str, refresh=False):
    global LANG
    for i, lang in enumerate(LANGUAGES):
        # pywebio.session.info.user_language return `zh-CN` or `zh-cn`, depends on browser
        if lang.lower() == s.lower():
            LANG = LANGUAGES[i]
            break
    else:
        LANG = "en-US"

    State.deploy_config.Language = LANG

    if refresh:
        from pywebio.session import run_js

        run_js("location.reload();")


def t(s, *args, **kwargs):
    """
    Get translation.
    other args, kwargs pass to .format()
    """
    if TRANSLATE_MODE:
        return s
    return _t(s, LANG).format(*args, **kwargs)


def _i18n_files(lang):
    """
    Translation files of one language, in load order (later overrides earlier).

    Args:
        lang (str): Such as `zh-CN`.

    Returns:
        list[str]: Paths, mod files first and the main `i18n/<lang>.json` last.
    """
    files = [filepath_i18n(lang, mod_name) for mod_name, _ in list_mod_dir()]
    files.append(filepath_i18n(lang))
    return files


def _mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _load(lang):
    """
    Read one language into a flat `Menu.Promilia.name` -> text dict.

    Args:
        lang (str): Such as `zh-CN`.

    Returns:
        Dict[str, str]:
    """
    data = {}
    for path in _i18n_files(lang):
        for keys, value in deep_iter(read_file(path), depth=3):
            data[".".join(keys)] = value
    return data


def _t(s, lang=None):
    """
    Get translation, ignore TRANSLATE_MODE
    """
    if not lang:
        lang = LANG
    value = dic_lang.get(lang, {}).get(s)
    # The config generator can leave the key itself as a temporary translation.
    if (value is None or value == s) and _reload_if_stale(lang):
        value = dic_lang.get(lang, {}).get(s)
    if value is None:
        print(f"Language key ({s}) not found")
        return s
    return value


dic_lang: Dict[str, Dict[str, str]] = {}
_loaded_at: Dict[str, float] = {}
_reload_lock = threading.Lock()


def reload():
    """
    Load every language from `module/config/i18n/<lang>.json`.

    `startup()` calls this once per process. `_t()` also calls it when a key is
    missing or still a placeholder and the file on disk was rewritten.
    """
    global dic_lang
    with _reload_lock:
        loaded = {}
        for lang in LANGUAGES:
            loaded[lang] = _load(lang)

        for key in loaded["ja-JP"]:
            if loaded["ja-JP"][key] == key:
                loaded["ja-JP"][key] = loaded["en-US"][key]

        # Rebind instead of clearing in place: a thread reading `dic_lang` sees
        # either the old or the new table, never a half-filled one.
        dic_lang = loaded
        for lang in LANGUAGES:
            _loaded_at[lang] = max(_mtime(path) for path in _i18n_files(lang))


def _reload_if_stale(lang):
    """
    Reload translations if the files of `lang` changed since the last load.

    Args:
        lang (str): Such as `zh-CN`.

    Returns:
        bool: True if reloaded.
    """
    loaded_at = _loaded_at.get(lang)
    if loaded_at is None:
        return False
    if all(_mtime(path) <= loaded_at for path in _i18n_files(lang)):
        return False
    reload()
    return True
