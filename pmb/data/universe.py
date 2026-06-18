"""PMB 追蹤的標的與 FRED 序列清單(單一真實來源,DRY)。

規格 §4:指數期貨 + 現貨、VIX、10Y、美元、槓桿載具;FRED 總經序列;
sector ETF 作為市場廣度的代理籃子。
"""

from __future__ import annotations

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

# 市場廣度代理籃子:11 檔 SPDR 類股 ETF
SECTOR_ETFS: list[str] = [
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLRE", "XLU", "XLC",
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
