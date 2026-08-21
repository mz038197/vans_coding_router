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


def test_round_trips_snippets_and_keeps_body_whitespace():
    raw = """
actions: []
snippets:
  - id: stub
    title: MCP 客戶端骨架
    paste_hint: mcp_client.py
    body: "  def call():\\n    pass\\n"
"""
    out = normalize_course_catalog_yaml(raw)
    assert "stub" in out
    assert "paste_hint" in out
    reloaded = normalize_course_catalog_yaml(out)
    import yaml

    doc = yaml.safe_load(reloaded)
    assert doc["snippets"][0]["body"] == "  def call():\n    pass\n"


def test_omits_empty_snippets_from_dump():
    out = normalize_course_catalog_yaml("actions: []\nsnippets: []\n")
    assert "snippets" not in out


def test_rejects_duplicate_snippet_ids():
    raw = """
actions: []
snippets:
  - id: stub
    title: A
    body: a
  - id: stub
    title: B
    body: b
"""
    try:
        normalize_course_catalog_yaml(raw)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "id" in str(exc)
