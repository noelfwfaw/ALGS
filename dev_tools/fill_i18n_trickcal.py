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
        'help': '嘟嘟脸恶作剧的登录、签到、邮箱、好友、主题剧院活动、资源副本、任务、商店免费礼包、普通商店批量购买与冒险通行证',
    },
    'zh-TW': {
        'name': '嘟嘟臉惡作劇',
        'help': '嘟嘟臉惡作劇的登入、簽到、信箱、好友、主題劇院活動、資源副本、任務、商店免費禮包、普通商店批量購買與冒險通行證',
    },
    'en-US': {
        'name': 'Trickcal',
        'help': 'Trickcal login, daily sign-in, mailbox, friends, theme-theater events, resource dungeons, tasks, the shop free gifts, '
                'bulk purchase in the normal shop and the adventure pass',
    },
    'ja-JP': {
        'name': 'Trickcal',
        'help': 'Trickcal のログイン・デイリーサインイン・メール・フレンド・テーマ劇場イベント・資源ダンジョン・タスク・'
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
        'name': '嘟嘟通行证',
        'help': '从主界面左上角分别进入「冒险通行证」与「便装通行证」（存在时），'
                '点右下角「一键领取」把能领的奖励一次领完；没有奖励时按钮变暗或置灰直接返回，'
                '获得奖励弹窗自动点掉，最后回到主界面。',
    },
    'zh-TW': {
        'name': '嘟嘟通行證',
        'help': '從主畫面左上角分別進入「冒險通行證」與「便裝通行證」（存在時），'
                '點右下角「一鍵領取」把能領的獎勵一次領完；沒有獎勵時按鈕變暗或置灰直接返回，'
                '獲得獎勵彈窗自動點掉，最後回到主畫面。',
    },
    'en-US': {
        'name': 'Trickcal Pass',
        'help': 'Open 冒险通行证 and 便装通行证 (when active) at the top left of the lobby and press '
                'bottom-right 一键领取 to collect available rewards. Skips cleanly when grey/dim or '
                'inactive, dismisses reward popups, and returns to the lobby.',
    },
    'ja-JP': {
        'name': 'Trickcal パス',
        'help': 'ロビー左上の「冒険通行証」と「便装通行証」（開催時）を開き、'
                '右下の「一鍵領取」で受け取れる報酬をまとめて受け取ります。受け取るものが無い場合や'
                '未開催時はそのまま戻り、報酬パネルは自動で閉じます。',
    },
}

EVENT_TEXT = {
    'zh-CN': {
        'name': '嘟嘟活动',
        'help': '从主界面左上角入口进入主题剧院活动，自动跳过首次开场剧情与说明弹窗；'
                '先开荒已解锁的「微微辣」「中辣」「变态辣」战斗难度并可选回微微辣速战清体力；'
                '再去「活动剧情」跳过带 NEW 标记的未读剧情，去「成就」三页签一键领取全部奖励，'
                '最后去「活动商店」严格按从上到下、从左到右顺序购买未售罄商品。',
    },
    'zh-TW': {
        'name': '嘟嘟活動',
        'help': '從主畫面左上角入口進入主題劇院活動，自動跳過首次開場劇情與說明彈窗；'
                '先開荒已解鎖的「微微辣」「中辣」「變態辣」戰鬥難度並可選回微微辣速戰清體力；'
                '再去「活動劇情」跳過帶 NEW 標記的未讀劇情，去「成就」三頁籤一鍵領取全部獎勵，'
                '最後去「活動商店」嚴格按由上到下、由左到右順序購買未售罄商品。',
    },
    'en-US': {
        'name': 'Trickcal Event',
        'help': 'Enter the theme-theater event, clear unlocked battle difficulties and optionally sweep '
                'stamina in 微微辣, skip NEW event stories, claim rewards across all three task tabs, '
                'and buy unsold items from the event shop strictly top-to-bottom without skipping.',
    },
    'ja-JP': {
        'name': 'Trickcal イベント',
        'help': 'テーマ劇場イベントに入り、戦闘ステージの攻略と任意のスタミナ消化後、'
                '未読ストーリー（NEW）のスキップ、実績・デイリー・ピクセル報酬の一括受取、'
                'イベントショップでの上から順番購入を行います。',
    },
}

