from pathlib import Path


def test_portal_key_row_shows_extra_usage_remaining_copy():
    html = Path("src/presentation/fastapi/web/portal.html").read_text(encoding="utf-8")
    assert "extra_usage_remaining" in html
    assert "Extra Usage Remaining" in html
    assert "額度無法取得" in html
