"""畫面版面常數與 ASS 疊層共用元件(樣式模板、時間格式、角標/CTA)。

版面避開 YouTube Shorts 播放器 UI(見 ``layout_safe_zone``):底部約 400px、右側約 170px
不放文字。從 video.assemble 拆出(v4),供各段型 renderer 共用。
"""

from __future__ import annotations

import re
from typing import NamedTuple

from pmb.video.captions import wrap_caption

# 直式短影片畫布(9:16)
WIDTH, HEIGHT = 1080, 1920
FPS = 25  # 全片影格率(ffmpeg 輸出與逐幀 ASS 動畫共用)
BG_HEX = "0D1B2A"  # 畫布色,與 charts.library._CANVAS 一致
GOLD_HEX = "FFD166"  # 品牌金(標題/進度條/字幕掃色)
WHITE_HEX = "FFFFFF"  # 色塊上的內文白
MUTED_HEX = "8FA3B8"  # 次要文字的灰藍(大數字的 label、對帳的 ask)

# Shorts 播放器 UI 遮蔽區(實機量測的保守值):底部標題/頻道/描述列、右側按讚/留言/分享欄。
# 所有文字都不得落進去,否則觀眾在 app 裡根本看不到。
BOTTOM_UI = 400
RIGHT_UI = 170
# 版面(由上而下,單位 px):角標(品牌·日期)→ 主題標題 → 圖表 → 大數字 callout → 字幕 → UI 遮蔽區
BADGE_TOP = 100
TITLE_TOP = 150  # 標題 92px,約到 245
CHART_BAND_TOP = 270
CHART_BOX_W = 1040
CHART_BOX_H = 850  # 框底 = 270+850 = 1120,下方留給 callout
CHART_BOX_BOTTOM = CHART_BAND_TOP + CHART_BOX_H  # 1120：有橫幅時框頂下移、框底不動
STAT_LABEL_TOP = 1122  # 48px
STAT_TOP = 1172  # 132px,約到 1340;字幕頂緣約 1365
SUB_MARGIN_V = BOTTOM_UI  # 字幕底緣 = 1520;兩行 64px 頂緣約 1365,不蓋 callout
CTA_MARGIN_V = 430
# 內容帶:對話泡泡、對帳列這類「少量就該置中」的版面共用。上緣 = 圖表帶上緣(標題約 150–245
# 之下),下緣 1320 在字幕頂緣(約 1365)之上;帶內任何東西都落在底部 UI 遮蔽區(1520)之上。
CONTENT_TOP = CHART_BAND_TOP
CONTENT_BOTTOM = 1320
# 字卡:大標以「可見區」(0 ~ 1920-BOTTOM_UI)的中心偏上為錨點置中;kicker 緊貼大標上方
CARD_CENTER_Y = 820
CARD_FONT = 136
CARD_LINE_H = int(CARD_FONT * 1.25)
CARD_MAX_UNITS = (WIDTH - 2 * 60) / CARD_FONT  # 每行寬度 ≈7 字(中文 1 單位 = 一個字寬)
KICKER_GAP = 96  # kicker 基線到大標頂緣的距離
CTA_SEC = 3.0  # 片尾 CTA 出現秒數
# 置中文字(口號轉場、全屏大數字):錨點 x=540、寬度上限 740 → 540 ± 370,右緣 910 不碰按讚欄
CENTER_X = WIDTH // 2
CENTERED_TEXT_MAX_W = 740

# 今日標題橫幅（金底深字的圓角框，疊在每個中段畫面頂端，讓任何一格被截成封面都讀得出主題）。
# 框：x=60、y=110、寬 960、高 216（兩行 88px + 上下各 20px 內距，底緣 326）；一行標題在框內置中。
BANNER_TOP = 110
BANNER_X = 60
BANNER_W = 960
BANNER_PAD = 20
BANNER_RADIUS = 28
BANNER_SIZES = (88, 76, 66)  # 標題字級，由大到小試
BANNER_MAX_LINES = 2
BANNER_H = BANNER_MAX_LINES * BANNER_SIZES[0] + 2 * BANNER_PAD  # 216：框高固定，不隨行數變
# 有橫幅的段：段標題縮小並下移到橫幅底緣（326）之下，內容帶/圖表帶上緣也跟著下移
BANNERED_TITLE_TOP = 344  # 標題 60px，約到 404
BANNERED_CONTENT_TOP = 424


class TopLayout(NamedTuple):
    """畫面上半部的版面：段標題用的樣式、內容帶/圖表帶上緣。"""

    title_style: str
    content_top: int

    @property
    def chart_box_h(self) -> int:
        """圖表框高：框底固定在 ``CHART_BOX_BOTTOM``，上緣下移就變矮。"""
        return CHART_BOX_BOTTOM - self.content_top


PLAIN_TOP = TopLayout("title", CHART_BAND_TOP)
BANNERED_TOP = TopLayout("title_b", BANNERED_CONTENT_TOP)


def top_layout(banner: bool) -> TopLayout:
    """這段有橫幅就用下移的版面，否則維持原版面。"""
    return BANNERED_TOP if banner else PLAIN_TOP


