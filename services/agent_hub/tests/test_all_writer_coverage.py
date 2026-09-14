"""CI fails when an inventoried writer/callsite loses its retention boundary."""
import ast,json
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
INVENTORY=json.loads((ROOT/'docs/acceptance/agent-hub-p9-rca18a2/SOURCE_INTEGRATION_INVENTORY.json').read_bytes())


def functions(path):
    tree=ast.parse((ROOT/path).read_text(encoding='utf8'));rows={}
    def visit(node,scope=''):
        for child in ast.iter_child_nodes(node):
            if isinstance(child,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                name=(scope+'.' if scope else '')+child.name
                if not isinstance(child,ast.ClassDef):rows[name]=child
                visit(child,name)
            else:visit(child,scope)
    visit(tree);return tree,rows


def decorators(node):return [ast.unparse(d) for d in node.decorator_list]


def test_all_50_exact_writer_boundaries_and_restore_subroutine():
    assert INVENTORY['exact_db1_memory_functions']==50
    for row in INVENTORY['expected_writers']:
        tree,rows=functions(row['path']);node=rows[row['component']]
        if row['component']=='restore_namespace':
            body=ast.unparse(node)
            assert 'with coordinator.batch(owner)' in body and 'GuardedRedis(client, owner)' in body
            callers=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='_restore_namespace_staged']
            assert len(callers)==1 and node.lineno<=callers[0].lineno<=node.end_lineno
        else:assert 'custody_writer' in decorators(node),row


def test_67_callsite_counts_and_outer_operation_scope():
    actual=Counter()
    for path in {r['path'] for r in INVENTORY['callsite_counts']}:
        tree,rows=functions(path)
        for call in (n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)):
            receiver=ast.unparse(call.func.value);key=(path,receiver,call.func.attr)
            if not any((r['path'],r['receiver'],r['callee'])==key for r in INVENTORY['callsite_counts']):continue
            actual[key]+=1
            parents=[node for node in rows.values() if node.lineno<=call.lineno<=node.end_lineno]
            parent=min(parents,key=lambda n:n.end_lineno-n.lineno)
            if receiver=='self':assert 'custody_writer' in decorators(parent)
            else:assert "custody_operation('self.store')" in decorators(parent),(key,parent.name)
    expected=Counter({(r['path'],r['receiver'],r['callee']):r['count'] for r in INVENTORY['callsite_counts']})
    assert actual==expected and sum(actual.values())==67


def test_no_unclassified_store_primitive_writer_is_introduced():
    primitives={'set','setnx','rpush','ltrim','delete','zadd','zrem','expire','pexpireat'}
    for path in ('services/agent_hub/npd_agent_hub/store.py','services/agent_hub/npd_agent_hub/nba_review_repository.py'):
        _,rows=functions(path)
        for name,node in rows.items():
            if name.endswith('__init__'):continue
            writes=[n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                and n.func.attr in primitives and ast.unparse(n.func.value) in ('self.redis','pipe')]
            if writes and 'custody_writer' not in decorators(node):
                # Redis WATCH callbacks are created inside the guarded parent
                # and can only receive its StagedPipeline transaction facade.
                parent=rows.get(name.rpartition('.')[0])
                assert parent is not None and 'custody_writer' in decorators(parent),name
                callbacks=[n for n in ast.walk(parent) if isinstance(n,ast.Call)
                    and ast.unparse(n.func)=='self.redis.transaction' and n.args
                    and isinstance(n.args[0],ast.Name) and n.args[0].id==node.name]
                assert len(callbacks)==1,name


def test_disposition_for_all_22_file_candidates_and_extra_maintenance_boundary():
    dispositions=INVENTORY['file_dispositions'];assert len(dispositions)==22
    assert sum(r['disposition'].startswith('READ_ONLY') for r in dispositions)==10
    for row in dispositions:
        _,rows=functions(row['path'])
        nodes=[n for name,n in rows.items() if name.split('.')[-1]==row['function']]
        assert len(nodes)==1,row
        if row['disposition']=='INTEGRATED_REGISTRY_FIRST_FILE_WRITER':
            assert 'custody_file_writer' in decorators(nodes[0]),row
        elif row['function']=='_write':
            text=ast.unparse(nodes[0]);assert 'os.O_EXCL' in text and 'os.fsync' in text
    _,rows=functions('services/agent_hub/npd_agent_hub/maintenance.py')
    text=ast.unparse(rows['_write_payload'])
    assert 'MAINTENANCE_FILE_CUSTODY_NOT_ACTIVATED' in text and 'write_text' not in text