DUNGEON_TEXT = {
    'zh-CN': {
        'name': '嘟嘟副本',
        'help': '从主界面「冒险 -> 副本」进入资源副本消耗星星糖体力（与活动的朱珠糖体力互不冲突）。'
                '先刷「克隆工厂」每日 8 次，再用剩余星星糖速战所选主刷副本的目标三星关卡；星星糖不足时不购买体力。',
    },
    'zh-TW': {
        'name': '嘟嘟副本',
        'help': '從主畫面「冒險 -> 副本」進入資源副本消耗星星糖體力（與活動的朱珠糖體力互不衝突）。'
                '先刷「克隆工廠」每日 8 次，再用剩餘星星糖速戰所選主刷副本的目標三星關卡；星星糖不足時不購買體力。',
    },
    'en-US': {
        'name': 'Trickcal Dungeon',
        'help': 'Spend star-candy stamina in resource dungeons via 冒险 -> 副本 (independent of event stamina). '
                'Optionally sweep 克隆工厂 (8 daily entries) first, then sweep the chosen main dungeon and stage.',
    },
    'ja-JP': {
        'name': 'Trickcal 副本',
        'help': '「冒險 -> 副本」からスターキャンディ（星星糖）を消費するダンジョンを周回します。'
                '先にクローンプラント（1日8回）を速戦し、残りで選択したダンジョンの指定ステージを速戦します。',
    },
}

CLASS_TEXT = {
    'zh-CN': {
        'name': '嘟嘟速成班',
        'help': '从主界面「冒险 -> 短期速成班」进入每日限免速战课程（每天免费 2 次、不消耗体力，凌晨 3 点刷新）。'
                '周一至周五自动选择当天开放的属性班，周六/周日多班同开时按配置选择，共 25 课（填 0 自动选最高三星课）。',
    },
    'zh-TW': {
        'name': '嘟嘟速成班',
        'help': '從主畫面「冒險 -> 短期速成班」進入每日限免速戰課程（每天免費 2 次、不消耗體力，凌晨 3 點重設）。'
                '週一至週五自動選擇當天開放的屬性班，週六/週日多班同開時依設定選擇，共 25 課（填 0 自動選最高三星課）。',
    },
    'en-US': {
        'name': 'Trickcal Short Class',
        'help': 'Sweep 短期速成班 via 冒险 -> 短期速成班 (2 free runs/day, 0 stamina, resets at 03:00). '
                'Picks the single open class on Mon-Fri and follows SaturdaySubject/SundaySubject on weekends; '
                '25 lessons per subject (0 = auto-pick highest 3-starred lesson).',
    },
    'ja-JP': {
        'name': 'Trickcal 短期速成班',
        'help': '「冒険 -> 短期速成班」で毎日2回の無料速戦を行います（スタミナ消費なし、午前3時リセット）。'
                '月〜金は解放中のクラスを自動選択し、土日は設定に従います。全25課（0で最高星3課を自動選択）。',
    },
}

DOLL_TEXT = {
    'zh-CN': {
        'name': '嘟嘟娃娃怪',
        'help': '从主界面「冒险 -> 娃娃怪破坏者」进入，按选项选择 8 个种族之一，直接对当前可速战的默认关卡执行速战'
                '（每日最多 4 次，每次消耗 10 红糖体力与 1 张门票，不可自选关卡，体力不足不购买）。',
    },
    'zh-TW': {
        'name': '嘟嘟娃娃怪',
        'help': '從主畫面「冒險 -> 娃娃怪破壞者」進入，依選項選擇 8 個種族之一，直接對目前可速戰的預設關卡執行速戰'
                '（每日最多 4 次，每次消耗 10 紅糖體力與 1 張門票，不可自選關卡，體力不足不購買）。',
    },
    'en-US': {
        'name': 'Trickcal Doll Buster',
        'help': 'Enter 冒险 -> 娃娃怪破坏者, pick one of the 8 races, and sweep the default sweepable stage '
                '(4 daily tickets, 10 red candy + 1 ticket per run, no stage selection, never buys stamina).',
    },
    'ja-JP': {
        'name': 'Trickcal 娃娃怪破坏者',
        'help': '「冒険 -> 娃娃怪破坏者」で 8 種族から 1 つを選び、デフォルトの速戦可能ステージを速戦します'
                '（1 日 4 回まで、1 回 10 赤キャンディ＋チケット 1 枚消費、スタミナ購入なし）。',
    },
}

