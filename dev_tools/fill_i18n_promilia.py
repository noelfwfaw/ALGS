"""Fill Promilia package, menu and task names in the generated i18n files.

Run after ``config_updater`` has created the package and task options, then run
``config_updater`` again to verify that the names survive regeneration.

Usage:
    ./toolkit/python.exe -m dev_tools.fill_i18n_promilia
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = 'com.manjuu.promilia.bilibili'
TEXT = {
    'zh-CN': '蓝色星原：旅谣（哔哩哔哩）',
    'zh-TW': '藍色星原：旅謠（嗶哩嗶哩）',
    'en-US': 'Azur Promilia (Bilibili)',
    'ja-JP': 'Azur Promilia (Bilibili)',
}
MENU = {
    'zh-CN': {
        'name': '蓝色星原：旅谣',
        'help': '蓝色星原：旅谣的每日活跃奖励领取',
    },
    'zh-TW': {
        'name': '藍色星原：旅謠',
        'help': '藍色星原：旅謠的每日活躍獎勵領取',
    },
    'en-US': {
        'name': 'Azur Promilia',
        'help': 'Claim daily activity rewards in Azur Promilia',
    },
    'ja-JP': {
        'name': 'アズールプロミリア',
        'help': 'アズールプロミリアのデイリー活躍報酬を受け取ります',
    },
}
TASK = {
    'zh-CN': {
        'name': '每日活跃奖励',
        'help': '进入日常活跃页面，领取已完成任务点数与一个可领取的里程碑奖励箱，然后返回主界面。',
    },
    'zh-TW': {
        'name': '每日活躍獎勵',
        'help': '進入日常活躍頁面，領取已完成任務點數與一個可領取的里程碑獎勵箱，然後返回主畫面。',
    },
    'en-US': {
        'name': 'Daily Activity Rewards',
        'help': 'Open the daily activity page, claim completed task points and one available milestone reward box, then return to the lobby.',
    },
    'ja-JP': {
        'name': 'デイリー活躍報酬',
        'help': 'デイリー活躍ページを開き、完了したタスクのポイントと受け取れるマイルストーン報酬箱を1つ受け取り、ロビーに戻ります。',
    },
}


def main():
    for language, text in TEXT.items():
        path = os.path.join(ROOT, 'module', 'config', 'i18n', language + '.json')
        with open(path, 'r', encoding='utf-8') as file:
            data = json.load(file)
        data.setdefault('Emulator', {}).setdefault('PackageName', {})[PACKAGE] = text
        data.setdefault('Menu', {})['Promilia'] = MENU[language]
        data.setdefault('Task', {})['PromiliaActivity'] = TASK[language]
        with open(path, 'w', encoding='utf-8', newline='\n') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        print('Updated {}'.format(path))


if __name__ == '__main__':
    main()
