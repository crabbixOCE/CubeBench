"""A small stdio MCP server exposing the CubeBench cube tools.

The provider harness talks directly to model APIs, while Codex can talk to a
local MCP server.  This module is the bridge between those two interfaces.  It
intentionally contains no model or network code: one process owns one cube
state, and every ``tools/call`` is delegated to :class:`ToolExecutor`.

The transport follows MCP's stdio convention of one JSON-RPC object per line.
For convenience, input with ``Content-Length`` headers is accepted too; this
makes the server useful with clients that use the older language-server-style
framing.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from typing import Any, BinaryIO, Iterable, TextIO

from .config import HarnessConfig
from .converters import get_converter
from .cube_bridge import CubeJsBridge
from .tasks import get_task_definition
from .tooling import ToolExecutor, build_common_tooldefs


# MCP clients negotiate this during initialize.  We echo a client's requested
# version when present so that a newer client can still use this deliberately
# small subset of the protocol; clients that omit it receive the current
# baseline version used by the stdio transport.
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cubebench"
SERVER_VERSION = "0.1.0"


class _ParseError:
    """Internal marker used when a stdio frame is not valid JSON."""


def _task_tooldefs(task: str) -> list[dict[str, Any]]:
    """Return MCP tool payloads for exactly one configured benchmark task."""

    # Validate once here rather than allowing a typo to produce a server that
    # starts successfully but can never complete its run.
    task_definition = get_task_definition(task)
    tool_payloads: list[dict[str, Any]] = []
    for tooldef in build_common_tooldefs():
        schema = deepcopy(tooldef.input_schema)
        description = tooldef.description
        if tooldef.name == "check_task_complete":
            # A Codex process is launched for one planned run.  Narrowing the
            # enum and enforcing it in tools/call prevents accidental checks
            # against another task in the same session.
            schema["properties"]["task"]["enum"] = [task_definition.id]
            description = (
                f"{description} This server is configured for the '{task_definition.id}' task."
            )
        tool_payloads.append(
            {
                "name": tooldef.name,
                "description": description,
                "inputSchema": schema,
            }
        )
    return tool_payloads


def _json_text(value: Any) -> str:
    """Serialize a tool result into deterministic MCP text content."""

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


class CubeBenchMcpServer:
    """Dispatch CubeBench tools over newline-delimited JSON-RPC.

    ``executor`` is injected so protocol tests can run with a recording fake;
    production construction is provided by :func:`build_server`.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        task: str,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
    ) -> None:
        get_task_definition(task)
        self.executor = executor
        self.task = task
        self.server_name = server_name
        self.server_version = server_version
        self._tools = _task_tooldefs(task)
        self._tool_names = {tool["name"] for tool in self._tools}
        self.initialized = False

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Return a copy so callers cannot mutate the advertised schemas."""

        return deepcopy(self._tools)

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        """Handle one parsed JSON-RPC request or notification.

        Notifications (requests without an ``id``) return ``None`` as required
        by JSON-RPC.  Errors are encoded as JSON-RPC error objects for protocol
        failures and as ``isError`` tool results for tool execution failures,
        matching MCP's ``tools/call`` semantics.
        """

        if not isinstance(message, dict):
            return self._error(None, -32600, "Invalid Request")

        request_id = message.get("id")
        is_notification = "id" not in message
        if message.get("jsonrpc") != "2.0":
            return None if is_notification else self._error(request_id, -32600, "Invalid Request")

        method = message.get("method")
        if not isinstance(method, str):
            return None if is_notification else self._error(request_id, -32600, "Invalid Request")

        params = message.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return None if is_notification else self._error(request_id, -32602, "Invalid params")

        if method == "notifications/initialized":
            self.initialized = True
            return None
        if method == "initialized":
            # A few early MCP clients sent the short notification name.  It is
            # harmless to accept it while still emitting no response.
            self.initialized = True
            return None
        if method == "initialize":
            requested_version = params.get("protocolVersion")
            protocol_version = (
                requested_version
                if isinstance(requested_version, str) and requested_version.strip()
                else MCP_PROTOCOL_VERSION
            )
            result = {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
                "instructions": (
                    f"CubeBench server configured for one '{self.task}' task. "
                    "Load the scramble before applying moves."
                ),
            }
            return None if is_notification else self._result(request_id, result)
        if method == "ping":
            return None if is_notification else self._result(request_id, {})
        if method == "tools/list":
            result = {"tools": self.tools}
            return None if is_notification else self._result(request_id, result)
        if method == "resources/list":
            return None if is_notification else self._result(request_id, {"resources": []})
        if method == "resources/templates/list":
            return None if is_notification else self._result(
                request_id, {"resourceTemplates": []}
            )
        if method == "prompts/list":
            return None if is_notification else self._result(request_id, {"prompts": []})
        if method == "tools/call":
            return None if is_notification else self._call_tool(request_id, params)

        return None if is_notification else self._error(request_id, -32601, "Method not found")

    def _call_tool(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            return self._error(request_id, -32602, "tools/call requires a non-empty 'name'.")
        if name not in self._tool_names:
            return self._error(request_id, -32602, f"Unknown tool: {name}")

        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return self._error(request_id, -32602, "tools/call 'arguments' must be an object.")

        # This check is intentionally in the adapter as well as the schema:
        # clients are allowed to send arguments without validating the schema.
        if name == "check_task_complete" and arguments.get("task") != self.task:
            return self._error(
                request_id,
                -32602,
                f"This server only accepts check_task_complete for task '{self.task}'.",
            )

        try:
            payload = self.executor.execute(name, arguments)
        except Exception as exc:  # Tool errors belong in an MCP tool result.
            error_payload = {"error": f"{type(exc).__name__}: {exc}"}
            return self._result(
                request_id,
                {
                    "content": [{"type": "text", "text": _json_text(error_payload)}],
                    "isError": True,
                },
            )

        return self._result(
            request_id,
            {
                "content": [{"type": "text", "text": _json_text(payload)}],
                "structuredContent": payload,
                "isError": False,
            },
        )

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def serve(self, input_stream: TextIO | BinaryIO | None = None, output_stream: TextIO | BinaryIO | None = None) -> None:
        """Serve requests until stdin closes.

        The function deliberately writes no logs to stdout because that stream
        is the JSON-RPC channel.  Diagnostics, if needed, should go to stderr.
        """

        input_stream = input_stream or sys.stdin
        output_stream = output_stream or sys.stdout
        binary_input = getattr(input_stream, "buffer", input_stream)
        binary_output = getattr(output_stream, "buffer", output_stream)

        for message in _iter_json_messages(binary_input):
            try:
                if isinstance(message, _ParseError):
                    response = self._error(None, -32700, "Parse error")
                else:
                    response = self.handle_message(message)
            except Exception as exc:  # Keep one bad request from killing a run.
                response = self._error(
                    message.get("id") if isinstance(message, dict) else None,
                    -32603,
                    f"Internal error: {type(exc).__name__}: {exc}",
                )
            if response is not None:
                _write_json_message(binary_output, response)


def _iter_json_messages(stream: BinaryIO) -> Iterable[Any]:
    """Yield JSON objects from newline or Content-Length framed stdin."""

    while True:
        line = stream.readline()
        if not line:
            return
        if isinstance(line, str):
            line = line.encode()
        line = line.strip()
        if not line:
            continue

        if line.lower().startswith(b"content-length:"):
            try:
                length = int(line.split(b":", 1)[1].strip())
            except (IndexError, ValueError):
                # Yield a malformed sentinel so serve() emits a parse error.
                yield _ParseError()
                continue
            # Consume remaining headers through the required empty line.
            while True:
                header = stream.readline()
                if not header or header in (b"\n", b"\r\n", "\n", "\r\n"):
                    break
            payload = stream.read(length)
            if not payload or len(payload) != length:
                yield _ParseError()
                return
        else:
            payload = line

        try:
            yield json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            yield _ParseError()


def _write_json_message(stream: BinaryIO | TextIO, message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
    try:
        stream.write(payload.encode())  # type: ignore[union-attr]
    except (AttributeError, TypeError):
        stream.write(payload)  # type: ignore[arg-type]
    stream.flush()


def build_server(
    *,
    task: str,
    scramble: str,
    cube: str = "3x3",
    representation: str = "cubie_json",
    scramble_name: str = "codex",
    repo_root: Path | None = None,
) -> CubeBenchMcpServer:
    """Build an isolated one-task server around the real cube bridge."""

    task_definition = get_task_definition(task)
    if not isinstance(scramble, str) or not scramble.strip():
        raise ValueError("A non-empty scramble is required.")
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    config = HarnessConfig(
        provider="codex",
        model_name="codex",
        cube=cube,
        representation=representation,
        scramble_name=scramble_name,
        scramble=scramble,
        task=task_definition.id,
    )
    converter = get_converter(config.representation)
    bridge = CubeJsBridge(repo_root=repo_root, cube=config.cube)
    return CubeBenchMcpServer(
        ToolExecutor(config=config, bridge=bridge, converter=converter),
        task=config.task,
    )


def _env_or(value: str | None, env_name: str, default: str | None = None) -> str | None:
    if value is not None:
        return value
    return os.environ.get(env_name, default)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve CubeBench tools over MCP stdio.")
    parser.add_argument("--task", default=_env_or(None, "CUBEBENCH_TASK"), choices=sorted({
        "white_cross", "cross", "one_face", "one_layer", "f2l", "full_solve"
    }))
    parser.add_argument("--scramble", default=_env_or(None, "CUBEBENCH_SCRAMBLE"))
    parser.add_argument(
        "--scramble-name",
        default=_env_or(None, "CUBEBENCH_SCRAMBLE_NAME", "codex"),
    )
    parser.add_argument("--cube", default=_env_or(None, "CUBEBENCH_CUBE", "3x3"))
    parser.add_argument(
        "--representation",
        default=_env_or(None, "CUBEBENCH_REPRESENTATION", "cubie_json"),
        choices=["cubie_json", "facelet_string"],
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(_env_or(None, "CUBEBENCH_REPO_ROOT", str(Path(__file__).resolve().parents[2]))),
    )
    args = parser.parse_args(argv)
    if not args.task:
        parser.error("--task or CUBEBENCH_TASK is required")
    if not args.scramble:
        parser.error("--scramble or CUBEBENCH_SCRAMBLE is required")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    server = build_server(
        task=args.task,
        scramble=args.scramble,
        cube=args.cube,
        representation=args.representation,
        scramble_name=args.scramble_name,
        repo_root=args.repo_root,
    )
    server.serve()


if __name__ == "__main__":
    main()