PVP_TEXT = {
    'zh-CN': {
        'name': '嘟嘟巅峰对决',
        'help': '从主界面「冒险 -> 巅峰对决 -> 胜利者的竞技场」进入，自动领奖励并挑战所选对手（默认打第 1 个对手，每日 5 次，不消耗体力）。',
    },
    'zh-TW': {
        'name': '嘟嘟巔峰對決',
        'help': '從主畫面「冒險 -> 巔峰對決 -> 勝利者的競技場」進入，自動領取獎勵並挑戰所選對手（預設打第 1 個對手，每日 5 次，不消耗體力）。',
    },
    'en-US': {
        'name': 'Trickcal Arena',
        'help': 'Enter 冒险 -> 巅峰对决 -> 胜利者的竞技场, claim hourly reward if available, and fight the chosen opponent (defaults to opponent 1, 5 daily runs, 0 stamina).',
    },
    'ja-JP': {
        'name': 'Trickcal 巅峰对决',
        'help': '「冒険 -> 巅峰对决 -> 勝利者の競技場」に入り、蓄積報酬を受け取って選択した相手に挑戦します（初期値: 1人目、1日5回、スタミナ消費なし）。',
    },
}

ORDER_TEXT = {
    'zh-CN': {
        'name': '嘟嘟圣团',
        'help': '从主界面右下角进入「圣团 -> 总部 -> 世界树圣物」，每日领取圣物奖励（不消耗体力，调度在消耗体力任务前）。',
    },
    'zh-TW': {
        'name': '嘟嘟聖團',
        'help': '從主畫面右下角進入「聖團 -> 總部 -> 世界樹聖物」，每日領取聖物獎勵（不消耗體力，調度在消耗體力任務前）。',
    },
    'en-US': {
        'name': 'Trickcal Order',
        'help': 'Enter bottom-right 圣团 -> 总部 -> 世界树圣物 from the lobby to claim the daily relic reward (0 stamina, scheduled before stamina tasks).',
    },
    'ja-JP': {
        'name': 'Trickcal 聖団',
        'help': 'ホーム右下の「聖団 -> 本部 -> 世界樹の聖物」から毎日の聖物報酬を受け取ります（スタミナ消費なし）。',
    },
}

