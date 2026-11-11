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
        'help': '嘟嘟脸恶作剧的登录、签到、邮箱、好友、任务、商店免费礼包、普通商店批量购买与冒险通行证',
    },
    'zh-TW': {
        'name': '嘟嘟臉惡作劇',
        'help': '嘟嘟臉惡作劇的登入、簽到、信箱、好友、任務、商店免費禮包、普通商店批量購買與冒險通行證',
    },
    'en-US': {
        'name': 'Trickcal',
        'help': 'Trickcal login, daily sign-in, mailbox, friends, tasks, the shop free gifts, '
                'bulk purchase in the normal shop and the adventure pass',
    },
    'ja-JP': {
        'name': 'Trickcal',
        'help': 'Trickcal のログイン・デイリーサインイン・メール・フレンド・タスク・'
                'ショップ無料パック・通常ショップの一括購入・冒険パス',
    },
}

NORMAL_SHOP_TEXT = {
    'zh-CN': {
        'name': '嘟嘟普通商店',
        'help': '从主界面底部的「商店」进入普通商店，只买「日常商店」这一页签'
                '（其他页签花的是别的货币，不会去点）。先用「全选」把 6 件商品全部勾上，'
                '再点「一键购买」，购买确认与获得奖励弹窗自动处理，最后返回主界面。',
    },
    'zh-TW': {
        'name': '嘟嘟普通商店',
        'help': '從主畫面底部的「商店」進入普通商店，只買「日常商店」這個頁籤'
                '（其他頁籤花的是別的貨幣，不會去點）。先用「全選」把 6 件商品全部勾上，'
                '再點「一鍵購買」，購買確認與獲得獎勵彈窗自動處理，最後回到主畫面。',
    },
    'en-US': {
        'name': 'Trickcal Normal Shop',
        'help': 'Open the normal shop from the 商店 icon at the bottom of the lobby and buy only '
                'the 日常商店 tab - the other tabs spend different currencies and are never '
                'touched. Tick all six items with 全選, press 一鍵購買, confirm the purchase '
                'dialog, dismiss the reward panel and return to the lobby.',
    },
    'ja-JP': {
        'name': 'Trickcal 通常ショップ',
        'help': 'ロビー下部の「商店」から通常ショップを開き、「日常商店」タブだけを購入します'
                '（他のタブは別の通貨なので触りません）。「全選」で6件すべてにチェックを入れ、'
                '「一鍵購買」を押して購入確認と報酬パネルを処理し、ロビーに戻ります。',
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
    'TrickcalMail': {
        'zh-CN': {
            'name': '嘟嘟邮箱',
            'help': '从主界面右上角的信封进入邮箱，用右下角「一键领取」把附件全领掉，'
                    '弹出的「确认领取」弹窗自动点掉，最后回到主界面。每天日更后跑一次。',
        },
        'zh-TW': {
            'name': '嘟嘟信箱',
            'help': '從主畫面右上角的信封進入信箱，用右下角「一鍵領取」把附件全領掉，'
                    '彈出的「確認領取」彈窗自動點掉，最後回到主畫面。每天日更後跑一次。',
        },
        'en-US': {
            'name': 'Trickcal Mail',
            'help': 'Open the mailbox from the envelope at the top right of the lobby, claim every '
                    'attachment with the bottom-right claim-all button, dismiss the confirmation '
                    'reward popup, and return to the lobby. Runs once after the daily reset.',
        },
        'ja-JP': {
            'name': 'Trickcal メール',
            'help': 'ロビー右上の封筒からメールボックスを開き、右下の「一鍵領取」で添付をすべて受け取り、'
                    '「確認領取」の報酬ポップアップを閉じてロビーに戻ります。日次更新後に 1 回実行します。',
        },
    },
    'TrickcalFriend': {
        'zh-CN': {
            'name': '嘟嘟好友',
            'help': '进主界面右上角的好友页，有叶子可领时「一键领取」会亮起来，亮着才点；'
                    '随后点「一键发送」给好友回礼，最后返回主界面。'
                    '这两个按钮都不弹窗，点完即走。',
        },
        'zh-TW': {
            'name': '嘟嘟好友',
            'help': '進主畫面右上角的好友頁，有葉子可領時「一鍵領取」會亮起來，亮著才點；'
                    '接著點「一鍵發送」回禮給好友，最後返回主畫面。這兩個按鈕都不彈窗，點完即走。',
        },
        'en-US': {
            'name': 'Trickcal Friends',
            'help': 'Open the friend list from the top right of the lobby. The claim-all button lights '
                    'up when friends have sent leaves, and is only clicked while lit; then send one '
                    'back with the send-all button and return to the lobby. Neither button opens a '
                    'popup, so the run does not wait for one.',
        },
        'ja-JP': {
            'name': 'Trickcal フレンド',
            'help': 'ロビー右上のフレンド画面を開き、受け取れる葉があると「一鍵領取」が光るので、'
                    '光っているときだけ押します。続けて「一鍵發送」でお返しし、ロビーに戻ります。'
                    'どちらのボタンもポップアップを出しません。',
        },
    },
    'TrickcalTask': {
        'zh-CN': {
            'name': '嘟嘟任务',
            'help': '从主界面右上角的清单进入任务页（默认停在每日任务），先点右下角「全部领取」，'
                    '再看左下角的「领取」能不能领；然后切到「收获满满的一周」，照同样顺序领一遍，'
                    '最后返回主界面。按钮亮着才点，灰的说明没得领。',
        },
        'zh-TW': {
            'name': '嘟嘟任務',
            'help': '從主畫面右上角的清單進入任務頁（預設停在每日任務），先點右下角「全部領取」，'
                    '再看左下角的「領取」能不能領；接著切到「收穫滿滿的一週」，照同樣順序領一遍，'
                    '最後回到主畫面。按鈕亮著才點，灰的代表沒得領。',
        },
        'en-US': {
            'name': 'Trickcal Tasks',
            'help': 'Open the task list from the checklist at the top right of the lobby (it opens on '
                    'the daily tab), claim with the bottom-right claim-all button, then claim the '
                    'bottom-left point-track reward if it is lit; switch to the weekly tab and repeat '
                    'the same order, then return to the lobby. A button is only clicked while lit; '
                    'grey means there is nothing to claim.',
        },
        'ja-JP': {
            'name': 'Trickcal タスク',
            'help': 'ロビー右上のチェックリストからタスク画面を開き（デイリータスクが既定）、'
                    'まず右下の「全部領取」、次に左下の「領取」が光っていれば受け取ります。'
                    '続けて「収穫満々の一週間」に切り替えて同じ順番でもう一度受け取り、ロビーに戻ります。'
                    'ボタンは光っているときだけ押します。',
        },
    },
    'TrickcalShop': {
        'zh-CN': {
            'name': '嘟嘟尊享商店',
            'help': '从主界面底部进入尊享商店，依次到「水晶叶商店」（每日免费礼包）、'
                    '「每周礼包」、「每月礼包」三个页签，各领一次左上角的免费礼包（价格 0）。'
                    '点完价格条会弹通用奖励弹窗，弹窗出现说明领到了；没有弹窗说明这个周期已经领过，'
                    '直接跳过。三个页签走完返回主界面。',
        },
        'zh-TW': {
            'name': '嘟嘟尊享商店',
            'help': '從主畫面底部進入尊享商店，依序到「水晶葉商店」（每日免費禮包）、'
                    '「每週禮包」、「每月禮包」三個頁籤，各領一次左上角的免費禮包（價格 0）。'
                    '點完價格條會彈通用獎勵彈窗，彈窗出現代表領到了；沒有彈窗代表這個週期已經領過，'
                    '直接跳過。三個頁籤走完回到主畫面。',
        },
        'en-US': {
            'name': 'Trickcal Shop',
            'help': 'Open the premium shop from the bottom bar of the lobby and visit the three tabs '
                    'in order - 水晶葉商店 (the daily free pack), 每週禮包 and 每月禮包 - claiming the '
                    'free pack in the top-left slot of each (price 0). Claiming pops the generic '
                    'reward panel; the panel showing up is the receipt, and no panel means that pack '
                    'was already taken this period, so it is skipped. The task then returns to the '
                    'lobby.',
        },
        'ja-JP': {
            'name': 'Trickcal ショップ',
            'help': 'ロビー下部から尊享商店を開き、「水晶葉商店」（デイリー無料パック）、'
                    '「每週禮包」「每月禮包」の3タブを順に回り、左上の無料パック（価格0）を'
                    'それぞれ1回受け取ります。価格バーを押すと共通の報酬パネルが出れば受け取り成功、'
                    '出なければその期間は受け取り済みなのでスキップします。最後にロビーへ戻ります。',
        },
    },
}


PASS_TEXT = {
    'zh-CN': {
        'name': '嘟嘟冒险通行证',
        'help': '从主界面左上角的「冒险通行证」（蓝色票券，不是旁边的等级通行证）进入，'
                '点右下角「一键领取」把能领的奖励一次领完；没有奖励时按钮是暗的，直接返回。'
                '获得奖励弹窗自动点掉，最后回到主界面。',
    },
    'zh-TW': {
        'name': '嘟嘟冒險通行證',
        'help': '從主畫面左上角的「冒險通行證」（藍色票券，不是旁邊的等級通行證）進入，'
                '點右下角「一鍵領取」把能領的獎勵一次領完；沒有獎勵時按鈕是暗的，直接返回。'
                '獲得獎勵彈窗自動點掉，最後回到主畫面。',
    },
    'en-US': {
        'name': 'Trickcal Adventure Pass',
        'help': 'Open the 冒險通行證 card at the top left of the lobby (the blue ticket, not the '
                'level pass next to it) and press the bottom-right 一鍵領取 to take every unlocked '
                'reward at once. The button is dim when there is nothing to claim, and the run then '
                'returns immediately. The reward panel is dismissed automatically.',
    },
    'ja-JP': {
        'name': 'Trickcal 冒険パス',
        'help': 'ロビー左上の「冒険通行証」（青いチケット。隣のレベルパスではありません）を開き、'
                '右下の「一鍵領取」で受け取れる報酬をまとめて受け取ります。受け取るものが無いと'
                'ボタンは暗くなり、そのまま戻ります。報酬パネルは自動で閉じます。',
    },
}

# 新增任务只在这里追加一行，TASKS 本体保持按接入顺序排列，读起来就是任务表。
TASKS['TrickcalNormalShop'] = NORMAL_SHOP_TEXT
TASKS['TrickcalPass'] = PASS_TEXT


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
