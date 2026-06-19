"""PMB 設定層(pydantic-settings)。

從 ``.env`` + 環境變數讀取設定。密鑰(FRED / Anthropic 等)絕不寫死、不入庫。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # 密鑰
    fred_api_key: str | None = None
    anthropic_api_key: str | None = None

    # YouTube 上傳(Phase 5,僅 --approve 實際上傳時需要)
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    youtube_refresh_token: str | None = None

    # 路徑
    artifacts_dir: Path = Path("artifacts")
    state_dir: Path = Path("state")
    prompt_path: Path = Path("prompts/daily_research.md")

    # 資料層參數
    history_period: str = "6mo"

    # 配音:短影片用快語速,高資訊密度
    tts_rate: str = "+35%"

    # 短影片開頭 / 結尾 slogan
    slogan_intro: str = "30 秒看懂今天美股盤前"
    slogan_outro: str = "每天盤前見,記得追蹤;非投資建議"

    def ensure_dirs(self) -> None:
        """確保 runtime 產出目錄存在。"""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """全應用共用的設定單例。"""
    return Settings()
