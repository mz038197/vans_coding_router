from pathlib import Path


def test_portal_key_row_shows_included_monthly_usage_copy():
    html = Path("src/presentation/fastapi/web/portal.html").read_text(encoding="utf-8")
    assert "included_monthly_usage" in html
    assert "月用量" in html
    assert "月用量無法取得" in html
    assert "included_weekly_usage" not in html