GROUPS = {
    'TrickcalEvent': {
        'zh-CN': {
            '_info': {'name': '嘟嘟活动设置', 'help': ''},
            'SweepStamina': {
                'name': '速战清体力',
                'help': '开荒结束后回到「微微辣」，对已三星的末尾关卡点「速战 -> 最大 -> 速战」消耗剩余体力；关闭后只做开荒。',
            },
        },
        'zh-TW': {
            '_info': {'name': '嘟嘟活動設定', 'help': ''},
            'SweepStamina': {
                'name': '速戰清體力',
                'help': '開荒結束後回到「微微辣」，對已三星的末尾關卡點「速戰 -> 最大 -> 速戰」消耗剩餘體力；關閉後只做開荒。',
            },
        },
        'en-US': {
            '_info': {'name': 'Trickcal Event Settings', 'help': ''},
            'SweepStamina': {
                'name': 'Sweep remaining stamina',
                'help': 'After clearing difficulties, switch back to 微微辣 and sweep the 3-starred last stage until stamina is below 10. Turn off to only clear new stages.',
            },
        },
        'ja-JP': {
            '_info': {'name': 'イベント設定', 'help': ''},
            'SweepStamina': {
                'name': '速戦でスタミナ消化',
                'help': '攻略完了後に「微微辣」へ戻り、星3クリア済みの最終ステージでスタミナが10未満になるまで「速戦」を行います。オフにすると初回攻略のみ行います。',
            },
        },
    },
    'TrickcalDungeon': {
        'zh-CN': {
            '_info': {'name': '嘟嘟副本设置', 'help': '按先克隆工厂、后主刷副本的顺序速战消耗星星糖'},
            'CloneFactory': {
                'name': '打克隆工厂',
                'help': '开启后先进入「克隆工厂」把每日 8 次速战清完（每次消耗 20 星星糖），再去打下方所选副本。',
            },
            'CloneFactoryStage': {
                'name': '克隆工厂关卡',
                'help': '克隆工厂指定速战的关卡编号（1~12，需已三星解锁速战）。',
            },
            'Dungeon': {
                'name': '主刷副本',
                'help': '清完克隆工厂后用剩余星星糖速战的副本（五个副本里只能选其一）。',
                'none': '不打',
                'gold': '金币大作战',
                'bakery_macaron': '神秘面包房 - 魔卡龙',
                'bakery_cream': '神秘面包房 - 奶卡龙',
                'candy_red': '糖果自由 - 红机(禁防御)',
                'candy_blue': '糖果自由 - 蓝机(禁输出)',
                'candy_green': '糖果自由 - 绿机(禁辅助)',
                'crayon': '到手蜡',
            },
            'DungeonStage': {
                'name': '主刷副本关卡',
                'help': '目标副本内要速战的关卡编号（金币大作战 1~20，其余副本填对应关号；需已三星）。',
            },
        },
        'zh-TW': {
            '_info': {'name': '嘟嘟副本設定', 'help': '按先克隆工廠、後主刷副本的順序速戰消耗星星糖'},
            'CloneFactory': {
                'name': '打克隆工廠',
                'help': '開啟後先進入「克隆工廠」把每日 8 次速戰清完（每次消耗 20 星星糖），再去打下方所選副本。',
            },
            'CloneFactoryStage': {
                'name': '克隆工廠關卡',
                'help': '克隆工廠指定速戰的關卡編號（1~12，需已三星解鎖速戰）。',
            },
            'Dungeon': {
                'name': '主刷副本',
                'help': '清完克隆工廠後用剩餘星星糖速戰的副本（五個副本裡只能選其一）。',
                'none': '不打',
                'gold': '金幣大作戰',
                'bakery_macaron': '神秘麵包房 - 魔卡龍',
                'bakery_cream': '神秘麵包房 - 奶卡龍',
                'candy_red': '糖果自由 - 紅機(禁防禦)',
                'candy_blue': '糖果自由 - 藍機(禁輸出)',
                'candy_green': '糖果自由 - 綠機(禁輔助)',
                'crayon': '到手蠟',
            },
            'DungeonStage': {
                'name': '主刷副本關卡',
                'help': '目標副本內要速戰的關卡編號（金幣大作戰 1~20，其餘副本填對應關號；需已三星）。',
            },
        },
        'en-US': {
            '_info': {'name': 'Trickcal Dungeon Settings', 'help': 'Sweep Clone Factory first, then spend leftover star candy in one chosen dungeon.'},
            'CloneFactory': {
                'name': 'Run Clone Factory',
                'help': 'Sweep up to 8 daily entries in 克隆工厂 (20 star candy each) before running the selected main dungeon.',
            },
            'CloneFactoryStage': {
                'name': 'Clone Factory stage',
                'help': 'Stage number (1-12) to sweep in 克隆工厂 (must already be 3-starred).',
            },
            'Dungeon': {
                'name': 'Main dungeon',
                'help': 'Choose which main dungeon spends the remaining star-candy stamina.',
                'none': 'Disabled',
                'gold': 'Gold Rush (金币大作战)',
                'bakery_macaron': 'Bakery - Macaron (魔卡龙)',
                'bakery_cream': 'Bakery - Cream Puff (奶卡龙)',
                'candy_red': 'Candy - Red (Ban Tank)',
                'candy_blue': 'Candy - Blue (Ban DPS)',
                'candy_green': 'Candy - Green (Ban Support)',
                'crayon': 'Crayon (到手蜡)',
            },
            'DungeonStage': {
                'name': 'Main dungeon stage',
                'help': '3-starred stage number to sweep in the chosen main dungeon.',
            },
        },
        'ja-JP': {
            '_info': {'name': 'ダンジョン設定', 'help': 'クローンプラントを先に速戦し、残りスタミナで選択ダンジョンを周回します。'},
            'CloneFactory': {
                'name': 'クローンプラントを実行',
                'help': 'オンにすると「克隆工厂」の日次 8 回分（1回 20 消費）を先に速戦します。',
            },
            'CloneFactoryStage': {
                'name': 'クローンプラント ステージ',
                'help': '速戦するステージ番号（1〜12、星3クリア済みが必要）。',
            },
            'Dungeon': {
                'name': 'メインダンジョン',
                'help': '残りのスターキャンディで速戦するダンジョンを選択します。',
                'none': '実行しない',
                'gold': '金币大作战',
                'bakery_macaron': '神秘面包房 - 魔卡龙',
                'bakery_cream': '神秘面包房 - 奶卡龙',
                'candy_red': '糖果自由 - 赤(防御禁止)',
                'candy_blue': '糖果自由 - 青(攻撃禁止)',
                'candy_green': '糖果自由 - 緑(支援禁止)',
                'crayon': '到手蜡',
            },
            'DungeonStage': {
                'name': 'メイン ステージ番号',
                'help': '選択したダンジョンで速戦する星3クリア済みステージ番号。',
            },
        },
    },
    'TrickcalClass': {
        'zh-CN': {
            '_info': {'name': '短期速成班设置', 'help': '周一至周五自动进入当天唯一开放的课堂；周末多开时按下方选项进入'},
            'SaturdaySubject': {
                'name': '周六课程选择',
                'help': '周六同时开放纯粹(绿)、冷静(蓝)、狂乱(红)三个课堂时优先进入哪一个。',
                'green': '纯粹 (绿)',
                'blue': '冷静 (蓝)',
                'red': '狂乱 (红)',
            },
            'SundaySubject': {
                'name': '周日课程选择',
                'help': '周日同时开放活泼(黄)、忧郁(紫)两个课堂时优先进入哪一个。',
                'yellow': '活泼 (黄)',
                'purple': '忧郁 (紫)',
            },
            'GreenLesson': {
                'name': '纯粹 (绿) 课数',
                'help': '周六/周一纯粹班速战第几课（1~25 需已三星；填 0 自动选最高三星课）。',
            },
            'BlueLesson': {
                'name': '冷静 (蓝) 课数',
                'help': '周六/周二冷静班速战第几课（1~25 需已三星；填 0 自动选最高三星课）。',
            },
            'RedLesson': {
                'name': '狂乱 (红) 课数',
                'help': '周六/周三狂乱班速战第几课（1~25 需已三星；填 0 自动选最高三星课）。',
            },
            'YellowLesson': {
                'name': '活泼 (黄) 课数',
                'help': '周日/周四活泼班速战第几课（1~25 需已三星；填 0 自动选最高三星课）。',
            },
            'PurpleLesson': {
                'name': '忧郁 (紫) 课数',
                'help': '周日/周五忧郁班速战第几课（1~25 需已三星；填 0 自动选最高三星课）。',
            },
        },
        'zh-TW': {
            '_info': {'name': '短期速成班設定', 'help': '週一至週五自動進入當天唯一開放的課堂；週末多開時依下方選項進入'},
            'SaturdaySubject': {
                'name': '週六課程選擇',
                'help': '週六同時開放純粹(綠)、冷靜(藍)、狂亂(紅)三個課堂時優先進入哪一個。',
                'green': '純粹 (綠)',
                'blue': '冷靜 (藍)',
                'red': '狂亂 (紅)',
            },
            'SundaySubject': {
                'name': '週日課程選擇',
                'help': '週日同時開放活潑(黃)、憂鬱(紫)兩個課堂時優先進入哪一個。',
                'yellow': '活潑 (黃)',
                'purple': '憂鬱 (紫)',
            },
            'GreenLesson': {
                'name': '純粹 (綠) 課數',
                'help': '週六/週一純粹班速戰第幾課（1~25 需已三星；填 0 自動選最高三星課）。',
            },
            'BlueLesson': {
                'name': '冷靜 (藍) 課數',
                'help': '週六/週二冷靜班速戰第幾課（1~25 需已三星；填 0 自動選最高三星課）。',
            },
            'RedLesson': {
                'name': '狂亂 (紅) 課數',
                'help': '週六/週三狂亂班速戰第幾課（1~25 需已三星；填 0 自動選最高三星課）。',
            },
            'YellowLesson': {
                'name': '活潑 (黃) 課數',
                'help': '週日/週四活潑班速戰第幾課（1~25 需已三星；填 0 自動選最高三星課）。',
            },
            'PurpleLesson': {
                'name': '憂鬱 (紫) 課數',
                'help': '週日/週五憂鬱班速戰第幾課（1~25 需已三星；填 0 自動選最高三星課）。',
            },
        },
        'en-US': {
            '_info': {'name': 'Short Class Settings', 'help': 'Auto-picks the single open class Mon-Fri; uses weekend selections on Sat/Sun'},
            'SaturdaySubject': {
                'name': 'Saturday subject',
                'help': 'Which subject to enter on Saturday when green/blue/red are open together.',
                'green': 'Green (纯粹)',
                'blue': 'Blue (冷静)',
                'red': 'Red (狂乱)',
            },
            'SundaySubject': {
                'name': 'Sunday subject',
                'help': 'Which subject to enter on Sunday when yellow/purple are open together.',
                'yellow': 'Yellow (活泼)',
                'purple': 'Purple (忧郁)',
            },
            'GreenLesson': {
                'name': 'Green lesson',
                'help': 'Lesson (1-25) to sweep for Green (0 = highest 3-starred lesson).',
            },
            'BlueLesson': {
                'name': 'Blue lesson',
                'help': 'Lesson (1-25) to sweep for Blue (0 = highest 3-starred lesson).',
            },
            'RedLesson': {
                'name': 'Red lesson',
                'help': 'Lesson (1-25) to sweep for Red (0 = highest 3-starred lesson).',
            },
            'YellowLesson': {
                'name': 'Yellow lesson',
                'help': 'Lesson (1-25) to sweep for Yellow (0 = highest 3-starred lesson).',
            },
            'PurpleLesson': {
                'name': 'Purple lesson',
                'help': 'Lesson (1-25) to sweep for Purple (0 = highest 3-starred lesson).',
            },
        },
        'ja-JP': {
            '_info': {'name': '短期速成班設定', 'help': '平日は解放中のクラスを自動選択し、土日は下の設定に従います'},
            'SaturdaySubject': {
                'name': '土曜日のクラス',
                'help': '土曜日に緑・青・赤が同時開放された際に周回するクラスを選択します。',
                'green': '純粋 (緑)',
                'blue': '冷静 (青)',
                'red': '狂乱 (赤)',
            },
            'SundaySubject': {
                'name': '日曜日のクラス',
                'help': '日曜日に黄・紫が同時開放された際に周回するクラスを選択します。',
                'yellow': '活発 (黄)',
                'purple': '憂鬱 (紫)',
            },
            'GreenLesson': {
                'name': '純粋 (緑) 課番号',
                'help': '速戦する課番号（1〜25、星3が必要；0で最高星3課を自動選択）。',
            },
            'BlueLesson': {
                'name': '冷静 (青) 課番号',
                'help': '速戦する課番号（1〜25、星3が必要；0で最高星3課を自動選択）。',
            },
            'RedLesson': {
                'name': '狂乱 (赤) 課番号',
                'help': '速戦する課番号（1〜25、星3が必要；0で最高星3課を自動選択）。',
            },
            'YellowLesson': {
                'name': '活発 (黄) 課番号',
                'help': '速戦する課番号（1〜25、星3が必要；0で最高星3課を自動選択）。',
            },
            'PurpleLesson': {
                'name': '憂鬱 (紫) 課番号',
                'help': '速戦する課番号（1〜25、星3が必要；0で最高星3課を自動選択）。',
            },
        },
    },
    'TrickcalDoll': {
        'zh-CN': {
            '_info': {'name': '娃娃怪破坏者设置', 'help': '每天最多打 4 次（每次 10 红糖 + 1 票），选择对应种族后直接速战默认可速战关卡'},
            'Race': {
                'name': '选择种族',
                'help': '从 8 个可选种族中挑一个进入并速战。',
                'dragon': '龙族',
                'elf': '精灵',
                'ghost': '幽灵',
                'fairy': '仙灵',
                'witch': '魔女',
                'elemental': '自然灵',
                'mystic': '秘灵',
                'beast': '兽人',
            },
        },
        'zh-TW': {
            '_info': {'name': '娃娃怪破壞者設定', 'help': '每天最多打 4 次（每次 10 紅糖 + 1 票），選擇對應種族後直接速戰預設可速戰關卡'},
            'Race': {
                'name': '選擇種族',
                'help': '從 8 個可選種族中挑一個進入並速戰。',
                'dragon': '龍族',
                'elf': '精靈',
                'ghost': '幽靈',
                'fairy': '仙靈',
                'witch': '魔女',
                'elemental': '自然靈',
                'mystic': '秘靈',
                'beast': '獸人',
            },
        },
        'en-US': {
            '_info': {'name': 'Doll Buster Settings', 'help': 'Up to 4 runs/day (10 red candy + 1 ticket each); sweeps the default unlocked stage'},
            'Race': {
                'name': 'Race',
                'help': 'Which of the 8 races to enter and sweep.',
                'dragon': 'Dragon (龙族)',
                'elf': 'Elf (精灵)',
                'ghost': 'Ghost (幽灵)',
                'fairy': 'Fairy (仙灵)',
                'witch': 'Witch (魔女)',
                'elemental': 'Elemental (自然灵)',
                'mystic': 'Mystic (秘灵)',
                'beast': 'Beast (兽人)',
            },
        },
        'ja-JP': {
            '_info': {'name': '娃娃怪破坏者設定', 'help': '1 日 4 回まで（1 回 10 赤キャンディ＋1 チケット）、選択種族のデフォルトステージを速戦します'},
            'Race': {
                'name': '種族選択',
                'help': '挑戦して速戦する種族を 8 つから選択します。',
                'dragon': '竜族 (龙族)',
                'elf': 'エルフ (精灵)',
                'ghost': 'ゴースト (幽灵)',
                'fairy': '妖精 (仙灵)',
                'witch': '魔女',
                'elemental': '精霊 (自然灵)',
                'mystic': '秘霊 (秘灵)',
                'beast': '獣人 (兽人)',
            },
        },
    },
    'TrickcalPvp': {
        'zh-CN': {
            '_info': {'name': '巅峰对决设置', 'help': '进入「胜利者的竞技场」每日挑战 5 次（默认打第 1 个对手）'},
            'Opponent': {
                'name': '挑战对手顺位',
                'help': '选择对手列表中从上到下挑战哪一个对手（1 = 第 1 个对手，2 = 第 2 个，3 = 第 3 个）。',
                '1': '第 1 个对手',
                '2': '第 2 个对手',
                '3': '第 3 个对手',
            },
        },
        'zh-TW': {
            '_info': {'name': '巔峰對決設定', 'help': '進入「勝利者的競技場」每日挑戰 5 次（預設打第 1 個對手）'},
            'Opponent': {
                'name': '挑戰對手順位',
                'help': '選擇對手列表中從上到下挑戰哪一個對手（1 = 第 1 個對手，2 = 第 2 個，3 = 第 3 個）。',
                '1': '第 1 個對手',
                '2': '第 2 個對手',
                '3': '第 3 個對手',
            },
        },
        'en-US': {
            '_info': {'name': 'Arena Settings', 'help': 'Run 5 daily matches in 胜利者的竞技场 (defaults to opponent 1)'},
            'Opponent': {
                'name': 'Opponent slot',
                'help': 'Which opponent row from top to bottom to challenge.',
                '1': 'Opponent 1',
                '2': 'Opponent 2',
                '3': 'Opponent 3',
            },
        },
        'ja-JP': {
            '_info': {'name': '巅峰对决設定', 'help': '「勝利者の競技場」で1日5回対戦します（初期値: 1人目）'},
            'Opponent': {
                'name': '対戦相手の順位',
                'help': '対戦相手リストの上から何番目に挑戦するか選択します。',
                '1': '1人目',
                '2': '2人目',
                '3': '3人目',
            },
        },
    },
}

# 新增任务只在这里追加一行，TASKS 本体保持按接入顺序排列，读起来就是任务表。
TASKS['TrickcalNormalShop'] = NORMAL_SHOP_TEXT
TASKS['TrickcalPass'] = PASS_TEXT
TASKS['TrickcalEvent'] = EVENT_TEXT
TASKS['TrickcalDungeon'] = DUNGEON_TEXT
TASKS['TrickcalClass'] = CLASS_TEXT
TASKS['TrickcalDoll'] = DOLL_TEXT
TASKS['TrickcalPvp'] = PVP_TEXT
TASKS['TrickcalOrder'] = ORDER_TEXT


def main():
    """Write the strings into each language file, keeping the existing keys."""
    for lang in LANGS:
        path = os.path.join(ROOT, 'module', 'config', 'i18n', lang + '.json')
        with open(path, encoding='utf-8') as f:
            data = json.load(f)

        data['Menu']['Trickcal'] = MENU[lang]
        for task, texts in TASKS.items():
            data['Task'][task] = texts[lang]
        for group, texts in GROUPS.items():
            data[group] = texts[lang]

        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        print(f'{lang}: Menu.Trickcal + {len(TASKS)} task(s)')


if __name__ == '__main__':
    main()
