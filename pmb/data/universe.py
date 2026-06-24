"""PMB 追蹤的標的與 FRED 序列清單(單一真實來源,DRY)。

規格 §4:指數期貨 + 現貨、VIX、10Y、美元、槓桿載具;FRED 總經序列;
sector ETF 作為市場廣度的代理籃子。
"""

from __future__ import annotations

import datetime as dt

# (ticker, 顯示名稱)
INDEX_FUTURES: list[tuple[str, str]] = [
    ("ES=F", "S&P 500 期貨"),
    ("NQ=F", "Nasdaq 100 期貨"),
    ("YM=F", "道瓊期貨"),
    ("RTY=F", "Russell 2000 期貨"),
]

INDEX_CASH: list[tuple[str, str]] = [
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq Composite"),
    ("^DJI", "道瓊工業指數"),
    ("^RUT", "Russell 2000"),
]

VIX: tuple[str, str] = ("^VIX", "VIX 波動率指數")
TREASURY_10Y: tuple[str, str] = ("^TNX", "美國 10 年期公債殖利率指數")
DOLLAR_INDEX: tuple[str, str] = ("DX-Y.NYB", "美元指數 (DXY)")

# 槓桿 / 反向載具——資訊與風險教育用,非可跟單策略
LEVERAGE: list[tuple[str, str]] = [
    ("UPRO", "3x 做多 S&P 500"),
    ("SPXL", "3x 做多 S&P 500"),
    ("TQQQ", "3x 做多 Nasdaq 100"),
    ("UDOW", "3x 做多道瓊"),
    ("TNA", "3x 做多 Russell 2000"),
    ("SOXL", "3x 做多費城半導體"),
    ("TMF", "3x 做多 20年+ 公債"),
]

# 衍生指標用:股債相關(股票端 vs 債券端)
STOCK_PROXY: str = "^GSPC"
BOND_PROXY: str = "TLT"

# 漲幅集中度:用此 ETF 的前 N 大持股(權重)近似 S&P 500 的成分股貢獻
CONCENTRATION_BENCHMARK: tuple[str, str] = ("SPY", "S&P 500")

# 市場廣度代理籃子:11 檔 SPDR 類股 ETF
SECTOR_ETFS: list[str] = [
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLRE", "XLU", "XLC",
]

SECTOR_LABELS: dict[str, str] = {
    "XLK": "科技", "XLF": "金融", "XLE": "能源", "XLV": "醫療", "XLY": "非必需消費",
    "XLP": "必需消費", "XLI": "工業", "XLB": "原物料", "XLRE": "房地產",
    "XLU": "公用事業", "XLC": "通訊服務",
}

# 海外 / 亞歐股(隔夜對照圖):亞洲收盤 + 歐股盤中,作為今日盤前外溢的領先訊號。
# yfinance 指數代碼;單檔失敗會在 get_quotes 跳過,不影響其餘。
GLOBAL_EQUITY: list[tuple[str, str]] = [
    ("^KS11", "南韓 KOSPI"),
    ("^N225", "日經 225"),
    ("^TWII", "台灣加權"),
    ("^HSI", "香港恆生"),
    ("000001.SS", "上海綜合"),
    ("^STOXX50E", "歐洲 STOXX50"),
    ("^GDAXI", "德國 DAX"),
    ("^FTSE", "英國 FTSE"),
]

# Fed 政策路徑 baseline:現行政策利率(FRED 聯邦基金有效利率)
POLICY_RATE_SERIES: tuple[str, str] = ("FEDFUNDS", "聯邦基金有效利率")

# Fed 路徑「曲線保底」用的短端到期點:(FRED series_id, 顯示標籤, 月數)
FED_PATH_CURVE_SERIES: list[tuple[str, str, int]] = [
    ("DGS3MO", "3個月", 3),
    ("DGS6MO", "6個月", 6),
    ("DGS1", "1年", 12),
    ("DGS2", "2年", 24),
]

# Fed funds 期貨月份代碼(CME 慣例)
_FUTURES_MONTH_CODE: dict[int, str] = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}


def fed_funds_future_ticker(year: int, month: int) -> str:
    """組 Yahoo Finance 上的 Fed funds 期貨合約代碼:``ZQ{月碼}{YY}.CBT``。"""
    return f"ZQ{_FUTURES_MONTH_CODE[month]}{year % 100:02d}.CBT"


# FOMC 會議日(排程事實,非市場數字)——Fed 路徑期貨模式用來對應各次會議。
# 2026 年八次例會(以會議第二天/決議日為準)。
FOMC_MEETINGS: list[tuple[dt.date, str]] = [
    (dt.date(2026, 1, 28), "1月"),
    (dt.date(2026, 3, 18), "3月"),
    (dt.date(2026, 4, 29), "4月"),
    (dt.date(2026, 6, 17), "6月"),
    (dt.date(2026, 7, 29), "7月"),
    (dt.date(2026, 9, 16), "9月"),
    (dt.date(2026, 10, 28), "10月"),
    (dt.date(2026, 12, 9), "12月"),
]

# econ_print 圖表的預設總經序列:(FRED series_id, 顯示標籤)
ECON_PRINT_SERIES: tuple[str, str] = ("UNRATE", "失業率 (%)")

# 殖利率曲線到期點:(FRED series_id, 顯示標籤, 月數)
YIELD_CURVE_SERIES: list[tuple[str, str, int]] = [
    ("DGS3MO", "3M", 3),
    ("DGS2", "2Y", 24),
    ("DGS5", "5Y", 60),
    ("DGS10", "10Y", 120),
    ("DGS30", "30Y", 360),
]

# (series_id, 顯示名稱, 單位)
FRED_SERIES: list[tuple[str, str, str | None]] = [
    ("DGS10", "10 年期公債殖利率", "percent"),
    ("DGS2", "2 年期公債殖利率", "percent"),
    ("T10Y2Y", "10年-2年利差", "percent"),
    ("FEDFUNDS", "聯邦基金有效利率", "percent"),
    ("CPIAUCSL", "CPI 消費者物價指數", "index"),
    ("PCEPI", "PCE 物價指數", "index"),
    ("UNRATE", "失業率", "percent"),
    ("PAYEMS", "非農就業人數", "thousands"),
    ("GDP", "國內生產毛額", "billions"),
]
