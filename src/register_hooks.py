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

    prompt_hook_cmd = f'{python_bin} {os.path.join(engrammar_home, "hooks", "on_prompt.py")}'
    tool_hook_cmd = f'{python_bin} {os.path.join(engrammar_home, "hooks", "on_tool_use.py")}'

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

    # Auto-allow engrammar MCP tools
    permissions = settings.setdefault("permissions", {})
    allow_list = permissions.setdefault("allow", [])
    mcp_pattern = "mcp__engrammar__*"
    if mcp_pattern not in allow_list:
        allow_list.append(mcp_pattern)
        print(f"Auto-allowed {mcp_pattern}")

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
