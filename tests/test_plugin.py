"""Checks the Claude Code plugin files stay in sync with the package."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_marketplace_points_at_plugin():
    market = _json(".claude-plugin/marketplace.json")
    plugin = _json("plugin/.claude-plugin/plugin.json")
    entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
    assert (ROOT / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_version_matches_package():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert _json("plugin/.claude-plugin/plugin.json")["version"] == project["version"]


def test_mcp_config_runs_package_script_read_only_by_default():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    server = _json("plugin/.mcp.json")["mcpServers"]["bambu"]
    assert server["args"][-1] in project["scripts"]
    assert server["env"]["BAMBU_READ_ONLY"] == "${BAMBU_READ_ONLY:-true}"


def test_skill_frontmatter():
    text = (ROOT / "plugin/skills/bambu-printer/SKILL.md").read_text(encoding="utf-8")
    head = text.split("---")[1]
    assert "name: bambu-printer" in head
    assert "description:" in head
    assert "\u2014" not in text
