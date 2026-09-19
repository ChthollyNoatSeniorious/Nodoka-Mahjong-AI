action-chii = 吃
action-chiicut = 吃、打
action-discard = 打
action-kan = 槓
action-skip = 跳過
action-pon = 碰
action-poncut = 碰、打
action-riichi = 立直
action-ron = 和
action-ryuukyoku = 流局
action-tsumo = 自摸

donate-header = 打賞

end-status-ron = {$seat}{"\u00a0"}榮和 {$delta}
end-status-ryuukyoku = {action-ryuukyoku}
end-status-tsumo = {$seat}{"\u00a0"}{action-tsumo} {$delta}

final-ranking-probs-at-the-start-of-kyoku = {$kyoku}開局時的最終順位概率

game-summary-header = 目錄

help-header = 幫助

kyoku =
    {$bakaze ->
        [East] 東
        [South] 南
        [West] 西
        [North] 北
        *[other] {$bakaze}
    }{$kyoku-in-bakaze}局{$honba ->
        [0] {""}
        *[other] {" "}{$honba}本场
    }

metadata-engine-header = AI 引擎
metadata-game-length-header = 對局長度
metadata-game-length-value = {$length ->
    [Hanchan] 半莊
    [Tonpuu] 東風
    *[other] {$length}
}
metadata-generated-at-header = 生成時間
metadata-header = 元資料
metadata-loading-time-header = 載入用時
metadata-log-id-header = 牌譜 ID
metadata-match-rate-header = AI 一致率
metadata-mjai-reviewer-version-header = mjai-reviewer 版本
metadata-player-id-header = 玩家 ID
metadata-review-time-header = 檢討用時

panel-expand = 展開:
panel-expand-all = 全部
panel-expand-diff-only = 僅差異項
panel-expand-none = 無
panel-layout = 佈局:
panel-layout-horizontal = 水平
panel-layout-vertical = 垂直
panel-save-this-page = 儲存本頁面

place-percentage = {$rank}位率 (%)

player = 玩家

replay-viewer = 牌譜回放

score-header = 點數

tehai-cuts = {$player}打
tehai-draw = 自摸
tehai-kans = {$player}加槓
tehai-riichi = 並宣告立直

tenhou-net-6-json-log-header = tenhou.net/6 JSON 牌譜

tenhou-net-6-paste-instruction-before-link = 可貼到{" "}
tenhou-net-6-paste-instruction-after-link = {" "}的「EDIT AS TEXT」选项裡。

title = 牌譜檢討

turn = {$junme}巡 (餘{$tiles-left})
turn-info-furiten = (振聽)
turn-info-shanten = {$shanten}向聽
turn-info-tenpai = 聽牌

seat-self = 自家
seat-kamicha = 上家
seat-shimocha = 下家
seat-toimen = 對家
