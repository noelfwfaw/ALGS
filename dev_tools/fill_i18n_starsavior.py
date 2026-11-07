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
            '① 挂了「目标角色」（最多 7 只）= 一轮轮刷到出为止。怎么算达标由「达标条件」决定：'
            '「任意一个角色」是名单里某一个角色凑够它自己的数量就停，「全都要」是选上的都凑够才停；达标就把号留在游戏里不重置，没达标就自动重置接着刷。\n'
            '② 选了「停节点」= 跑到那个节点就停下。\n'
            '③ 目标角色和停节点都留空 = 只跑一轮，验号完停下，不重置。',

        'Starsavior2.Nickname.name': '自定义昵称',
        'Starsavior2.Nickname.help':
            '留空就每轮随机「Savior + 4 位数字」。只收英文和数字（游戏输入框打不了中文），'
            '4~16 个字符；其他字符会被过滤掉，过滤完不够 4 位就退回随机名。',

        'Starsavior2.TargetMode.name': '达标条件',
        'Starsavior2.TargetMode.help':
            '挂上的目标怎么才算刷成功。\n'
            '· 任意一个角色：名单里只要某一个角色凑够它自己的数量就停，最省时间（默认）。\n'
            '· 全都要：选上的每一只都得凑够各自的数量，缺一只就重置重来。'
            '比如「4 只光奶 + 1 只别的」，两个同时满足才停。',
        'Starsavior2.TargetMode.any': '任意一个角色凑够就停',
        'Starsavior2.TargetMode.all': '选上的全都要凑够',

        'Starsavior2.Target.name': '目标角色',
        'Starsavior2.Target.help':
            '最多挂 7 只（这一栏是第 1 只，下面还有「目标角色 2」~「目标角色 7」）。'
            '怎么算达标看上面的「达标条件」，每一只各自有数量。'
            '七个位全留「不指定」= 只跑一轮。⚠ 和「停节点」只能填一个，两个都填按这里跑。',
        'Starsavior2.Target.none': '不指定（只跑一轮，验号完停）',

        'Starsavior2.TargetCount.name': '第 1 只的数量',
        'Starsavior2.TargetCount.help':
            '第 1 个目标要几只（1 = 本体 0 星，4 = 满星）。后面每个目标各有自己的数量。',

        'Starsavior2.StopAt.name': '停节点',
        'Starsavior2.StopAt.help':
            '分段跑 / 调试用，跑到这个节点就停下，不重置账号。\n'
            '不设置 = 不停下，正常刷：挂了「目标角色」就一轮轮重复刷到出为止，没挂就只跑一轮。\n'
            '⚠ 填了节点就按节点跑，「目标角色」会被忽略。',
        'Starsavior2.StopAt.none': '不设置（不停下，有目标就重复刷）',
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
            '① 掛了「目標角色」（最多 7 隻）= 一輪輪刷到出為止。怎樣算達標由「達標條件」決定：'
            '「任意一個角色」是名單裡某一個角色湊夠它自己的數量就停，「全都要」是選上的都湊夠才停；達標就把號留在遊戲裡不重置，沒達標就自動重置繼續刷。\n'
            '② 選了「停節點」= 跑到那個節點就停下。\n'
            '③ 目標角色和停節點都留空 = 只跑一輪，驗號完停下，不重置。',

        'Starsavior2.Nickname.name': '自訂暱稱',
        'Starsavior2.Nickname.help':
            '留空就每輪隨機「Savior + 4 位數字」。只收英文和數字（遊戲輸入框打不了中文），'
            '4~16 個字元；其他字元會被過濾掉，過濾完不足 4 位就退回隨機名稱。',

        'Starsavior2.TargetMode.name': '達標條件',
        'Starsavior2.TargetMode.help':
            '掛上的目標怎樣才算刷成功。\n'
            '· 任意一個角色：名單裡只要某一個角色湊夠它自己的數量就停，最省時間（預設）。\n'
            '· 全都要：選上的每一隻都得湊夠各自的數量，缺一隻就重置重來。'
            '例如「4 隻光奶 + 1 隻別的」，兩個同時滿足才停。',
        'Starsavior2.TargetMode.any': '任意一個角色湊夠就停',
        'Starsavior2.TargetMode.all': '選上的全都要湊夠',

        'Starsavior2.Target.name': '目標角色',
        'Starsavior2.Target.help':
            '最多掛 7 隻（這一欄是第 1 隻，下面還有「目標角色 2」~「目標角色 7」）。'
            '怎樣算達標看上面的「達標條件」，每一隻各自有數量。'
            '七個位全留「不指定」= 只跑一輪。⚠ 和「停節點」只能填一個，兩個都填以這裡為準。',
        'Starsavior2.Target.none': '不指定（只跑一輪，驗號完停）',

        'Starsavior2.TargetCount.name': '第 1 隻的數量',
        'Starsavior2.TargetCount.help':
            '第 1 個目標要幾隻（1 = 本體 0 星，4 = 滿星）。後面每個目標各有自己的數量。',

        'Starsavior2.StopAt.name': '停節點',
        'Starsavior2.StopAt.help':
            '分段跑 / 除錯用，跑到這個節點就停下，不重置帳號。\n'
            '不設定 = 不停下，正常刷：掛了「目標角色」就一輪輪重複刷到出為止，沒掛就只跑一輪。\n'
            '⚠ 填了節點就按節點跑，「目標角色」會被忽略。',
        'Starsavior2.StopAt.none': '不設定（不停下，有目標就重複刷）',
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
            '1) Target character(s) set (up to 7): reroll round after round. "Win condition" decides '
            'what counts: "any one character" stops once a single listed character reaches its own count, '
            '"all" needs every selected target. '
            'On a hit the account is kept (no reset); on a miss the account is reset and the next round starts.\n'
            '2) Stop-at set: stop right after that checkpoint.\n'
            '3) Target character and Stop-at both empty: run exactly one round, stop after the roster check, no reset.',

        'Starsavior2.Nickname.name': 'Nickname',
        'Starsavior2.Nickname.help':
            'Leave empty for a random "Savior + 4 digits" name each round. ASCII letters and digits only '
            '(the game input box cannot take Chinese), 4-16 characters; other characters are stripped, '
            'and a result shorter than 4 falls back to a random name.',

        'Starsavior2.TargetMode.name': 'Win condition',
        'Starsavior2.TargetMode.help':
            'How the targets are counted as a hit.\n'
            '- Any one character: a single listed character reaching its own count is a hit '
            '(default, fastest).\n'
            '- All: every selected target must reach its own count, otherwise reset and reroll. '
            'E.g. 4 copies of A plus 1 of B needs both.',
        'Starsavior2.TargetMode.any': 'Any one character reaches its count',
        'Starsavior2.TargetMode.all': 'All selected must drop',

        'Starsavior2.Target.name': 'Target character',
        'Starsavior2.Target.help':
            'Up to 7 targets can be set (this is #1; "Target 2" to "Target 7" follow). '
            'See "Win condition" above; each target has its own count. '
            'All seven set to "Not set" runs a single round only. '
            'Warning: mutually exclusive with "Stop at".',
        'Starsavior2.Target.none': 'Not set (one round, stop after the roster check)',

        'Starsavior2.TargetCount.name': 'Target 1 count',
        'Starsavior2.TargetCount.help':
            'How many copies target #1 needs (1 = base / 0 star, 4 = max star). '
            'Every target has its own count field.',

        'Starsavior2.StopAt.name': 'Stop at',
        'Starsavior2.StopAt.help':
            'For step-by-step runs and debugging: stop right after this checkpoint, without resetting.\n'
            'Not set = no checkpoint, normal rerolling: with a target character it keeps repeating '
            'until the target drops, without one it runs a single round.\n'
            'Warning: when a checkpoint is set, "Target character" is ignored.',
        'Starsavior2.StopAt.none': 'Not set (no checkpoint; repeat while a target is set)',
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
            '①「目標キャラ」を設定（最大 7 体）= 出るまで周回。達成条件は「達成条件」で決まり、'
            '「どれか 1 キャラ」はリスト内のどれか 1 キャラが自分の必要数に達すれば停止、'
            '「全部そろえる」は選んだすべてが揃うまで続行。'
            '達成ならアカウントを残して停止、未達成ならリセットして次周へ。\n'
            '②「停止ポイント」を設定 = そのポイントで停止。\n'
            '③「目標キャラ」も「停止ポイント」も空 = 1 周だけ実行し、検品後に停止（リセットなし）。',

        'Starsavior2.Nickname.name': 'ニックネーム',
        'Starsavior2.Nickname.help':
            '空欄なら毎回ランダムな「Savior + 4 桁の数字」。英数字のみ（ゲームの入力欄は中国語を受け付けません）、'
            '4〜16 文字。他の文字は除去され、4 文字未満ならランダム名になります。',

        'Starsavior2.TargetMode.name': '達成条件',
        'Starsavior2.TargetMode.help':
            '設定した目標をどう数えたら成功か。\n'
            '・どれか 1 キャラ：リスト内のどれか 1 キャラが自分の必要数に達すれば停止（既定・最短）。\n'
            '・全部そろえる：選んだすべてが各自の必要数に達するまで周回。'
            '例：「A を 4 体 + B を 1 体」なら両方そろって初めて停止。',
        'Starsavior2.TargetMode.any': 'どれか 1 キャラが必要数に達すれば停止',
        'Starsavior2.TargetMode.all': '選んだ全部をそろえる',

        'Starsavior2.Target.name': '目標キャラ',
        'Starsavior2.Target.help':
            '最大 7 体まで設定できます（ここは 1 体目、「目標キャラ 2」〜「目標キャラ 7」が続きます）。'
            '達成条件は上の「達成条件」、必要数はキャラごとに個別です。'
            '7 つすべて「指定しない」なら 1 周だけ。⚠「停止ポイント」とは排他です。',
        'Starsavior2.Target.none': '指定しない（1 周だけ、検品後に停止）',

        'Starsavior2.TargetCount.name': '1 体目の必要数',
        'Starsavior2.TargetCount.help':
            '1 体目の目標に必要な数（1 = 本体・0 凸、4 = 完凸）。以降の目標はそれぞれ専用の項目があります。',

        'Starsavior2.StopAt.name': '停止ポイント',
        'Starsavior2.StopAt.help':
            '分割実行 / デバッグ用。そのポイントで停止し、アカウントはリセットしません。\n'
            '設定しない = 途中で止めず通常実行：「目標キャラ」を設定していれば出るまで周回、'
            '未設定なら 1 周だけ。\n'
            '⚠ ポイントを設定すると「目標キャラ」は無視されます。',
        'Starsavior2.StopAt.none': '設定しない（止めずに通常実行、目標があれば周回）',
        'Starsavior2.StopAt.nickname': 'ポイント1：ニックネーム入力前に停止',
        'Starsavior2.StopAt.guide': 'ポイント2：チュートリアル終了後に停止（受け取り・ガチャ前）',
        'Starsavior2.StopAt.verify': 'ポイント3：検品まで通しで実行',
    },
}

