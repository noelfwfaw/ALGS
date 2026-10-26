"""Fill the Hazeworld translations of module/config/i18n/*.json.

`config_updater` only generates the key skeleton, it does not invent wording.
This script writes the actual name/help for the Hazeworld menu, tasks and
options, and then the skeleton gets merged back by `config_updater`.

Usage:
    ./toolkit/python.exe -m dev_tools.fill_i18n_hazeworld
"""
import json
import os

from module.config.utils import filepath_i18n

TRANSLATIONS = {
    'zh-CN': {
        'Menu': {
            'Hazeworld': {'name': '苍雾世界', 'help': '苍雾世界的日常任务'},
        },
        'Task': {
            'HazeworldMail': {'name': '邮件', 'help': '领取邮箱里的附件'},
            'HazeworldRoom': {'name': '指挥室', 'help': '收取指挥室资源，并处理远征'},
            'HazeworldExercise': {'name': '演习', 'help': '用每天的演习券打完竞技场'},
            'HazeworldFriend': {'name': '好友', 'help': '给所有好友点赞'},
            'HazeworldTask': {'name': '任务', 'help': '领取每日/每周/每月任务奖励'},
            'HazeworldPass': {'name': '通行证', 'help': '领取通行证奖励'},
            'HazeworldSupport': {'name': '支援角色',
                                 'help': '领取支援角色的友情币（绿币）'},
            'HazeworldCore': {'name': '核心制造',
                              'help': '在资源副本「核心制造」里扫荡核心材料，消耗体力'},
        },
        'HazeworldMail': {
            '_info': {'name': '邮件设置', 'help': ''},
            'ClaimAll': {'name': '领取全部邮件',
                         'help': '在邮件页点击「领取全部」，一次领完所有未读邮件的附件'},
        },
        'HazeworldRoom': {
            '_info': {'name': '指挥室设置', 'help': ''},
            'CollectAll': {'name': '收取全部资源',
                           'help': '在指挥室点击「全部收集」，收取已经产出的资源'},
            'Expedition': {'name': '处理远征',
                           'help': '领取已经完成的远征奖励，并再次派遣'},
        },
        'HazeworldExercise': {
            '_info': {'name': '演习设置', 'help': ''},
            'ProxyBattle': {'name': '使用代理作战',
                            'help': '用「代理作战」一次扫荡完当天所有演习券；关闭后一场场手动开战，可以看到战斗过程'},
        },
        'HazeworldFriend': {
            '_info': {'name': '好友设置', 'help': ''},
            'LikeAll': {'name': '一键点赞',
                        'help': '在好友列表点击「一键点赞」，给所有好友点赞'},
        },
        'HazeworldTask': {
            '_info': {'name': '任务设置', 'help': ''},
            'ClaimDaily': {'name': '领取每日任务奖励',
                           'help': '切到「每日」页签，点击「一键领取」'},
            'ClaimWeekly': {'name': '领取每周任务奖励',
                            'help': '切到「每周」页签，点击「一键领取」'},
            'ClaimMonthly': {'name': '领取每月任务奖励',
                             'help': '切到「每月」页签，点击「一键领取」'},
        },
        'HazeworldPass': {
            '_info': {'name': '通行证设置', 'help': ''},
            'ClaimAll': {'name': '领取全部通行证奖励',
                         'help': '在通行证页点击「一键领取」'},
        },
        'HazeworldSupport': {
            '_info': {'name': '支援角色设置', 'help': ''},
            'ClaimAll': {'name': '领取友情币',
                         'help': '在玩家档案里打开「支援角色」，逐个领取每个支援角色的友情币（绿币），每日上限 50000'},
        },
        'HazeworldCore': {
            '_info': {'name': '核心制造设置', 'help': ''},
            'Core': {'name': '核心种类',
                     'help': '要刷哪一类核心。只有选中的那一条左侧有金色高亮',
                     'Life': '生命核心', 'Attack': '攻击核心',
                     'Armor': '装甲核心', 'Critical': '暴击核心',
                     'Burst': '爆发核心'},
            'SweepCount': {'name': '扫荡次数',
                           'help': '0 表示点「MAX」把体力一次花完；填正数则只扫荡这么多次。\n关卡用游戏内当前选中的那一关，请先在游戏里选好（脚本不切关卡）'},
        },
    },
    'zh-TW': {
        'Menu': {
            'Hazeworld': {'name': '蒼霧世界', 'help': '蒼霧世界的日常任務'},
        },
        'Task': {
            'HazeworldMail': {'name': '郵件', 'help': '領取信箱裡的附件'},
            'HazeworldRoom': {'name': '指揮室', 'help': '收取指揮室資源，並處理遠征'},
            'HazeworldExercise': {'name': '演習', 'help': '用每天的演習券打完競技場'},
            'HazeworldFriend': {'name': '好友', 'help': '給所有好友按讚'},
            'HazeworldTask': {'name': '任務', 'help': '領取每日/每週/每月任務獎勵'},
            'HazeworldPass': {'name': '通行證', 'help': '領取通行證獎勵'},
            'HazeworldSupport': {'name': '支援角色',
                                 'help': '領取支援角色的友情幣（綠幣）'},
            'HazeworldCore': {'name': '核心製造',
                              'help': '在資源副本「核心製造」裡掃蕩核心材料，消耗體力'},
        },
        'HazeworldMail': {
            '_info': {'name': '郵件設定', 'help': ''},
            'ClaimAll': {'name': '領取全部郵件',
                         'help': '在郵件頁點擊「領取全部」，一次領完所有未讀郵件的附件'},
        },
        'HazeworldRoom': {
            '_info': {'name': '指揮室設定', 'help': ''},
            'CollectAll': {'name': '收取全部資源',
                           'help': '在指揮室點擊「全部收集」，收取已經產出的資源'},
            'Expedition': {'name': '處理遠征',
                           'help': '領取已經完成的遠征獎勵，並再次派遣'},
        },
        'HazeworldExercise': {
            '_info': {'name': '演習設定', 'help': ''},
            'ProxyBattle': {'name': '使用代理作戰',
                            'help': '用「代理作戰」一次掃蕩完當天所有演習券；關閉後一場場手動開戰，可以看到戰鬥過程'},
        },
        'HazeworldFriend': {
            '_info': {'name': '好友設定', 'help': ''},
            'LikeAll': {'name': '一鍵按讚',
                        'help': '在好友列表點擊「一鍵點讚」，給所有好友按讚'},
        },
        'HazeworldTask': {
            '_info': {'name': '任務設定', 'help': ''},
            'ClaimDaily': {'name': '領取每日任務獎勵',
                           'help': '切到「每日」頁籤，點擊「一鍵領取」'},
            'ClaimWeekly': {'name': '領取每週任務獎勵',
                            'help': '切到「每週」頁籤，點擊「一鍵領取」'},
            'ClaimMonthly': {'name': '領取每月任務獎勵',
                             'help': '切到「每月」頁籤，點擊「一鍵領取」'},
        },
        'HazeworldPass': {
            '_info': {'name': '通行證設定', 'help': ''},
            'ClaimAll': {'name': '領取全部通行證獎勵',
                         'help': '在通行證頁點擊「一鍵領取」'},
        },
        'HazeworldSupport': {
            '_info': {'name': '支援角色設定', 'help': ''},
            'ClaimAll': {'name': '領取友情幣',
                         'help': '在玩家檔案裡打開「支援角色」，逐個領取每個支援角色的友情幣（綠幣），每日上限 50000'},
        },
        'HazeworldCore': {
            '_info': {'name': '核心製造設定', 'help': ''},
            'Core': {'name': '核心種類',
                     'help': '要刷哪一類核心。只有選中的那一條左側有金色高亮',
                     'Life': '生命核心', 'Attack': '攻擊核心',
                     'Armor': '裝甲核心', 'Critical': '暴擊核心',
                     'Burst': '爆發核心'},
            'SweepCount': {'name': '掃蕩次數',
                           'help': '0 表示點「MAX」把體力一次花完；填正數則只掃蕩這麼多次。\n關卡用遊戲內當前選中的那一關，請先在遊戲裡選好（腳本不切關卡）'},
        },
    },
    'en-US': {
        'Menu': {
            'Hazeworld': {'name': 'Hazeworld', 'help': 'Daily routines of Hazeworld'},
        },
        'Task': {
            'HazeworldMail': {'name': 'Mail', 'help': 'Claim mail attachments'},
            'HazeworldRoom': {'name': 'Command room',
                              'help': 'Collect resources and handle expeditions'},
            'HazeworldExercise': {'name': 'Exercise',
                                  'help': 'Spend the daily exercise tickets in the arena'},
            'HazeworldFriend': {'name': 'Friend', 'help': 'Like all friends'},
            'HazeworldTask': {'name': 'Mission',
                              'help': 'Claim daily, weekly and monthly mission rewards'},
            'HazeworldPass': {'name': 'Battle pass', 'help': 'Claim battle pass rewards'},
            'HazeworldSupport': {'name': 'Support character',
                                 'help': 'Claim the friendship coins of support characters'},
            'HazeworldCore': {'name': 'Core material',
                              'help': 'Sweep core material stages in the resource dungeon, spends stamina'},
        },
        'HazeworldMail': {
            '_info': {'name': 'Mail settings', 'help': ''},
            'ClaimAll': {'name': 'Claim all mails',
                         'help': 'Press "Claim all" on the mail page to take every unread attachment'},
        },
        'HazeworldRoom': {
            '_info': {'name': 'Command room settings', 'help': ''},
            'CollectAll': {'name': 'Collect all resources',
                           'help': 'Press "Collect all" in the command room'},
            'Expedition': {'name': 'Handle expeditions',
                           'help': 'Claim finished expeditions and dispatch them again'},
        },
        'HazeworldExercise': {
            '_info': {'name': 'Exercise settings', 'help': ''},
            'ProxyBattle': {'name': 'Use proxy battle',
                            'help': 'Sweep every ticket of the day with "代理作战"; turn it off to fight one by one and watch the fights'},
        },
        'HazeworldFriend': {
            '_info': {'name': 'Friend settings', 'help': ''},
            'LikeAll': {'name': 'Like all friends',
                        'help': 'Press "Like all" in the friend list'},
        },
        'HazeworldTask': {
            '_info': {'name': 'Mission settings', 'help': ''},
            'ClaimDaily': {'name': 'Claim daily mission rewards',
                           'help': 'Switch to the "Daily" tab and press "Claim all"'},
            'ClaimWeekly': {'name': 'Claim weekly mission rewards',
                            'help': 'Switch to the "Weekly" tab and press "Claim all"'},
            'ClaimMonthly': {'name': 'Claim monthly mission rewards',
                             'help': 'Switch to the "Monthly" tab and press "Claim all"'},
        },
        'HazeworldPass': {
            '_info': {'name': 'Battle pass settings', 'help': ''},
            'ClaimAll': {'name': 'Claim all battle pass rewards',
                         'help': 'Press "Claim all" on the battle pass page'},
        },
        'HazeworldSupport': {
            '_info': {'name': 'Support character settings', 'help': ''},
            'ClaimAll': {'name': 'Claim friendship coins',
                         'help': 'Open "支援角色" in the player profile and claim every support character, 50000 per day at most'},
        },
        'HazeworldCore': {
            '_info': {'name': 'Core material settings', 'help': ''},
            'Core': {'name': 'Core type',
                     'help': 'Which core to farm. Only the selected entry has the gold bar on its left edge',
                     'Life': 'Life core', 'Attack': 'Attack core',
                     'Armor': 'Armor core', 'Critical': 'Critical core',
                     'Burst': 'Burst core'},
            'SweepCount': {'name': 'Sweep count',
                           'help': '0 presses "MAX" and spends every bit of stamina, a positive number sweeps exactly that many runs.\nThe stage is whatever the game has selected, pick it in game first, the script does not change it'},
        },
    },
    'ja-JP': {
        'Menu': {
            'Hazeworld': {'name': 'ヘイズワールド', 'help': 'ヘイズワールドの日課'},
        },
        'Task': {
            'HazeworldMail': {'name': 'メール', 'help': 'メールの添付を受け取る'},
            'HazeworldRoom': {'name': '司令室', 'help': '司令室の資源回収と遠征'},
            'HazeworldExercise': {'name': '演習', 'help': '毎日の演習券でアリーナを消化する'},
            'HazeworldFriend': {'name': 'フレンド', 'help': 'フレンド全員にいいね'},
            'HazeworldTask': {'name': 'ミッション',
                              'help': 'デイリー・ウィークリー・マンスリーミッションの報酬を受け取る'},
            'HazeworldPass': {'name': 'パス', 'help': 'パス報酬を受け取る'},
            'HazeworldSupport': {'name': '支援キャラ',
                                 'help': '支援キャラの友情コイン（緑コイン）を受け取る'},
            'HazeworldCore': {'name': 'コア製造',
                              'help': '資源ダンジョンの「コア製造」でコア素材を掃討する（スタミナ消費）'},
        },
        'HazeworldMail': {
            '_info': {'name': 'メール設定', 'help': ''},
            'ClaimAll': {'name': 'メールをすべて受け取る',
                         'help': 'メール画面で「すべて受け取る」を押す'},
        },
        'HazeworldRoom': {
            '_info': {'name': '司令室設定', 'help': ''},
            'CollectAll': {'name': '資源をすべて回収',
                           'help': '司令室で「すべて回収」を押す'},
            'Expedition': {'name': '遠征を処理',
                           'help': '完了した遠征の報酬を受け取り、再派遣する'},
        },
        'HazeworldExercise': {
            '_info': {'name': '演習設定', 'help': ''},
            'ProxyBattle': {'name': '代理作戦を使う',
                            'help': '「代理作戦」でその日の演習券をまとめて消化する。オフにすると 1 戦ずつ手動で戦い、戦闘を見られる'},
        },
        'HazeworldFriend': {
            '_info': {'name': 'フレンド設定', 'help': ''},
            'LikeAll': {'name': '一括いいね',
                        'help': 'フレンド一覧で「一括いいね」を押す'},
        },
        'HazeworldTask': {
            '_info': {'name': 'ミッション設定', 'help': ''},
            'ClaimDaily': {'name': 'デイリーミッション報酬を受け取る',
                           'help': '「デイリー」タブに切り替えて「すべて受け取る」を押す'},
            'ClaimWeekly': {'name': 'ウィークリーミッション報酬を受け取る',
                            'help': '「ウィークリー」タブに切り替えて「すべて受け取る」を押す'},
            'ClaimMonthly': {'name': 'マンスリーミッション報酬を受け取る',
                             'help': '「マンスリー」タブに切り替えて「すべて受け取る」を押す'},
        },
        'HazeworldPass': {
            '_info': {'name': 'パス設定', 'help': ''},
            'ClaimAll': {'name': 'パス報酬をすべて受け取る',
                         'help': 'パス画面で「すべて受け取る」を押す'},
        },
        'HazeworldSupport': {
            '_info': {'name': '支援キャラ設定', 'help': ''},
            'ClaimAll': {'name': '友情コインを受け取る',
                         'help': 'プレイヤープロフィールの「支援キャラ」を開き、各支援キャラの友情コインを受け取る（1日の上限は 50000）'},
        },
        'HazeworldCore': {
            '_info': {'name': 'コア製造設定', 'help': ''},
            'Core': {'name': 'コアの種類',
                     'help': 'どのコアを周回するか。選択中の項目だけ左端が金色に光る',
                     'Life': '生命コア', 'Attack': '攻撃コア',
                     'Armor': '装甲コア', 'Critical': '会心コア',
                     'Burst': '爆発コア'},
            'SweepCount': {'name': '掃討回数',
                           'help': '0 は「MAX」を押してスタミナを使い切る。正の数ならその回数だけ掃討する。\nステージはゲーム内で選択中のものを使う（スクリプトは切り替えない）'},
        },
    },
}


def main():
    for lang, groups in TRANSLATIONS.items():
        file = filepath_i18n(lang)
        with open(file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        for group, entries in groups.items():
            data.setdefault(group, {})
            for key, words in entries.items():
                data[group].setdefault(key, {})
                data[group][key].update(words)
        with open(file, 'w', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
        print(f'filled {lang}')


if __name__ == '__main__':
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
    main()
