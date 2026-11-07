# -*- coding: utf-8 -*-
"""把星之救援者（工具 `Starsavior2`）的文案写进四种 i18n。

`module/config/i18n/*.json` 是 `config_updater` 生成的产物，但生成时只**补缺**，
已有的值不会被覆盖 —— 所以先跑这个脚本写死文案，再跑

    python -m module.config.config_updater

补齐剩下的键（比如 `Storage.*`、`Target.<46 只角色>`，后者的默认值就是角色名本身）。

    python dev_tools/fill_i18n_starsavior.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from module.config.deep import deep_set  # noqa: E402
from module.config.utils import read_file, write_file  # noqa: E402

I18N = os.path.join('module', 'config', 'i18n')

TEXT = {
    'zh-CN': {
        'Menu.Starsavior.name': '星之救援者',
        'Menu.Starsavior.help': '刷初始工具，在「工具」页单独启动，不跟随任务调度',

        'Task.Starsavior2.name': '刷初始',
        'Task.Starsavior2.help':
            '⚠ 这个功能还在测试阶段，随时可能改行为，也可能出 bug。\n'
            '已实测环境：MuMu 模拟器 12、游戏亚服、游戏内简体中文、画质极低。'
            '其他模拟器 / 分辨率 / 语言 / 画质都没测过，可能点错或者卡住。\n'
            '游戏自身的卡顿、点击没反应（比如旅程结算后卡十几秒）脚本不会去处理，等它自己好。',

        'Starsavior2._info.name': '刷初始设置',
        'Starsavior2._info.help':
            '先在「设置 → 模拟器」把包名、分辨率配好，再回这一页点「启动」。三种模式只能生效一种：\n'
            '① 挂了「目标角色」（最多 7 只）= 一轮轮刷到出为止；这七只里任意一只出了就停在号上不重置，一只都没出就自动重置接着刷。\n'
            '② 选了「停节点」= 跑到那个节点就停下。\n'
            '③ 两个都留空 = 只跑一轮，验号完停下，不重置。',

        'Starsavior2.Nickname.name': '自定义昵称',
        'Starsavior2.Nickname.help':
            '留空就每轮随机「Savior + 4 位数字」。只收英文和数字（游戏输入框打不了中文），'
            '4~16 个字符；其他字符会被过滤掉，过滤完不够 4 位就退回随机名。',

        'Starsavior2.Target.name': '目标角色',
        'Starsavior2.Target.help':
            '最多挂 7 只（这一栏是第 1 只，下面还有「目标角色 2」~「目标角色 7」）。'
            '刷到其中任意一只就停下，把号留在游戏里不重置；一只都没出就重置账号接着刷。'
            '七个位全留「不指定」= 只跑一轮。⚠ 和「停节点」只能填一个，两个都填按这里跑。',
        'Starsavior2.Target.none': '不指定（只跑一轮，验号完停）',

        'Starsavior2.TargetCount.name': '目标数量',
        'Starsavior2.TargetCount.help':
            '每个挂上的目标各自都要这么多只。1 = 本体（0 星），4 = 满星。没挂目标时不生效。',

        'Starsavior2.StopAt.name': '停节点',
        'Starsavior2.StopAt.help':
            '分段跑 / 调试用，跑到这个节点就停下，不重置账号。⚠ 和「目标角色」只能填一个。',
        'Starsavior2.StopAt.none': '不设置（一直跑到验号完）',
        'Starsavior2.StopAt.nickname': '节点1：昵称输入前停下',
        'Starsavior2.StopAt.guide': '节点2：引导走完停下（没领奖、没抽卡）',
        'Starsavior2.StopAt.verify': '节点3：一直跑到验号',
    },
    'zh-TW': {
        'Menu.Starsavior.name': '星之救援者',
        'Menu.Starsavior.help': '刷初始工具，在「工具」頁單獨啟動，不跟隨任務調度',

        'Task.Starsavior2.name': '刷初始',
        'Task.Starsavior2.help':
            '⚠ 這個功能還在測試階段，隨時可能改行為，也可能有 bug。\n'
            '已實測環境：MuMu 模擬器 12、遊戲亞服、遊戲內簡體中文、畫質極低。'
            '其他模擬器 / 解析度 / 語言 / 畫質都沒測過，可能點錯或卡住。\n'
            '遊戲本身的卡頓、點擊沒反應（例如旅程結算後卡十幾秒）腳本不會處理，等它自己好。',

        'Starsavior2._info.name': '刷初始設定',
        'Starsavior2._info.help':
            '先在「設定 → 模擬器」把包名、解析度設好，再回這一頁點「啟動」。三種模式只會生效一種：\n'
            '① 掛了「目標角色」（最多 7 隻）= 一輪輪刷到出為止；這七隻裡任意一隻出了就停在號上不重置，一隻都沒出就自動重置繼續刷。\n'
            '② 選了「停節點」= 跑到那個節點就停下。\n'
            '③ 兩個都留空 = 只跑一輪，驗號完停下，不重置。',

        'Starsavior2.Nickname.name': '自訂暱稱',
        'Starsavior2.Nickname.help':
            '留空就每輪隨機「Savior + 4 位數字」。只收英文和數字（遊戲輸入框打不了中文），'
            '4~16 個字元；其他字元會被過濾掉，過濾完不足 4 位就退回隨機名稱。',

        'Starsavior2.Target.name': '目標角色',
        'Starsavior2.Target.help':
            '最多掛 7 隻（這一欄是第 1 隻，下面還有「目標角色 2」~「目標角色 7」）。'
            '刷到其中任意一隻就停下，把號留在遊戲裡不重置；一隻都沒出就重置帳號繼續刷。'
            '七個位全留「不指定」= 只跑一輪。⚠ 和「停節點」只能填一個，兩個都填以這裡為準。',
        'Starsavior2.Target.none': '不指定（只跑一輪，驗號完停）',

        'Starsavior2.TargetCount.name': '目標數量',
        'Starsavior2.TargetCount.help':
            '每個掛上的目標各自都要這麼多隻。1 = 本體（0 星），4 = 滿星。沒掛目標時不生效。',

        'Starsavior2.StopAt.name': '停節點',
        'Starsavior2.StopAt.help':
            '分段跑 / 除錯用，跑到這個節點就停下，不重置帳號。⚠ 和「目標角色」只能填一個。',
        'Starsavior2.StopAt.none': '不設定（一直跑到驗號完）',
        'Starsavior2.StopAt.nickname': '節點1：暱稱輸入前停下',
        'Starsavior2.StopAt.guide': '節點2：引導走完停下（沒領獎、沒抽卡）',
        'Starsavior2.StopAt.verify': '節點3：一直跑到驗號',
    },
    'en-US': {
        'Menu.Starsavior.name': 'Star Savior',
        'Menu.Starsavior.help': 'Reroll tool. Start it from the Tools page; it never joins the task queue',

        'Task.Starsavior2.name': 'Reroll',
        'Task.Starsavior2.help':
            'Warning: this tool is still in testing. Behaviour may change, and it may contain bugs.\n'
            'Tested on: MuMu emulator 12, Asia server, in-game Simplified Chinese, lowest graphics. '
            'Other emulators / resolutions / languages / graphics settings are untested.\n'
            'Stutters and dead clicks caused by the game itself (e.g. a ~15s freeze after the journey '
            'settlement) are not worked around; the script just waits them out.',

        'Starsavior2._info.name': 'Reroll settings',
        'Starsavior2._info.help':
            'Set the package name and resolution in "Settings -> Emulator" first, then press Start here. '
            'Only one of the three modes takes effect:\n'
            '1) Target character(s) set (up to 7): reroll round after round until ANY of them drops. '
            'On a hit the account is kept (no reset); on a miss the account is reset and the next round starts.\n'
            '2) Stop-at set: stop right after that checkpoint.\n'
            '3) Both empty: run exactly one round, stop after the roster check, no reset.',

        'Starsavior2.Nickname.name': 'Nickname',
        'Starsavior2.Nickname.help':
            'Leave empty for a random "Savior + 4 digits" name each round. ASCII letters and digits only '
            '(the game input box cannot take Chinese), 4-16 characters; other characters are stripped, '
            'and a result shorter than 4 falls back to a random name.',

        'Starsavior2.Target.name': 'Target character',
        'Starsavior2.Target.help':
            'Up to 7 targets can be set (this is #1; "Target 2" to "Target 7" follow). '
            'Stop as soon as ANY of them drops and keep the account; otherwise reset and keep rerolling. '
            'All seven set to "Not set" runs a single round only. '
            'Warning: mutually exclusive with "Stop at".',
        'Starsavior2.Target.none': 'Not set (one round, stop after the roster check)',

        'Starsavior2.TargetCount.name': 'Target count',
        'Starsavior2.TargetCount.help':
            'How many copies each target needs. 1 = base (0 star), 4 = max star. Ignored when no target is set.',

        'Starsavior2.StopAt.name': 'Stop at',
        'Starsavior2.StopAt.help':
            'For step-by-step runs and debugging: stop right after this checkpoint, without resetting. '
            'Warning: mutually exclusive with "Target character".',
        'Starsavior2.StopAt.none': 'Not set (run all the way to the roster check)',
        'Starsavior2.StopAt.nickname': 'Checkpoint 1: before entering the nickname',
        'Starsavior2.StopAt.guide': 'Checkpoint 2: guides finished (no reward, no gacha)',
        'Starsavior2.StopAt.verify': 'Checkpoint 3: all the way to the roster check',
    },
    'ja-JP': {
        'Menu.Starsavior.name': 'スターセイヴァー',
        'Menu.Starsavior.help': 'リセマラツール。「ツール」ページから個別に起動し、タスクスケジュールには従いません',

        'Task.Starsavior2.name': 'リセマラ',
        'Task.Starsavior2.help':
            '⚠ この機能はテスト中です。挙動が変わる可能性があり、不具合も残っています。\n'
            '検証済み環境：MuMu エミュレーター 12、アジアサーバー、ゲーム内簡体字中国語、画質は最低。'
            '他のエミュレーター / 解像度 / 言語 / 画質は未検証です。\n'
            'ゲーム側のカクつきやクリックが効かない現象（旅の清算後に十数秒止まる等）は処理しません。',

        'Starsavior2._info.name': 'リセマラ設定',
        'Starsavior2._info.help':
            '先に「設定 → エミュレーター」でパッケージ名と解像度を設定し、このページで「起動」を押してください。'
            '3 つのモードのうち有効なのは 1 つだけです：\n'
            '①「目標キャラ」を設定（最大 7 体）= 出るまで周回。どれか 1 体出たらアカウントを残して停止、1 体も出なければリセットして続行。\n'
            '②「停止ポイント」を設定 = そのポイントで停止。\n'
            '③ 両方空 = 1 周だけ実行し、検品後に停止（リセットなし）。',

        'Starsavior2.Nickname.name': 'ニックネーム',
        'Starsavior2.Nickname.help':
            '空欄なら毎回ランダムな「Savior + 4 桁の数字」。英数字のみ（ゲームの入力欄は中国語を受け付けません）、'
            '4〜16 文字。他の文字は除去され、4 文字未満ならランダム名になります。',

        'Starsavior2.Target.name': '目標キャラ',
        'Starsavior2.Target.help':
            '最大 7 体まで設定できます（ここは 1 体目、「目標キャラ 2」〜「目標キャラ 7」が続きます）。'
            'いずれか 1 体が出たら停止し、アカウントはリセットしません。出なければリセットして周回を続けます。'
            '7 つすべて「指定しない」なら 1 周だけ。⚠「停止ポイント」とは排他です。',
        'Starsavior2.Target.none': '指定しない（1 周だけ、検品後に停止）',

        'Starsavior2.TargetCount.name': '必要数',
        'Starsavior2.TargetCount.help':
            '設定した各目標それぞれに必要な数。1 = 本体（0 凸）、4 = 完凸。目標未設定時は無効です。',

        'Starsavior2.StopAt.name': '停止ポイント',
        'Starsavior2.StopAt.help':
            '分割実行 / デバッグ用。そのポイントで停止し、アカウントはリセットしません。'
            '⚠「目標キャラ」とは排他です。',
        'Starsavior2.StopAt.none': '設定しない（検品まで通しで実行）',
        'Starsavior2.StopAt.nickname': 'ポイント1：ニックネーム入力前に停止',
        'Starsavior2.StopAt.guide': 'ポイント2：チュートリアル終了後に停止（受け取り・ガチャ前）',
        'Starsavior2.StopAt.verify': 'ポイント3：検品まで通しで実行',
    },
}

# 目标角色 2~7：和 `Target` 是同一组字段，只有序号不同，所以按语种模板生成，
# 不手抄 6 遍。文案故意短——界面上六条一模一样的说明会把设置本身挤下去。
EXTRA_TARGET = {
    'zh-CN': ('目标角色 %d', '可选。最多挂 7 只，任意一只出了就停。', '不指定（这一位空着）'),
    'zh-TW': ('目標角色 %d', '可選。最多掛 7 隻，任一隻出了就停。', '不指定（這一格空著）'),
    'en-US': ('Target %d', 'Optional. Up to 7 targets; any one of them stops the reroll.',
              'Not set (leave this slot empty)'),
    'ja-JP': ('目標キャラ %d', '任意。最大 7 体、どれか 1 体出たら停止。', '指定しない（この枠は空き）'),
}


def main():
    for lang, mapping in TEXT.items():
        name, help_text, none_text = EXTRA_TARGET[lang]
        for index in range(2, 8):
            mapping['Starsavior2.Target%d.name' % index] = name % index
            mapping['Starsavior2.Target%d.help' % index] = help_text
            mapping['Starsavior2.Target%d.none' % index] = none_text
        path = os.path.join(I18N, '%s.json' % lang)
        data = read_file(path)
        for key, value in mapping.items():
            deep_set(data, key.split('.'), value)
        write_file(path, data)
        print('%s: %d keys' % (lang, len(mapping)))


if __name__ == '__main__':
    main()
