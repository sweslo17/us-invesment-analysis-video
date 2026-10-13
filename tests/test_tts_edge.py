"""edge-tts endpoint 墊片測試:v1 token 的 edge-tts 改走 api.msedgeservices.com(不連網)。"""

import edge_tts.communicate as comm
from edge_tts.constants import TRUSTED_CLIENT_TOKEN

from pmb.tts.edge import MSEDGE_WSS_BASE, ensure_working_endpoint

LEGACY_WSS = (
    "wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1"
    f"?TrustedClientToken={TRUSTED_CLIENT_TOKEN}"
)


def test_v1_token_switches_to_msedgeservices_host(monkeypatch):
    monkeypatch.setattr(comm, "WSS_URL", LEGACY_WSS)
    monkeypatch.setattr(comm, "SEC_MS_GEC_VERSION", "1-143.0.3650.75")

    ensure_working_endpoint()

    assert comm.WSS_URL == f"{MSEDGE_WSS_BASE}?Ocp-Apim-Subscription-Key={TRUSTED_CLIENT_TOKEN}"


def test_idempotent(monkeypatch):
    monkeypatch.setattr(comm, "WSS_URL", LEGACY_WSS)
    monkeypatch.setattr(comm, "SEC_MS_GEC_VERSION", "1-143.0.3650.75")

    ensure_working_endpoint()
    first = comm.WSS_URL
    ensure_working_endpoint()

    assert comm.WSS_URL == first


def test_upstream_v2_token_left_untouched(monkeypatch):
    # 上游改用 v2 token 後(rany2/edge-tts#492),舊 host 又能用:墊片不得覆蓋上游設定
    monkeypatch.setattr(comm, "WSS_URL", LEGACY_WSS)
    monkeypatch.setattr(comm, "SEC_MS_GEC_VERSION", "2-155.0.4283.45")

    ensure_working_endpoint()

    assert comm.WSS_URL == LEGACY_WSS
