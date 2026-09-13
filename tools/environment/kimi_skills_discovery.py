#!/usr/bin/env python3
"""Bounded, prompt-free Kimi ACP discovery. Output name<TAB>acp:skill:name.

ACP exposes command names, not source paths. Only initialize and session/new
are sent; never authenticate, prompt, execute a tool or modify installed Skills.
Kimi may maintain its own session/log metadata during this local diagnostic.
"""
import json
import math
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time

from skills_discovery import reap


def messages(proc, deadline):
    buffered = b""
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("ACP discovery timed out")
        ready, _, _ = select.select([proc.stdout], [], [], min(remaining, 0.5))
        if not ready:
            continue
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            raise ValueError("ACP closed before discovery completed (check Kimi configuration)")
        total += len(chunk)
        if total > 4 * 1024 * 1024:
            raise ValueError("ACP discovery exceeded 4 MiB")
        buffered += chunk
        while b"\n" in buffered:
            raw, buffered = buffered.split(b"\n", 1)
            try:
                msg = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ValueError("ACP returned malformed JSON") from None
            if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
                raise ValueError("ACP returned an invalid envelope")
            yield msg


def send(proc, request_id, method, params):
    proc.stdin.write((json.dumps({"jsonrpc":"2.0", "id":request_id,
                                 "method":method, "params":params})+"\n").encode())
    proc.stdin.flush()


def discover(proc, cwd, deadline):
    send(proc, 1, "initialize", {"protocolVersion":1, "clientCapabilities":{},
                               "clientInfo":{"name":"aiwb-discovery", "version":"1"}})
    initialized = False
    session_id = None
    updates = {}
    for msg in messages(proc, deadline):
        if "error" in msg:
            # Remote errors may contain config or credential values: keep only the stage.
            raise ValueError("ACP RPC error during %s" % ("session/new" if initialized else "initialize"))
        if "method" in msg and "id" in msg:
            raise ValueError("ACP requested client operations during read-only discovery")
        if msg.get("id") == 1:
            result = msg.get("result")
            if initialized or not isinstance(result, dict) or result.get("protocolVersion") != 1:
                raise ValueError("ACP initialize response is invalid")
            initialized = True
            send(proc, 2, "session/new", {"cwd":cwd, "mcpServers":[]})
        elif msg.get("id") == 2:
            result = msg.get("result")
            if not initialized or not isinstance(result, dict) or not isinstance(result.get("sessionId"), str) or not result["sessionId"]:
                raise ValueError("ACP session/new response is invalid")
            session_id = result["sessionId"]
        elif msg.get("method") == "session/update":
            params = msg.get("params")
            if not isinstance(params, dict) or not isinstance(params.get("update"), dict):
                raise ValueError("ACP session/update is invalid")
            update = params["update"]
            if update.get("sessionUpdate") != "available_commands_update":
                continue
            sid, commands = params.get("sessionId"), update.get("availableCommands")
            if not isinstance(sid, str) or not sid or not isinstance(commands, list):
                raise ValueError("ACP command list is invalid")
            names = []
            for command in commands:
                if (not isinstance(command, dict) or not isinstance(command.get("name"), str)
                        or not command["name"] or not isinstance(command.get("description"), str)):
                    raise ValueError("ACP command entry is invalid")
                name = command["name"]
                if name.startswith("skill:"):
                    name = name[len("skill:"):]
                    if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in names:
                        raise ValueError("ACP Skill command is invalid or duplicated")
                    names.append(name)
            updates[sid] = names
        if session_id is not None and session_id in updates:
            return sorted(updates[session_id])


def main(argv):
    if len(argv) > 1:
        sys.stderr.write("usage: kimi_skills_discovery.py [kimi-binary]\n")
        return 2
    try:
        timeout = float(os.environ.get("AIWB_DISCOVERY_TIMEOUT", "45"))
        if not math.isfinite(timeout) or not 0 < timeout <= 120:
            raise ValueError("timeout must be in (0, 120]")
        binary = argv[0] if argv else "kimi"
        # An empty cwd avoids loading arbitrary project integrations; HOME is preserved
        # so native user-level discovery and configuration are actually checked.
        with tempfile.TemporaryDirectory(prefix="aiwb-kimi-discovery-") as cwd:
            proc = subprocess.Popen([binary, "acp"], cwd=cwd, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                names = discover(proc, cwd, time.monotonic() + timeout)
            finally:
                # Own process group only; include descendants even if the leader exited.
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                reap(proc)
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for name in names:
            print("%s\tacp:skill:%s" % (name, name))
        return 0
    except TimeoutError:
        sys.stderr.write("Kimi ACP discovery timed out; no trusted list\n")
        return 4
    except (OSError, ValueError) as exc:
        # No raw server output, credential values, or implicit retries.
        detail = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        sys.stderr.write("Kimi discovery failed: %s\n" % detail)
        return 5


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
