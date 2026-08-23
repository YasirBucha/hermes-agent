"""Integration coverage for profile-local MCP discovery in slash workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import textwrap
import threading

import pytest
import yaml

_mcp_server_mod = pytest.importorskip("mcp.server")

if not hasattr(_mcp_server_mod, "MCPServer"):
    # `mcp.server.MCPServer` replaced `mcp.server.fastmcp.FastMCP` in mcp 2.0.
    # Skip rather than fail on a FastMCP-era SDK: the probe below is written
    # against the 2.x API, and the pinned version provides it.
    pytest.skip(
        "profile-local MCP discovery probe requires mcp >= 2.0 (MCPServer)",
        allow_module_level=True,
    )


def test_profile_local_mcp_tool_is_visible_in_slash_worker(tmp_path):
    profile_home = tmp_path / "profile-home"
    profile_home.mkdir()
    marker = "profile-local-61922"
    server = tmp_path / "mcp_probe.py"
    server.write_text(
        textwrap.dedent(
            f"""
            from mcp.server import MCPServer

            mcp = MCPServer("profileprobe")

            @mcp.tool()
            def hermes_61922_profile_probe() -> str:
                return {marker!r}

            if __name__ == "__main__":
                mcp.run(transport="stdio")
            """
        ),
        encoding="utf-8",
    )
    (profile_home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "mcp_servers": {
                    "profileprobe": {
                        "enabled": True,
                        "command": sys.executable,
                        "args": [str(server)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    for key in list(env):
        if key.endswith("_API_KEY") or key.endswith("_TOKEN"):
            env.pop(key)
    env["HERMES_HOME"] = str(profile_home)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    env["HERMES_SLASH_WATCHDOG_GRACE_S"] = "0"
    env["HERMES_SLASH_WATCHDOG_POLL_S"] = "0.05"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "tui_gateway.slash_worker",
            "--session-key",
            "agent:main:tui:dm:mcp-profile-test",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    output: queue.Queue[str] = queue.Queue()
    try:
        assert proc.stdin is not None
        assert proc.stdout is not None
        stdout = proc.stdout

        def _read_stdout() -> None:
            for line in stdout:
                output.put(line)

        threading.Thread(
            target=_read_stdout,
            daemon=True,
        ).start()

        # Synchronize on actual discovery readiness instead of charging Python
        # import and MCP startup time to the command's 10s response budget.
        # The production worker has a 45s command ceiling; keep this readiness
        # wait bounded by the same outer contract.
        try:
            mcp_ready_line = output.get(timeout=45)
        except queue.Empty:
            pytest.fail("slash worker produced no MCP readiness frame within 45 seconds")
        assert json.loads(mcp_ready_line) == {"type": "mcp.ready"}

        proc.stdin.write(json.dumps({"id": 1, "command": "/tools"}) + "\n")
        proc.stdin.flush()
        try:
            line = output.get(timeout=10)
        except queue.Empty:
            pytest.fail("slash worker produced no /tools response within 10 seconds")
        response = json.loads(line)
        assert response["ok"] is True
        assert "mcp__profileprobe__hermes_61922_profile_probe" in response["output"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_tools_command_waits_for_mcp_discovery_readiness(monkeypatch):
    """The first /tools snapshot must happen after pending discovery settles."""
    from tui_gateway import slash_worker

    ready = threading.Event()
    order: list[str] = []

    def _wait_for_mcp_discovery(*, single_query=False):
        assert single_query is True
        order.append("ready")
        ready.set()

    class _CLI:
        console = None

        def process_command(self, command):
            if command == "/tools":
                assert ready.is_set(), "/tools ran before MCP discovery readiness"
            order.append(command)
            print("mcp__profileprobe__hermes_61922_profile_probe")

    monkeypatch.setattr(
        "hermes_cli.mcp_startup.wait_for_mcp_discovery",
        _wait_for_mcp_discovery,
    )

    result = slash_worker._run(_CLI(), "/tools")

    assert order == ["ready", "/tools"]
    assert "mcp__profileprobe__hermes_61922_profile_probe" in result

    ready.clear()
    order.clear()
    slash_worker._run(_CLI(), "/help")
    assert order == ["/help"], "unrelated commands must not wait for MCP discovery"
