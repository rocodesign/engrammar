"""Register Engrammar hooks in settings.json and MCP server in ~/.claude.json."""

import json
import os


def register_hooks():
    """Add Engrammar hooks to ~/.claude/settings.json and MCP server to ~/.claude.json."""
    engrammar_home = os.path.expanduser("~/.engrammar")
    python_bin = os.path.join(engrammar_home, "venv", "bin", "python")

    _register_hooks_in_settings(engrammar_home, python_bin)
    _register_mcp_server(engrammar_home, python_bin)


def _register_hooks_in_settings(engrammar_home, python_bin):
    """Register hooks in ~/.claude/settings.json."""
    settings_path = os.path.expanduser("~/.claude/settings.json")

    session_hook_cmd = f'{python_bin} {os.path.join(engrammar_home, "hooks", "on_session_start.py")}'
    prompt_hook_cmd = f'{python_bin} {os.path.join(engrammar_home, "hooks", "on_prompt.py")}'
    tool_hook_cmd = f'{python_bin} {os.path.join(engrammar_home, "hooks", "on_tool_use.py")}'
    session_end_hook_cmd = f'{python_bin} {os.path.join(engrammar_home, "hooks", "on_session_end.py")}'

    settings = {}
    if os.path.exists(settings_path):
        with open(settings_path, "r") as f:
            settings = json.load(f)

    hooks = settings.setdefault("hooks", {})

    def hook_exists(event_name, command):
        for hook_group in hooks.get(event_name, []):
            for h in hook_group.get("hooks", []):
                if h.get("command", "") == command:
                    return True
        return False

    if not hook_exists("SessionStart", session_hook_cmd):
        hooks.setdefault("SessionStart", []).append({
            "hooks": [{"type": "command", "command": session_hook_cmd}]
        })
        print("Registered SessionStart hook")

    if not hook_exists("UserPromptSubmit", prompt_hook_cmd):
        hooks.setdefault("UserPromptSubmit", []).append({
            "hooks": [{"type": "command", "command": prompt_hook_cmd}]
        })
        print("Registered UserPromptSubmit hook")

    if not hook_exists("PreToolUse", tool_hook_cmd):
        hooks.setdefault("PreToolUse", []).append({
            "hooks": [{"type": "command", "command": tool_hook_cmd}]
        })
        print("Registered PreToolUse hook")

    if not hook_exists("SessionEnd", session_end_hook_cmd):
        hooks.setdefault("SessionEnd", []).append({
            "hooks": [{"type": "command", "command": session_end_hook_cmd}]
        })
        print("Registered SessionEnd hook")

    # Auto-allow engrammar MCP tools
    permissions = settings.setdefault("permissions", {})
    allow_list = permissions.setdefault("allow", [])
    mcp_pattern = "mcp__engrammar__*"
    if mcp_pattern not in allow_list:
        allow_list.append(mcp_pattern)
        print(f"Auto-allowed {mcp_pattern}")

    # Remove old extract-engrams.py hook (replaced by Engrammar extraction)
    for event_name in list(hooks.keys()):
        for hook_group in hooks.get(event_name, []):
            hook_group["hooks"] = [
                h for h in hook_group.get("hooks", [])
                if "extract-engrams.py" not in h.get("command", "")
            ]
        # Remove empty hook groups
        hooks[event_name] = [
            hg for hg in hooks[event_name] if hg.get("hooks")
        ]

    # Clean up mcpServers from settings.json (wrong location)
    if "mcpServers" in settings:
        del settings["mcpServers"]

    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")

    print(f"Updated {settings_path}")


def _register_mcp_server(engrammar_home, python_bin):
    """Register MCP server in ~/.claude.json (where Claude Code reads mcpServers)."""
    claude_json_path = os.path.expanduser("~/.claude.json")
    mcp_server_script = os.path.join(engrammar_home, "engrammar", "mcp_server.py")

    claude_config = {}
    if os.path.exists(claude_json_path):
        with open(claude_json_path, "r") as f:
            claude_config = json.load(f)

    mcp_servers = claude_config.setdefault("mcpServers", {})
    mcp_servers["engrammar"] = {
        "type": "stdio",
        "command": python_bin,
        "args": [mcp_server_script],
        "defer_initialization": False,  # Load immediately - core system tool
        "env": {
            "ENGRAMMAR_HOME": engrammar_home,
        },
    }

    with open(claude_json_path, "w") as f:
        json.dump(claude_config, f, indent=2)
        f.write("\n")

    print(f"Registered MCP server 'engrammar' in {claude_json_path}")


if __name__ == "__main__":
    register_hooks()
