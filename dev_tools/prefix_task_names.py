"""Prefix every task name in the GUI with its game's short name.

`config_updater` only generates the i18n skeleton, it does not add prefixes.
Task names like 「指挥室」/「邮箱」/「兑换码」 repeat across six games, so the
task list is hard to read. This script adds a short game prefix to every
`Task.<Name>.name` in all four languages.

Idempotent: a name that already starts with the language's prefix is left
alone (Crosscore's Chinese names already start with 「交错」). Framework tasks
(`Alas`, `Restart`) have no game and are skipped.

Usage:
    ./toolkit/python.exe -m dev_tools.prefix_task_names

Run this again after adding new tasks. `fill_i18n_starsavior.py` also carries
`Task.Starsavior2.name`, so keep its values prefixed too.
"""
from module.config.utils import filepath_i18n, read_file, write_file

# Short game names, kept in sync with the Menu.<Game>.name entries.
PREFIX = {
    'Hazeworld': {
        'zh-CN': '苍雾', 'zh-TW': '蒼霧',
        'en-US': 'Hazeworld', 'ja-JP': 'ヘイズ',
    },
    'Lostsword': {
        'zh-CN': '失落', 'zh-TW': '失落',
        'en-US': 'Lost Sword', 'ja-JP': 'ロスト',
    },
    'Browndust': {
        'zh-CN': '棕尘', 'zh-TW': '棕塵',
        'en-US': 'Brown Dust', 'ja-JP': 'ブラウン',
    },
    'Chaoszero': {
        'zh-CN': '卡厄思', 'zh-TW': '卡厄思',
        'en-US': 'Chaos Zero', 'ja-JP': 'カオス',
    },
    'Crosscore': {
        'zh-CN': '交错', 'zh-TW': '交錯',
        'en-US': 'Cross Core', 'ja-JP': 'クロス',
    },
    'Starsavior': {
        'zh-CN': '星之', 'zh-TW': '星之',
        'en-US': 'Star Savior', 'ja-JP': 'スター',
    },
}
# Chinese reads better without a separator; latin/kana need one.
SEPARATOR = {'zh-CN': '', 'zh-TW': '', 'en-US': ': ', 'ja-JP': '：'}
LANGS = ('zh-CN', 'zh-TW', 'en-US', 'ja-JP')


def game_of(task):
    for game in PREFIX:
        if task.startswith(game):
            return game
    return None


def main():
    for lang in LANGS:
        path = filepath_i18n(lang)
        data = read_file(path)
        changed = []
        for task, item in data.get('Task', {}).items():
            game = game_of(task)
            if game is None or not isinstance(item, dict):
                continue
            prefix = PREFIX[game][lang]
            name = item.get('name', '')
            if not name or name.startswith(prefix):
                continue
            item['name'] = prefix + SEPARATOR[lang] + name
            changed.append(task)
        write_file(path, data)
        print('%s: %d task names prefixed' % (lang, len(changed)))
        for task in changed:
            print('  %s -> %s' % (task, data['Task'][task]['name']))


if __name__ == '__main__':
    main()
