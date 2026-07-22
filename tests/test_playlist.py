"""播放清單補加測試:去重(已在清單內跳過)、逐支失敗不擋其餘(不打網路,注入假 client)。"""

import pmb.publish.youtube as yt


class _FakePlaylistItems:
    def __init__(self, existing, fail_on=None):
        self._existing = list(existing)
        self._fail_on = fail_on or set()
        self.inserted = []

    def list(self, **kwargs):
        page = {"items": [{"contentDetails": {"videoId": v}} for v in self._existing]}
        return _Exec(page)

    def insert(self, **kwargs):
        vid = kwargs["body"]["snippet"]["resourceId"]["videoId"]
        if vid in self._fail_on:
            return _Exec(None, error=RuntimeError("403 insufficient permissions"))
        self.inserted.append(vid)
        return _Exec({"id": "item"})


class _Exec:
    def __init__(self, resp, error=None):
        self._resp = resp
        self._error = error

    def execute(self):
        if self._error:
            raise self._error
        return self._resp


class _FakeYouTube:
    def __init__(self, existing, fail_on=None):
        self._pi = _FakePlaylistItems(existing, fail_on)

    def playlistItems(self):
        return self._pi


def test_backfill_skips_existing_and_adds_missing(monkeypatch):
    fake = _FakeYouTube(existing=["vid_old"])
    monkeypatch.setattr(yt, "_build_youtube", lambda settings: fake)

    result = yt.add_videos_to_playlist(
        ["vid_old", "vid_new1", "vid_new2"], "PL123", settings=object()
    )
    assert result["added"] == ["vid_new1", "vid_new2"]
    assert result["skipped"] == ["vid_old"]
    assert result["failed"] == []
    assert fake._pi.inserted == ["vid_new1", "vid_new2"]


def test_backfill_reports_failures_without_stopping(monkeypatch):
    fake = _FakeYouTube(existing=[], fail_on={"vid_bad"})
    monkeypatch.setattr(yt, "_build_youtube", lambda settings: fake)

    result = yt.add_videos_to_playlist(["vid_a", "vid_bad", "vid_b"], "PL123", settings=object())
    assert result["added"] == ["vid_a", "vid_b"]  # 壞的那支不擋其餘
    assert len(result["failed"]) == 1
    assert result["failed"][0][0] == "vid_bad"


def test_list_playlist_video_ids_paginates(monkeypatch):
    class _PagedPI:
        def __init__(self):
            self.calls = 0

        def list(self, **kwargs):
            self.calls += 1
            if kwargs.get("pageToken") is None:
                return _Exec({"items": [{"contentDetails": {"videoId": "a"}}],
                              "nextPageToken": "p2"})
            return _Exec({"items": [{"contentDetails": {"videoId": "b"}}]})

    class _YT:
        def __init__(self):
            self._pi = _PagedPI()

        def playlistItems(self):
            return self._pi

    ids = yt.list_playlist_video_ids(_YT(), "PL123")
    assert ids == {"a", "b"}
