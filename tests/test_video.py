"""影片合成的純邏輯測試:SRT 字幕格式、時間軸累積(不跑 ffmpeg)。"""

import pytest

from pmb.video.assemble import build_srt, segment_timeline


def test_build_srt_formats_cues_with_ms():
    srt = build_srt([("你好", 0.0, 2.5), ("世界", 2.5, 1.5)])
    assert "00:00:00,000 --> 00:00:02,500" in srt
    assert "你好" in srt
    assert "00:00:02,500 --> 00:00:04,000" in srt
    assert "世界" in srt


def test_segment_timeline_accumulates_actual_durations():
    # 給每段「實際配音長度」,回傳累積起點 + 總長
    starts, total = segment_timeline([3.0, 4.5, 2.5])
    assert starts == pytest.approx([0.0, 3.0, 7.5])
    assert total == pytest.approx(10.0)
