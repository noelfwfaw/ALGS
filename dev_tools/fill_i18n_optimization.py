"""Fill the Optimization translations of module/config/i18n/*.json.

Edit the strings here, run this script, then run config_updater to regenerate
and verify that the translations survive.

Usage:
    ./toolkit/python.exe -m dev_tools.fill_i18n_optimization
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = {
    'zh-CN': {
        'help': '设置任务队列清空后的操作。选择「关闭模拟器」时，仅对可确认的 Windows 本地模拟器生效；'
                '队列空闲且距下一任务至少 180 秒时关闭，否则继续待机，下一任务到点自动启动。',
        'close_emulator': '关闭模拟器',
    },
    'zh-TW': {
        'help': '設定任務隊列清空後的操作。選擇「關閉模擬器」時，僅對可確認的 Windows 本機模擬器生效；'
                '隊列空閒且距離下一任務至少 180 秒時關閉，否則繼續待機，下一任務到點自動啟動。',
        'close_emulator': '關閉模擬器',
    },
    'en-US': {
        'help': 'Choose what to do when the task queue is empty. Close Emulator only applies to identifiable '
                'local Windows emulators: it shuts down when the queue is idle and the next task is at least '
                '180 seconds away, otherwise it keeps waiting. The next task starts the emulator automatically '
                'when due.',
        'close_emulator': 'Close Emulator',
    },
    'ja-JP': {
        'help': 'タスクキューが空になったときの動作を選択します。「エミュレータを終了」は、確認できる Windows '
                'ローカルエミュレータでのみ有効です。キューが空で、次のタスクまで180秒以上ある場合のみ終了し、'
                '未満の場合は待機します。次のタスクの時刻になると自動的に起動します。',
        'close_emulator': 'エミュレータを終了',
    },
}


def main():
    for lang, text in TEXT.items():
        path = os.path.join(ROOT, 'module', 'config', 'i18n', lang + '.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        data.setdefault('Optimization', {}).setdefault('WhenTaskQueueEmpty', {}).update(text)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
        print(f'{lang}: Optimization.WhenTaskQueueEmpty')


if __name__ == '__main__':
    main()
