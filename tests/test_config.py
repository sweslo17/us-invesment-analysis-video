"""設定層測試(pydantic-settings):env 對應與目錄建立。"""

from pmb.config import Settings


def test_settings_reads_fred_api_key_from_env(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test-key-123")
    settings = Settings(_env_file=None)
    assert settings.fred_api_key == "test-key-123"


def test_settings_fred_api_key_defaults_to_none(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    settings = Settings(_env_file=None)
    assert settings.fred_api_key is None


def test_ensure_dirs_creates_artifacts_and_state(tmp_path):
    settings = Settings(
        _env_file=None,
        artifacts_dir=tmp_path / "artifacts",
        state_dir=tmp_path / "state",
    )
    settings.ensure_dirs()
    assert (tmp_path / "artifacts").is_dir()
    assert (tmp_path / "state").is_dir()


def test_slogan_defaults_use_fullwidth_punctuation(monkeypatch):
    # 開場口號轉場與收尾口號會上畫面、進 TTS:預設值本身就要是全形標點
    monkeypatch.delenv("SLOGAN_INTRO", raising=False)
    monkeypatch.delenv("SLOGAN_OUTRO", raising=False)
    settings = Settings(_env_file=None)
    assert settings.slogan_intro == "美股早發車，發車！"
    assert settings.slogan_outro == "以上非投資建議，明天盤前見。"
