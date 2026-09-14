"""Exact supplementary SQL/control census; original 50/67 tests stay mandatory."""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SUPPLEMENT = json.loads((ROOT / "docs/acceptance/agent-hub-p9-rca18a5/WRITER_SUPPLEMENT.json").read_bytes())


def nodes(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf8"))
    functions = {}
    for cls in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        for node in cls.body:
            if isinstance(node, ast.FunctionDef):
                functions[cls.name + "." + node.name] = node
    return tree, functions


def test_all_new_control_writers_have_exact_auth_or_sql_boundary():
    assert len(SUPPLEMENT["new_control_journal_writers"]) == 5
    for row in SUPPLEMENT["new_control_journal_writers"]:
        _, functions = nodes(row["path"])
        node = functions[row["component"]]
        body = ast.unparse(node)
        if row["component"].startswith("Durable"):
            assert "with self.journal.atomic() as snapshot:" in body
            assert "self._check_trust()" in body and "restore_model" in body
        elif node.name == "create_fixture":
            assert "scope.path(name)" in body and "os.O_EXCL" in body
            assert "BEGIN IMMEDIATE" in body and "synchronous=FULL" in body
        elif node.name == "atomic":
            assert "BEGIN IMMEDIATE" in body and "self._load(connection)" in body
            assert "sql_failure(error, committing)" in body and "connection.commit()" in body
        else:
            assert node.name == "_append_commit" and "validate_extension" in body
            assert "INSERT INTO commits" in body


def test_exact_five_journal_transition_calls_and_private_append_owner():
    for expected in SUPPLEMENT["new_control_call_sites"]:
        path = "services/agent_hub/npd_agent_hub/" + (
            "durable_custody_authority.py" if expected["caller"].startswith("Durable") else "authority_journal.py")
        tree, functions = nodes(path)
        node = functions[expected["caller"]]
        calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and ast.unparse(n.func) == expected["callee"]]
        assert len(calls) == expected["count"]
        if expected["callee"] == "self._append_commit":
            all_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n.func) == expected["callee"]]
            assert calls == all_calls


def test_no_new_uninventoried_sql_write_or_production_activation():
    path = "services/agent_hub/npd_agent_hub/authority_journal.py"
    _, functions = nodes(path)
    allowed_sql = {"SQLiteFixtureAuthorityJournal.create_fixture", "SQLiteFixtureAuthorityJournal._append_commit"}
    for name, node in functions.items():
        for call in (n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr in {"execute", "executemany"} and n.args):
            if isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
                query = call.args[0].value.upper()
                if query.startswith(("INSERT", "UPDATE", "DELETE", "CREATE TABLE", "DROP", "ALTER")):
                    assert name in allowed_sql, name
    source = (ROOT / path).read_text(encoding="utf8")
    assert "PRODUCTION_AUTHORITY_JOURNAL_NOT_ACCEPTED_HOLD" in source
    assert "import redis" not in source and "import boto" not in source
    assert "minimum_checkpoint: JournalCheckpoint" in source
    assert SUPPLEMENT["known_unprotected_static_boundaries"] == 0
