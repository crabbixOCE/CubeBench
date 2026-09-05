from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import codex_tool_isolation as isolation


class ToolIsolationTests(unittest.TestCase):
    def test_catalog_preserves_model_and_instructions_but_removes_execution_metadata(self):
        original = {'models': [{'slug': 'astra', 'tool_mode': 'code_mode_only',
                                'base_instructions': 'original', 'shell_type': 'unified_exec',
                                'supported_reasoning_levels': [{'effort': 'max'}],
                                'apply_patch_tool_type': 'freeform',
                                'experimental_supported_tools': ['clock']}]}
        model = isolation.isolated_catalog(original, 'astra')['models'][0]
        self.assertEqual(model['slug'], 'astra')
        self.assertEqual(model['base_instructions'], 'original')
        self.assertEqual(model['supported_reasoning_levels'], [{'effort': 'max'}])
        self.assertIsNone(model['tool_mode'])
        self.assertIsNone(model['apply_patch_tool_type'])
        self.assertTrue(model['node_repl_disabled'])
        self.assertEqual(model['experimental_supported_tools'], [])
        self.assertEqual(original['models'][0]['tool_mode'], 'code_mode_only')

    def test_unknown_or_ambiguous_models_fail_closed(self):
        for models in [[], [{'slug': 'astra'}, {'slug': 'astra'}]]:
            with self.assertRaises(RuntimeError):
                isolation.isolated_catalog({'models': models}, 'astra')

    def test_tool_allowlist_rejects_new_or_disguised_executor(self):
        for tool in [('functions', 'exec'), ('functions', 'exec_command'),
                     ('new_namespace', 'load_scramble'), ('mcp__cubebench', 'evaluate')]:
            with self.assertRaises(RuntimeError):
                isolation.assert_tool_surface({tool})
        isolation.assert_tool_surface({('mcp__cubebench', n) for n in isolation.CUBE_TOOLS})

    def test_nested_namespace_is_checked(self):
        tools = [{'type': 'namespace', 'name': 'functions', 'tools': [
            {'type': 'custom', 'name': 'exec'}]}]
        with self.assertRaises(RuntimeError):
            isolation.assert_tool_surface(isolation.tool_names(tools))

    def test_command_pins_catalog_and_disables_host(self):
        args = isolation.command_args(Path('/tmp/catalog.json'))
        self.assertIn('model_catalog_json="/tmp/catalog.json"', args)
        self.assertIn('code_mode_host', args)
        self.assertIn('features.code_mode.enabled=false', args)


if __name__ == '__main__':
    unittest.main()
