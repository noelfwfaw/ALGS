"""Fill the four-language strings of Trickcal menus and tasks.

The generated i18n files only carry keys declared in gui.yaml. Game task
names and their help texts are kept here as the single source, the same way
fill_i18n_hazeworld.py / fill_i18n_starsavior.py do for their games: edit
this file, run it, then run `module.config.config_updater` to confirm the
keys survive regeneration.

Usage:
    python -m dev_tools.fill_i18n_trickcal
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANGS = ('zh-CN', 'zh-TW', 'en-US', 'ja-JP')

MENU = {
    'zh-CN': {
        'name': '嘟嘟脸恶作剧',
        'help': '嘟嘟脸恶作剧的登录与签到',
    },
    'zh-TW': {
        'name': '嘟嘟臉惡作劇',
        'help': '嘟嘟臉惡作劇的登入與簽到',
    },
    'en-US': {
        'name': 'Trickcal',
        'help': 'Trickcal login and daily sign-in',
    },
    'ja-JP': {
        'name': 'Trickcal',
        'help': 'Trickcal のログインとデイリーサインイン',
    },
}

TASKS = {
    'TrickcalLogin': {
        'zh-CN': {
            'name': '嘟嘟登录',
            'help': '启动客户端并走完标题屏与登录，领取当天签到奖励、关闭获得奖励弹窗与公告，最后停在主界面。'
                    '正常不会经过回归活动；回归活动面板弹出时只把它关掉，不领取回归奖励。每天日更后跑一次。',
        },
        'zh-TW': {
            'name': '嘟嘟登入',
            'help': '啟動客戶端並走完標題畫面與登入，領取當日簽到獎勵、關閉獲得獎勵彈窗與公告，最後停在主畫面。'
                    '正常不會經過回歸活動；回歸活動面板彈出時只把它關掉，不領取回歸獎勵。每天日更後跑一次。',
        },
        'en-US': {
            'name': 'Trickcal Login',
            'help': 'Launch the client, walk through the title screen and login, claim the daily '
                    'sign-in reward, dismiss the reward and announcement popups, and stop at the '
                    'lobby. A return-event panel normally does not appear; if it does, it is only '
                    'closed and no return rewards are claimed. Runs once after the daily reset.',
        },
        'ja-JP': {
            'name': 'Trickcal ログイン',
            'help': 'クライアントを起動してタイトル画面からログインし、デイリーサインイン報酬を受け取り、'
                    '報酬・お知らせのポップアップを閉じてロビーで終了します。復帰イベントは通常表示されませんが、'
                    '表示された場合は閉じるだけで報酬は受け取りません。日次更新後に 1 回実行します。',
        },
    },
}


def main():
    """Write the strings into each language file, keeping the existing keys."""
    for lang in LANGS:
        path = os.path.join(ROOT, 'module', 'config', 'i18n', lang + '.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

        data['Menu']['Trickcal'] = MENU[lang]
        for task, texts in TASKS.items():
            data['Task'][task] = texts[lang]

        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print(f'{lang}: Menu.Trickcal + {len(TASKS)} task(s)')


if __name__ == '__main__':
    main()
