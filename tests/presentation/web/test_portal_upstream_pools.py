from pathlib import Path


def test_portal_key_row_shows_included_weekly_usage_copy():
    html = Path("src/presentation/fastapi/web/portal.html").read_text(encoding="utf-8")
    assert "included_weekly_usage" in html
    assert "週用量" in html
    assert "週用量無法取得" in html
    assert "額度無法取得" not in html
    assert "extra_usage_remaining" not in html
