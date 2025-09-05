import os
import ast


def _load_save_row():
    path = os.path.join(os.path.dirname(__file__), '..', 'app.py')
    with open(path, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read(), filename='app.py')
    func_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'save_row')
    module = ast.Module(body=[func_node], type_ignores=[])
    namespace = {}
    exec(compile(module, 'app.py', 'exec'), namespace)
    return namespace['save_row']


def test_save_row_results():
    save_row = _load_save_row()

    def dummy_sheet(row):
        return {'ok': True, 'foo': 'bar'}

    def dummy_fire(row):
        return {'ok': True, 'baz': 'qux'}

    save_row.__globals__['save_row_to_scores'] = dummy_sheet
    save_row.__globals__['save_row_to_firestore'] = dummy_fire

    result = save_row({'x': 1}, to_sheet=True, to_firestore=True)
    assert result['ok'] is True
    assert result['sheet_ok'] is True
    assert result['fire_ok'] is True
    assert result['sheet_result']['foo'] == 'bar'
    assert result['fire_result']['baz'] == 'qux'
