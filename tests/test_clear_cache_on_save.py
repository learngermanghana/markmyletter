import ast


def test_cache_cleared_after_save():
    with open('app.py', 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())

    found_block = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Call)
                and isinstance(test.func, ast.Attribute)
                and isinstance(test.func.value, ast.Name)
                and test.func.value.id == 'result'
                and test.func.attr == 'get'
                and len(test.args) >= 1
                and isinstance(test.args[0], ast.Constant)
                and test.args[0].value == 'ok'
            ):
                calls = [n for n in ast.walk(ast.Module(body=node.body)) if isinstance(n, ast.Call)]
                cleared = any(
                    isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name)
                    and c.func.value.id == 'load_sheet_csv'
                    and c.func.attr == 'clear'
                    for c in calls
                )
                rerun = any(
                    isinstance(c.func, ast.Attribute)
                    and isinstance(c.func.value, ast.Name)
                    and c.func.value.id == 'st'
                    and c.func.attr == 'rerun'
                    for c in calls
                )
                if cleared and rerun:
                    found_block = True
                    break
    assert found_block, 'load_sheet_csv.clear() and st.rerun() should be called after successful save'
