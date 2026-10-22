"""Per-harness hook config generators."""

import json

from unified_agent_memory.hook_configs import generate


def test_claude_code_config_covers_all_events():
    fname, text = generate("claude-code")
    cfg = json.loads(text)
    assert fname.endswith("settings.json")
    for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"):
        cmd = cfg["hooks"][event][0]["hooks"][0]["command"]
        assert "uam-hook" in cmd and "claude-code" in cmd


def test_codex_config():
    fname, text = generate("codex")
    cfg = json.loads(text)
    assert fname.endswith("hooks.json")
    assert "SessionStart" in cfg["hooks"]


def test_cursor_config_uses_cursor_event_names():
    fname, text = generate("cursor")
    cfg = json.loads(text)
    assert cfg["version"] == 1
    assert "beforeSubmitPrompt" in cfg["hooks"]
    cmd = cfg["hooks"]["beforeSubmitPrompt"][0]["command"]
    assert "--client cursor" in cmd and "--event beforeSubmitPrompt" in cmd
