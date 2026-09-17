"""CI checks that both gate entrypoints embed one sealed contract source."""

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "owner_fence_rebind"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(GATE))
from owner_fence_representation import canonical_docker_mounts  # noqa: E402


class ToolingContractTests(unittest.TestCase):
    def test_entrypoints_have_exact_shared_sources(self):
        for name in ("owner_rebind_begin.template.py", "owner_rebind_execute.template.py"):
            source = (GATE / name).read_text(encoding="utf-8")
            self.assertEqual(source.count("# __SHARED_REPRESENTATION_SOURCE__"), 1)
            self.assertEqual(source.count("# __SHARED_PACKAGE_BINDING_CONTRACT__"), 1)
            self.assertEqual(source.count("verify_package_contract(CONTEXT)"), 1)
            compile(source, name, "exec")

    def test_producer_uses_exact_same_mount_function(self):
        producer = (GATE / "prepare_owner_rebind_execution.py").read_text(encoding="utf-8")
        self.assertIn("from owner_fence_representation import canonical_docker_mounts", producer)
        self.assertIn('canonical_docker_mounts(runtime["mounts_full"], target=True)', producer)
        for name in ("owner_rebind_begin.template.py", "owner_rebind_execute.template.py"):
            source = (GATE / name).read_text(encoding="utf-8")
            self.assertIn('canonical_docker_mounts(item.get("Mounts") or [], target=True)', source)
        self.assertTrue(callable(canonical_docker_mounts))

    def test_other_arrays_remain_ordered(self):
        source = (GATE / "owner_rebind_execute.template.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        normalized = ast.get_source_segment(source, functions["normalized"])
        self.assertIn("return [normalized(item) for item in value]", normalized)
        self.assertNotIn("return sorted(items", normalized)
        self.assertIn("canonical_compose_volumes", source)
        self.assertIn('"OLD_COMMAND_DRIFT"', source)
        self.assertIn('"COMMAND_DRIFT"', source)


if __name__ == "__main__":
    unittest.main()
