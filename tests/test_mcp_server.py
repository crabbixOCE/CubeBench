from __future__ import annotations

from io import BytesIO
import json
import unittest

from cubebench_harness.mcp_server import CubeBenchMcpServer


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        if name == "load_scramble":
            return {"representation": "test", "state": "loaded"}
        if name == "apply_moves":
            return {"applied_moves": arguments["moves"], "state": "moved"}
        if name == "check_task_complete":
            return {"task": arguments["task"], "task_completed": True}
        if name == "make_final_submission":
            return {"submission_accepted": True, "submitted_moves": arguments["moves"]}
        raise AssertionError(f"unexpected tool {name}")


class _FailingExecutor:
    def execute(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        raise ValueError("bad cube input")


def _request(request_id: int, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
    request: dict[str, object] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        request["params"] = params
    return request


class McpSchemaTests(unittest.TestCase):
    def test_tools_list_exposes_only_common_tools_and_one_task(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="one_layer")

        response = server.handle_message(_request(1, "tools/list"))

        self.assertIsNotNone(response)
        assert response is not None
        tools = response["result"]["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools],
            ["load_scramble", "apply_moves", "check_task_complete", "make_final_submission"],
        )
        check_tool = tools[2]
        self.assertEqual(
            check_tool["inputSchema"]["properties"]["task"]["enum"],
            ["one_layer"],
        )
        self.assertNotIn("get_state", [tool["name"] for tool in tools])

    def test_tools_property_is_defensive_copy(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="cross")

        tools = server.tools
        tools[0]["name"] = "mutated"

        self.assertEqual(server.tools[0]["name"], "load_scramble")


class McpDispatchTests(unittest.TestCase):
    def test_initialize_and_notifications_follow_jsonrpc(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="cross")

        initialize = server.handle_message(
            _request(7, "initialize", {"protocolVersion": "2025-03-26"})
        )
        initialized = server.handle_message(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

        assert initialize is not None
        self.assertEqual(initialize["id"], 7)
        self.assertEqual(initialize["result"]["protocolVersion"], "2025-03-26")
        self.assertIsNone(initialized)
        self.assertTrue(server.initialized)

    def test_tool_calls_delegate_and_return_structured_and_text_results(self) -> None:
        executor = _RecordingExecutor()
        server = CubeBenchMcpServer(executor, task="cross")

        calls = [
            _request(1, "tools/call", {"name": "load_scramble", "arguments": {}}),
            _request(2, "tools/call", {"name": "apply_moves", "arguments": {"moves": "R"}}),
            _request(
                3,
                "tools/call",
                {"name": "check_task_complete", "arguments": {"task": "cross"}},
            ),
            _request(
                4,
                "tools/call",
                {"name": "make_final_submission", "arguments": {"moves": "R'"}},
            ),
        ]

        responses = [server.handle_message(call) for call in calls]

        self.assertEqual([call[0] for call in executor.calls], [
            "load_scramble", "apply_moves", "check_task_complete", "make_final_submission"
        ])
        for response, request_id in zip(responses, range(1, 5)):
            assert response is not None
            self.assertEqual(response["id"], request_id)
            result = response["result"]
            self.assertFalse(result["isError"])
            self.assertEqual(json.loads(result["content"][0]["text"]), result["structuredContent"])

    def test_invalid_task_is_rejected_before_executor(self) -> None:
        executor = _RecordingExecutor()
        server = CubeBenchMcpServer(executor, task="cross")

        response = server.handle_message(
            _request(
                9,
                "tools/call",
                {"name": "check_task_complete", "arguments": {"task": "f2l"}},
            )
        )

        assert response is not None
        self.assertEqual(response["error"]["code"], -32602)
        self.assertEqual(executor.calls, [])

    def test_executor_error_is_a_tool_error_result(self) -> None:
        server = CubeBenchMcpServer(_FailingExecutor(), task="cross")

        response = server.handle_message(
            _request(11, "tools/call", {"name": "load_scramble", "arguments": {}})
        )

        assert response is not None
        self.assertTrue(response["result"]["isError"])
        self.assertIn("bad cube input", response["result"]["content"][0]["text"])

    def test_protocol_errors_and_notifications(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="cross")

        unknown = server.handle_message(_request(1, "does/not-exist"))
        wrong_params = server.handle_message(
            _request(2, "tools/call", {"name": "load_scramble", "arguments": []})
        )
        notification = server.handle_message({"jsonrpc": "2.0", "method": "ping"})

        assert unknown is not None
        assert wrong_params is not None
        self.assertEqual(unknown["error"]["code"], -32601)
        self.assertEqual(wrong_params["error"]["code"], -32602)
        self.assertIsNone(notification)

    def test_optional_discovery_endpoints_are_empty(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="cross")

        resources = server.handle_message(_request(1, "resources/list"))
        templates = server.handle_message(_request(2, "resources/templates/list"))
        prompts = server.handle_message(_request(3, "prompts/list"))

        assert resources is not None
        assert templates is not None
        assert prompts is not None
        self.assertEqual(resources["result"], {"resources": []})
        self.assertEqual(templates["result"], {"resourceTemplates": []})
        self.assertEqual(prompts["result"], {"prompts": []})


class McpStdioTests(unittest.TestCase):
    def test_serve_reads_newline_json_and_content_length_frames(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="cross")
        initialize = json.dumps(_request(1, "initialize"), separators=(",", ":"))
        tools_list = json.dumps(_request(2, "tools/list"), separators=(",", ":"))
        framed = f"Content-Length: {len(tools_list.encode())}\r\n\r\n{tools_list}"
        input_stream = BytesIO((initialize + "\n" + framed).encode())
        output_stream = BytesIO()

        server.serve(input_stream, output_stream)

        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2])
        self.assertEqual(len(responses[1]["result"]["tools"]), 4)

    def test_serve_reports_parse_errors_without_stopping(self) -> None:
        server = CubeBenchMcpServer(_RecordingExecutor(), task="cross")
        input_stream = BytesIO(b"not-json\n{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"ping\"}\n")
        output_stream = BytesIO()

        server.serve(input_stream, output_stream)

        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["result"], {})


if __name__ == "__main__":
    unittest.main()