def center_block_top(block_height: int, top: int = CONTENT_TOP) -> int:
    """高 ``block_height`` 的區塊在內容帶（``top``..``CONTENT_BOTTOM``）內上下置中，
    回傳區塊頂緣；``top`` 是內容帶上緣（有橫幅時是 ``BANNERED_CONTENT_TOP``）。
    區塊比內容帶還高就貼著上緣(寧可往下溢出,也不往上蓋標題)。"""
    return top + max(0, (CONTENT_BOTTOM - top - block_height) // 2)


def layout_safe_zone() -> dict[str, int]:
    """回傳版面安全區參數,供測試/文件確認文字都避開 Shorts 播放器 UI。"""
    return {
        "bottom_ui": BOTTOM_UI,
        "right_ui": RIGHT_UI,
        "sub_margin_v": SUB_MARGIN_V,
        "sub_margin_r": RIGHT_UI,
    }

# 用 .ass 並指定 PlayResY=1920,字級/邊界都以實際像素計。字幕在底(Alignment=2)、
# 標題在頂(Alignment=8),都不蓋到中間的圖表。含 SecondaryColour 供卡拉OK掃色:
# 未唸到 = Secondary(白),唸過 = Primary(金)。
_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV"
)
_EVENT_FORMAT = (
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
)
# 自由定位樣式：新段型的色塊/圖示/文字（以及 16:9 封面）都用它，位置與字級由事件的 override 決定。
# ``{font}`` 留給 ``ass_template`` 的產物用 ``.format`` 填字型。
FREE_STYLE = "Style: free,{font},60,&H00FFFFFF,&H00FFFFFF,&H00201810,&H00000000,1,1,0,0,7,0,0,0"


def ass_template(width: int, height: int, styles: list[str]) -> str:
    """ASS 模板（``{font}``、``{events}`` 兩個佔位留給 ``.format``）：``PlayRes`` 取 ``width``×
    ``height``，樣式區放 ``styles``（每個元素一行 ``Style: …``）。影片 9:16 的 ``ASS_TEMPLATE``
    與 16:9 封面的 ``cover.COVER_ASS_TEMPLATE`` 共用這個骨架，``PlayRes`` 之外的檔頭一致。"""
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            _STYLE_FORMAT,
            *styles,
            "",
            "[Events]",
            _EVENT_FORMAT,
            "{events}",
            "",
        ]
    )


# 顏色為 ASS 的 &HAABBGGRR。sub 的 Primary=金(唸過)、Secondary=白(未唸);
# 版面座標全部引用上面的常數,改版面只改常數。
ASS_TEMPLATE = ass_template(
    WIDTH,
    HEIGHT,
    [
        # 字幕:底部置中,避開底部 UI 與右側按讚欄
        f"Style: sub,{{font}},64,&H0066D1FF,&H00FFFFFF,&H00201810,&H78000000,1,1,5,1,2,"
        f"60,{RIGHT_UI},{SUB_MARGIN_V}",
        # 主題標題:頂部置中
        f"Style: title,{{font}},92,&H0066D1FF,&H00FFFFFF,&H00201810,&H00000000,1,1,3,0,8,"
        f"40,40,{TITLE_TOP}",
        # 有橫幅時的段標題：同 title，字級縮到 60、下移到橫幅底緣之下
        f"Style: title_b,{{font}},60,&H0066D1FF,&H00FFFFFF,&H00201810,&H00000000,1,1,3,0,8,"
        f"40,40,{BANNERED_TITLE_TOP}",
        # 字卡大標與 kicker:位置由事件的 \\pos 決定(依行數對可見區置中),樣式只管字型
        f"Style: card,{{font}},{CARD_FONT},&H00FFFFFF,&H00FFFFFF,&H40000000,&H00000000,1,1,2,0,5,"
        "80,80,0",
        "Style: kicker,{font},52,&H0066D1FF,&H00FFFFFF,&H40000000,&H00000000,1,1,2,0,5,80,80,0",
        # 大數字 callout:左對齊,圖表下方;右側留 UI 欄
        f"Style: stat,{{font}},132,&H0066D1FF,&H00FFFFFF,&H00201810,&H00000000,1,1,3,0,7,"
        f"70,{RIGHT_UI},{STAT_TOP}",
        f"Style: statlabel,{{font}},48,&H00E6EDF5,&H00FFFFFF,&H00201810,&H00000000,1,1,2,0,7,"
        f"70,{RIGHT_UI},{STAT_LABEL_TOP}",
        # 品牌·日期角標:最頂,小而淡
        f"Style: badge,{{font}},36,&H00D9C58F,&H00FFFFFF,&H00201810,&H00000000,0,1,2,0,8,"
        f"40,40,{BADGE_TOP}",
        # 片尾 CTA:底部安全區內
        f"Style: cta,{{font}},48,&H00FFFFFF,&H00FFFFFF,&H00201810,&H78000000,1,1,4,0,2,"
        f"60,{RIGHT_UI},{CTA_MARGIN_V}",
        # 自由定位:新段型的色塊/圖示/文字都用它,位置與字級由事件的 override 決定
        FREE_STYLE,
    ],
)

