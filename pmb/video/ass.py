"""畫面版面常數與 ASS 疊層共用元件(樣式模板、時間格式、角標/CTA)。

版面避開 YouTube Shorts 播放器 UI(見 ``layout_safe_zone``):底部約 400px、右側約 170px
不放文字。從 video.assemble 拆出(v4),供各段型 renderer 共用。
"""

from __future__ import annotations

import re

from pmb.video.captions import wrap_caption

# 直式短影片畫布(9:16)
WIDTH, HEIGHT = 1080, 1920
BG_HEX = "0D1B2A"  # 與 charts.library._CANVAS 一致
GOLD_HEX = "FFD166"  # 品牌金(標題/進度條/字幕掃色)
WHITE_HEX = "FFFFFF"  # 色塊上的內文白

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
STAT_LABEL_TOP = 1122  # 48px
STAT_TOP = 1172  # 132px,約到 1340;字幕頂緣約 1365
SUB_MARGIN_V = BOTTOM_UI  # 字幕底緣 = 1520;兩行 64px 頂緣約 1365,不蓋 callout
CTA_MARGIN_V = 430
# 字卡:大標以「可見區」(0 ~ 1920-BOTTOM_UI)的中心偏上為錨點置中;kicker 緊貼大標上方
CARD_CENTER_Y = 820
CARD_FONT = 136
CARD_LINE_H = int(CARD_FONT * 1.25)
CARD_MAX_UNITS = (WIDTH - 2 * 60) / CARD_FONT  # 每行寬度 ≈7 字(中文 1 單位 = 一個字寬)
KICKER_GAP = 96  # kicker 基線到大標頂緣的距離
CTA_SEC = 3.0  # 片尾 CTA 出現秒數


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
# 顏色為 ASS 的 &HAABBGGRR。sub 的 Primary=金(唸過)、Secondary=白(未唸);
# 版面座標全部引用上面的常數,改版面只改常數。
ASS_TEMPLATE = "\n".join(
    [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        _STYLE_FORMAT,
        # 字幕:底部置中,避開底部 UI 與右側按讚欄
        f"Style: sub,{{font}},64,&H0066D1FF,&H00FFFFFF,&H00201810,&H78000000,1,1,5,1,2,"
        f"60,{RIGHT_UI},{SUB_MARGIN_V}",
        # 主題標題:頂部置中
        f"Style: title,{{font}},92,&H0066D1FF,&H00FFFFFF,&H00201810,&H00000000,1,1,3,0,8,"
        f"40,40,{TITLE_TOP}",
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
        "Style: free,{font},60,&H00FFFFFF,&H00FFFFFF,&H00201810,&H00000000,1,1,0,0,7,0,0,0",
        "",
        "[Events]",
        _EVENT_FORMAT,
        "{events}",
        "",
    ]
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
    start: float, end: float, x: int, y: int, path: str, color: str, *, move_px: int = 24
) -> str:
    """色塊/圖示事件(layer 0,在文字下面):從下方滑入 + 淡入。"""
    tags = f"{{\\an7{_slide_in(x, y, move_px)}\\bord0\\shad0\\1c{color}\\p1}}"
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
    move_px: int = 24,
) -> str:
    """文字事件(layer 1,蓋在色塊上):``align`` 是 ASS 數字鍵盤對齊(7 左上、9 右上、5 置中)。"""
    tags = f"{{\\an{align}{_slide_in(x, y, move_px)}\\fs{size}\\1c{color}\\bord0\\shad0}}"
    body = _escape_text(text)
    return f"Dialogue: 1,{ass_time(start)},{ass_time(end)},free,,0,0,0,,{tags}{body}"
