"""Enforce and probe CubeBench's no-code Codex tool surface.

The probe uses a local scripted Responses server, no credentials or model
inference. It tests the installed CLI's dispatcher, not a model's willingness
to follow instructions. Unknown tool schemas or executable handlers fail closed.
"""
from __future__ import annotations

import copy
from datetime import UTC, datetime
import http.server
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

CUBE_TOOLS = {'load_scramble', 'apply_moves', 'check_task_complete', 'make_final_submission'}
NO_CODE_INSTRUCTIONS = (
    'This is a NO-CODE cube benchmark. Code execution is disallowed and disabled in this environment. '
    'There is no permitted JavaScript exec wrapper, Python interpreter, shell, REPL, browser, '
    'or other code-execution tool. Do not search for execution tools, attempt hidden tool calls, '
    'or look for workarounds to these restrictions. Do not attempt to run a solver program. '
    'Reason about the cube directly and use only load_scramble, apply_moves, check_task_complete, '
    'and make_final_submission. If needed, use tool_search solely to discover those four CubeBench '
    'tools, then call them directly. The cube tools accept cube operations, not executable code.'
)
# Inert discovery/UI helpers Codex currently registers alongside MCP tools.
HELPERS = {'list_mcp_resources', 'list_mcp_resource_templates', 'read_mcp_resource', 'request_user_input'}
DISABLED = ('code_mode_host', 'code_mode_only', 'code_mode_prewarm', 'shell_tool',
            'unified_exec', 'view_image', 'sleep_tool', 'apps', 'plugins', 'remote_plugin',
            'browser_use', 'browser_use_external', 'browser_use_full_cdp_access',
            'computer_use', 'in_app_browser', 'image_generation', 'multi_agent',
            'goals', 'hooks', 'memories', 'skill_search', 'skill_mcp_dependency_install',
            'shell_snapshot')


def isolated_catalog(catalog: dict, model: str) -> dict:
    matches = [m for m in catalog.get('models', []) if m.get('slug') == model]
    if len(matches) != 1:
        raise RuntimeError(f'Cannot isolate unrecognized model {model!r}')
    result = copy.deepcopy(matches[0])
    result.update(tool_mode=None, node_repl_disabled=True, apply_patch_tool_type=None,
                  experimental_supported_tools=[])
    return {'models': [result]}


def command_args(catalog_path: Path) -> list[str]:
    args = ['-c', 'model_catalog_json=' + json.dumps(str(catalog_path.resolve())),
            '-c', 'features.code_mode.enabled=false',
            '-c', 'features.context_management.experimental_mode=false',
            '-c', 'web_search="disabled"', '-c', 'approval_policy="never"']
    for feature in DISABLED:
        args.extend(['--disable', feature])
    return args


def tool_names(tools: list, namespace: str = '') -> set[tuple[str, str]]:
    names = set()
    for tool in tools:
        if tool.get('type') == 'namespace':
            names.update(tool_names(tool.get('tools', []), tool['name']))
        elif tool.get('type') == 'tool_search':
            names.add(('', 'tool_search'))
        else:
            names.add((namespace, tool.get('name', '<unnamed>')))
    return names


def assert_tool_surface(names: set[tuple[str, str]]) -> None:
    # Older model formats serialize the same helpers without a namespace.
    allowed = {(ns, n) for ns in ('', 'functions') for n in HELPERS} | {('', 'tool_search')}
    allowed |= {('mcp__cubebench', n) for n in CUBE_TOOLS}
    unexpected = names - allowed
    if unexpected:
        raise RuntimeError(f'Unexpected model-visible tools: {sorted(unexpected)}')


# Deliberately send calls that were NOT advertised. A hidden handler is a failure.
ATTACKS = [
    ('exec', 'custom', 'text("CUBEBENCH_CODE_EXECUTED")'),
    ('exec_command', 'function', {'cmd': 'printf CUBEBENCH_SHELL_EXECUTED'}),
    ('shell', 'function', {'command': ['printf', 'CUBEBENCH_SHELL_EXECUTED']}),
    ('js_repl', 'custom', 'console.log("CUBEBENCH_CODE_EXECUTED")'),
    ('apply_patch', 'custom', '*** Begin Patch\n*** Add File: probe-marker\n+CUBEBENCH_PATCH_EXECUTED\n*** End Patch'),
]


