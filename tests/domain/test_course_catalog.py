from src.domain.course_catalog import DEFAULT_COURSE_CATALOG_YAML, normalize_course_catalog_yaml


def test_default_empty_catalog_normalizes():
    assert "actions:" in normalize_course_catalog_yaml(DEFAULT_COURSE_CATALOG_YAML)


def test_valid_action_round_trip():
    raw = """
actions:
  - id: peas-tools
    title: 安裝 peas-agent-tools
    kind: package
    command: uv add peas-agent-tools
    description: demo
"""
    out = normalize_course_catalog_yaml(raw)
    assert "peas-tools" in out
    assert "package" in out


def test_rejects_bad_kind():
    raw = """
actions:
  - id: x
    title: X
    kind: asset
    command: echo hi
"""
    try:
        normalize_course_catalog_yaml(raw)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "kind" in str(exc)