# 目标角色 2~7 和它们各自的数量：和 `Target`/`TargetCount` 是同一组字段，
# 只有序号不同，所以按语种模板生成，不手抄 6 遍。文案故意短——界面上六条
# 一模一样的说明会把设置本身挤下去。
EXTRA_TARGET = {
    'zh-CN': ('目标角色 %d', '可选。最多挂 7 只，怎么算达标看上面的「达标条件」。', '不指定（这一位空着）'),
    'zh-TW': ('目標角色 %d', '可選。最多掛 7 隻，怎樣算達標看上面的「達標條件」。', '不指定（這一格空著）'),
    'en-US': ('Target %d', 'Optional. Up to 7 targets; see "Win condition" above.',
              'Not set (leave this slot empty)'),
    'ja-JP': ('目標キャラ %d', '任意。最大 7 体、達成条件は上の項目を参照。', '指定しない（この枠は空き）'),
}

EXTRA_COUNT = {
    'zh-CN': ('第 %d 只的数量', '第 %d 个目标要几只（1 = 本体 0 星，4 = 满星）。'),
    'zh-TW': ('第 %d 隻的數量', '第 %d 個目標要幾隻（1 = 本體 0 星，4 = 滿星）。'),
    'en-US': ('Target %d count', 'How many copies target #%d needs (1 = base, 4 = max star).'),
    'ja-JP': ('%d 体目の必要数', '%d 体目の目標に必要な数（1 = 本体・0 凸、4 = 完凸）。'),
}


def main():
    for lang, mapping in TEXT.items():
        name, help_text, none_text = EXTRA_TARGET[lang]
        count_name, count_help = EXTRA_COUNT[lang]
        for index in range(2, 8):
            mapping['Starsavior2.Target%d.name' % index] = name % index
            mapping['Starsavior2.Target%d.help' % index] = help_text
            mapping['Starsavior2.Target%d.none' % index] = none_text
            mapping['Starsavior2.TargetCount%d.name' % index] = count_name % index
            mapping['Starsavior2.TargetCount%d.help' % index] = count_help % index
        path = os.path.join(I18N, '%s.json' % lang)
        data = read_file(path)
        for key, value in mapping.items():
            deep_set(data, key.split('.'), value)
        write_file(path, data)
        print('%s: %d keys' % (lang, len(mapping)))


if __name__ == '__main__':
    main()