# 文字 pop-in:淡入 + 由 82% 放大到 100%(靜止字卡是滑走的主因之一)
POP_IN = "{\\fad(120,0)\\fscx82\\fscy82\\t(0,240,\\fscx100\\fscy100)}"
FADE_TAG = "{\\fad(160,0)}"


def ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def full_event(style: str, seg_duration: float, text: str) -> str:
    return f"Dialogue: 0,0:00:00.00,{ass_time(seg_duration)},{style},,0,0,0,,{text}"


def common_events(
    seg_duration: float, *, badge: str | None, cta: str | None
) -> list[str]:
    """所有段共用的疊層:品牌·日期角標(全段)+ 片尾 CTA(最後 ``CTA_SEC`` 秒)。"""
    events: list[str] = []
    if badge:
        events.append(full_event("badge", seg_duration, badge))
    if cta:
        start = max(seg_duration - CTA_SEC, 0.0)
        events.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(seg_duration)},cta,,0,0,0,,"
            f"{FADE_TAG}{cta}"
        )
    return events


def build_ass(
    sentence: str, duration: float, *, title: str | None = None, font: str = "Noto Sans CJK TC"
) -> str:
    """組單句用的 .ass(底部字幕 + 選配頂部標題,皆全長顯示)。段級請用 build_segment_ass。"""
    end = ass_time(duration)
    events = [f"Dialogue: 0,0:00:00.00,{end},sub,,0,0,0,,{wrap_caption(sentence)}"]
    if title:
        events.append(f"Dialogue: 0,0:00:00.00,{end},title,,0,0,0,,{title}")
    return ASS_TEMPLATE.format(font=font, events="\n".join(events))


def ass_color(hex_rgb: str) -> str:
    """``#RRGGBB`` → ASS 的 ``&HBBGGRR&``。"""
    h = hex_rgb.lstrip("#").upper()
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&"


def rounded_rect(w: int, h: int, r: int) -> str:
    """圓角矩形的 ASS 繪圖路徑(左上為原點)。"""
    r = max(0, min(r, w // 2, h // 2))
    return (
        f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
        f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0"
    )


def polygon(points: list[tuple[float, float]], size: float) -> str:
    """0–1 正規化座標的多邊形 → 邊長 ``size`` 的 ASS 繪圖路徑(✓/✗ 圖示用)。"""
    pts = [(round(x * size), round(y * size)) for x, y in points]
    (x0, y0), rest = pts[0], pts[1:]
    return f"m {x0} {y0} l " + " ".join(f"{x} {y}" for x, y in rest)


def _escape_text(text: str) -> str:
    """ASS 文字轉義:``{``/``}`` 會開關 override 區塊,先換成全形;真換行會把 Dialogue 行切斷,
    改成 ASS 的換行 ``\\N``。呼叫端自己放的 ``\\N`` 序列不動。"""
    text = text.replace("{", "｛").replace("}", "｝")
    return re.sub(r"\r\n|\r|\n", r"\\N", text)


def _slide_in(x: int, y: int, move_px: int) -> str:
    return f"\\move({x},{y + move_px},{x},{y},0,160)\\fad(120,0)"


def shape_event(
    start: float, end: float, x: int, y: int, path: str, color: str, *, move_px: int | None = 24
) -> str:
    """色塊/圖示事件(layer 0,在文字下面):預設從下方滑入 + 淡入；``move_px=None`` 是靜態
    定位（``\\pos``，不滑不淡，與 ``text_event`` 一致，橫幅這類常駐色塊用）。"""
    place = f"\\pos({x},{y})" if move_px is None else _slide_in(x, y, move_px)
    tags = f"{{\\an7{place}\\bord0\\shad0\\1c{color}\\p1}}"
    return f"Dialogue: 0,{ass_time(start)},{ass_time(end)},free,,0,0,0,,{tags}{path}{{\\p0}}"


def text_event(
    start: float,
    end: float,
    x: int,
    y: int,
    text: str,
    *,
    size: int,
    color: str,
    align: int = 7,
    move_px: int | None = 24,
    effect: str = "",
) -> str:
    """文字事件(layer 1,蓋在色塊上):``align`` 是 ASS 數字鍵盤對齊(7 左上、9 右上、5 置中)。

    預設從下方滑入 ``move_px`` + 淡入;``move_px=None`` 是靜態定位(``\\pos``,不滑不淡,
    逐幀換字的大數字用)。``effect`` 是接在定位後的額外 override 區塊(如 ``POP_IN``)。
    文字一律經 ``_escape_text`` 轉義。"""
    place = f"\\pos({x},{y})" if move_px is None else _slide_in(x, y, move_px)
    tags = f"{{\\an{align}{place}\\fs{size}\\1c{color}\\bord0\\shad0}}"
    body = _escape_text(text)
    return f"Dialogue: 1,{ass_time(start)},{ass_time(end)},free,,0,0,0,,{tags}{effect}{body}"
