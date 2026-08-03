from src.infrastructure.gateways.realtime_proxy import (
    http_base_to_realtime_ws_url,
    rewrite_realtime_client_text,
)


def test_http_base_to_realtime_ws_url():
    assert (
        http_base_to_realtime_ws_url("https://api.openai.com/v1", "gpt-live-transcribe")
        == "wss://api.openai.com/v1/realtime?model=gpt-live-transcribe"
    )


def test_rewrite_session_update_transcription_model():
    raw = (
        '{"type":"session.update","session":{"type":"transcription",'
        '"audio":{"input":{"transcription":{"model":"openai@gpt-live-transcribe"}}}}}'
    )
    rewritten = rewrite_realtime_client_text(raw, "gpt-live-transcribe")
    assert '"model": "gpt-live-transcribe"' in rewritten or '"model":"gpt-live-transcribe"' in rewritten
    assert "openai@" not in rewritten


def test_rewrite_leaves_non_session_update_untouched():
    raw = '{"type":"input_audio_buffer.append","audio":"abc"}'
    assert rewrite_realtime_client_text(raw, "gpt-live-transcribe") == raw