class _ProbeServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.server.requests.append(request)
            i = len(self.server.requests)
            if i > len(ATTACKS) + 3:
                raise RuntimeError('Unexpected probe request count')
            if i <= len(ATTACKS):
                name, kind, value = ATTACKS[i - 1]
                item = {'type': kind + '_tool_call' if kind == 'custom' else 'function_call',
                        'id': f'probe_{i}', 'call_id': f'probe_{name}', 'name': name, 'status': 'completed'}
                item['input' if kind == 'custom' else 'arguments'] = value if kind == 'custom' else json.dumps(value)
            elif i == len(ATTACKS) + 1:
                item = {'type': 'tool_search_call', 'id': 'probe_search', 'call_id': 'probe_search',
                        'execution': 'client', 'status': 'completed',
                        'arguments': {'query': 'cubebench load_scramble apply_moves check_task_complete make_final_submission', 'limit': 4}}
            elif i == len(ATTACKS) + 2:
                item = {'type': 'function_call', 'id': 'probe_cube', 'call_id': 'probe_cube',
                        'name': 'load_scramble', 'namespace': 'mcp__cubebench', 'arguments': '{}', 'status': 'completed'}
            else:
                item = {'type': 'message', 'id': 'probe_done', 'role': 'assistant',
                        'content': [{'type': 'output_text', 'text': 'Tool isolation probe complete.'}]}
            response = {'id': f'resp_{i}', 'object': 'response', 'created_at': 1, 'status': 'completed',
                        'output': [], 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
            events = [
                {'type': 'response.created', 'response': dict(response, status='in_progress')},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': item},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                {'type': 'response.completed', 'response': dict(response, output=[item])},
            ]
            body = ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            self.server.errors.append(str(exc))
            self.send_error(400)


def probe(home: Path, model: str, catalog_path: Path, codex_bin: str, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='cubebench-isolation-') as tmp:
        root = Path(tmp)
        probe_home, workspace = root / 'home', root / 'workspace'
        probe_home.mkdir(); workspace.mkdir()
        server = _ProbeServer(('127.0.0.1', 0), _Handler)
        server.requests, server.errors = [], []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        # Deliberately do not copy auth.json or inherit API credentials.
        (probe_home / 'config.toml').write_text((home / 'config.toml').read_text())
        env = os.environ.copy()
        env['CODEX_HOME'] = str(probe_home)
        env.pop('OPENAI_API_KEY', None); env.pop('CODEX_API_KEY', None)
        overrides = command_args(catalog_path) + [
            '-c', 'model_provider="cubebench_isolation_probe"',
            '-c', 'model_providers.cubebench_isolation_probe.name="Local isolation test"',
            '-c', f'model_providers.cubebench_isolation_probe.base_url="http://127.0.0.1:{server.server_port}/v1"',
            '-c', 'model_providers.cubebench_isolation_probe.wire_api="responses"',
            '-c', 'model_providers.cubebench_isolation_probe.requires_openai_auth=false',
            '-c', 'features.enable_request_compression=false',
        ]
        command = [codex_bin, 'exec', '--json', '--strict-config', '--ignore-rules',
                   '--skip-git-repo-check', '--sandbox', 'read-only', '--model', model,
                   *overrides, '-C', str(workspace), 'Local tool-isolation test only.']
        try:
            completed = subprocess.run(command, env=env, text=True, capture_output=True, timeout=60)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        (output / 'probe-stdout.jsonl').write_text(completed.stdout)
        (output / 'probe-stderr.txt').write_text(completed.stderr)
        if completed.returncode or server.errors:
            raise RuntimeError(f'Isolation probe failed: {completed.stderr[-1500:]} {server.errors}')
        names, discovered, results = set(), set(), {}
        for request in server.requests:
            names.update(tool_names(request.get('tools', [])))
            for item in request.get('input', []):
                if item.get('type') == 'additional_tools':
                    names.update(tool_names(item.get('tools', [])))
                if item.get('type') == 'tool_search_output':
                    found = tool_names(item.get('tools', []))
                    names.update(found); discovered.update(found)
                if item.get('type') in {'function_call_output', 'custom_tool_call_output'}:
                    results[item.get('call_id')] = item.get('output')
        assert_tool_surface(names)
        expected = {('mcp__cubebench', n) for n in CUBE_TOOLS}
        if discovered != expected:
            raise RuntimeError(f'Cube tools unavailable or unexpected tools discovered: {sorted(discovered)}')
        rejections = {}
        for name, kind, _ in ATTACKS:
            result = results.get('probe_' + name)
            expected_error = f'unsupported custom tool call: {name}' if kind == 'custom' else f'unsupported call: {name}'
            if result != expected_error:
                raise RuntimeError(f'{name} was not rejected by the dispatcher: {str(result)[:300]}')
            rejections[name] = result
        cube_ok = any(e.get('type') == 'item.completed' and e.get('item', {}).get('tool') == 'load_scramble'
                      and e['item'].get('status') == 'completed' and not e['item'].get('error')
                      and e['item'].get('result', {}).get('structured_content', {}).get('state')
                      for e in (json.loads(line) for line in completed.stdout.splitlines() if line.startswith('{')))
        if not cube_ok:
            raise RuntimeError('Direct CubeBench load_scramble did not succeed')
        report = {'passed': True, 'model': model, 'timestamp': datetime.now(UTC).isoformat(),
                  'codex_version': subprocess.check_output([codex_bin, '--version'], text=True).strip(),
                  'tools': sorted(names), 'rejections': rejections, 'cube_load_succeeded': True,
                  'uses_model_inference': False, 'catalog': str(catalog_path),
                  'catalog_sha256': hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
                  'config_sha256': hashlib.sha256((home / 'config.toml').read_bytes()).hexdigest()}
        (output / 'report.json').write_text(json.dumps(report, indent=2))
        return report


def prepare(home: Path, model: str, codex_bin: str, output: Path) -> list[str]:
    """Pin metadata, validate the running CLI, and return mandatory overrides."""
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'report.json'
    report_path.write_text(json.dumps({'passed': False, 'model': model, 'state': 'checking'}))
    try:
        return _prepare(home, model, codex_bin, output)
    except Exception as exc:
        report_path.write_text(json.dumps({'passed': False, 'model': model, 'error': str(exc)}, indent=2))
        raise


def _prepare(home: Path, model: str, codex_bin: str, output: Path) -> list[str]:
    env = os.environ.copy(); env['CODEX_HOME'] = str(home)
    raw = subprocess.run([codex_bin, 'debug', 'models'], env=env, text=True, capture_output=True, timeout=45)
    if raw.returncode:
        raise RuntimeError('Cannot obtain model catalog: ' + raw.stderr[-1000:])
    catalog = isolated_catalog(json.loads(raw.stdout), model)
    catalog_path = home / 'cubebench-no-code-model.json'
    catalog_path.write_text(json.dumps(catalog, indent=2))
    probe(home, model, catalog_path, codex_bin, output)
    return command_args(catalog_path)
