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

    # 路徑
    artifacts_dir: Path = Path("artifacts")
    state_dir: Path = Path("state")
    prompt_path: Path = Path("prompts/daily_research.md")

    # 資料層參數
    history_period: str = "6mo"

    def ensure_dirs(self) -> None:
        """確保 runtime 產出目錄存在。"""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """全應用共用的設定單例。"""
    return Settings()
