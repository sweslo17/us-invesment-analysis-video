"""程序化轉場音效測試。"""

import wave

from pmb.audio.sfx import generate_sting, resolve_sting_sfx


def test_generate_sting_writes_short_mono_wav(tmp_path):
    out = generate_sting(tmp_path / "s.wav")
    with wave.open(str(out)) as fh:
        assert fh.getnchannels() == 1 and fh.getframerate() == 44100
        assert 0.4 < fh.getnframes() / 44100 < 0.7


def test_user_sfx_file_takes_priority(tmp_path):
    sfx_dir = tmp_path / "sfx"
    sfx_dir.mkdir()
    (sfx_dir / "sting.mp3").write_bytes(b"fake")
    assert resolve_sting_sfx(sfx_dir, tmp_path).name == "sting.mp3"
    assert resolve_sting_sfx(tmp_path / "none", tmp_path).name == "sting_sfx.wav"
