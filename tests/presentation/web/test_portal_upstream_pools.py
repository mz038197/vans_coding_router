from pathlib import Path


def test_portal_key_row_shows_included_monthly_usage_copy():
    html = Path("src/presentation/fastapi/web/portal.html").read_text(encoding="utf-8")
    assert "included_monthly_usage" in html
    assert "value.summary" in html
    assert "value.resets" in html
    assert "月用量無法取得" in html
    assert "included_weekly_usage" not in html


def test_portal_openrouter_key_row_shows_account_credit_remaining_copy():
    html = Path("src/presentation/fastapi/web/portal.html").read_text(encoding="utf-8")
    assert "account_credit_remaining" in html
    assert "name === 'openrouter'" in html
    assert "餘額無法取得" in html
    assert "餘額 ${sign}$${abs.toFixed(2)}" in html
