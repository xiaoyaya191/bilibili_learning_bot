import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from utils.database import DocumentDatabase, register_directory
from utils.storage import JsonStore


@pytest.fixture
def data(tmp_path):
    directory = tmp_path / 'Data'
    directory.mkdir()
    return directory, DocumentDatabase(directory)


def test_lossless_bom_unicode_nested_null_and_original_snapshot(data):
    directory, database = data
    values = {'config.json': {'人格': '  原始\n提示词  ', 'nested': [False, None, {'score': 2.5}]}, 'null.json': None, 'empty.json': []}
    originals = {}
    for name, value in values.items():
        raw = ('\ufeff' + json.dumps(value, ensure_ascii=False, indent=2)).encode('utf-8')
        (directory / name).write_bytes(raw)
        originals[name] = raw
    result = database.migrate()
    assert result['healthy'] and len(result['records']) == 3
    for name, value in values.items():
        assert database.read(name, 'missing') == value
        assert (directory / name).read_bytes() == originals[name]
    with database.connect() as connection:
        assert dict(connection.execute('SELECT name,raw FROM migration_originals')) == originals


def test_corrupt_json_rolls_back_entire_batch(data):
    directory, database = data
    (directory / 'a.json').write_text('{"ok":true}', encoding='utf-8')
    (directory / 'z.json').write_bytes(b'broken')
    with pytest.raises(json.JSONDecodeError):
        database.migrate()
    result = database.status()
    assert not result['records'] and result['original_count'] == 0
    assert (directory / 'z.json').read_bytes() == b'broken'


def test_store_is_database_backed_and_legacy_change_updates_revision(data):
    directory, database = data
    store = JsonStore(directory / 'personas.json')
    assert store.write({'prompt': 'original'})
    assert database.read('personas.json') == {'prompt': 'original'}
    (directory / 'personas.json').write_text('{"prompt":"manual edit"}', encoding='utf-8')
    assert store.read()['prompt'] == 'manual edit'
    result = database.status()['records'][0]
    assert result['revision'] == 2
    assert store.write({'prompt': 'new'})
    assert json.loads((directory / 'personas.json').read_text(encoding='utf-8'))['prompt'] == 'new'
    with database.connect() as connection:
        original = connection.execute('SELECT raw FROM migration_originals').fetchone()[0]
        assert json.loads(original)['prompt'] == 'original'


def test_deleted_cookie_is_not_resurrected(data):
    directory, database = data
    store = JsonStore(directory / 'bilibili_cookies.json')
    assert store.write({'SESSDATA': 'private'})
    store.path.unlink()
    assert not store.exists()
    assert store.read({}) == {}
    assert not database.status()['records']


def test_update_serializes_independent_store_instances(data):
    directory, database = data
    path = directory / 'counter.json'
    assert JsonStore(path).write({'count': 0})
    def increment(index):
        def change(value):
            value['count'] += 1
        return JsonStore(path).update(change)
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert all(executor.map(increment, range(80)))
    assert JsonStore(path).read()['count'] == 80
    assert json.loads(path.read_text(encoding='utf-8'))['count'] == 80


def test_callback_failure_rolls_back_both_database_and_json(data):
    directory, database = data
    store = JsonStore(directory / 'counter.json')
    assert store.write({'count': 0})
    def fail(value):
        value['count'] = 999
        raise ValueError('cancel')
    assert not store.update(fail)
    assert store.read()['count'] == 0


def test_corrupt_source_cannot_be_overwritten_by_default(data):
    directory, database = data
    path = directory / 'personas.json'
    path.write_text('broken', encoding='utf-8')
    assert JsonStore(path).read({'fallback': True}) == {'fallback': True}
    assert not JsonStore(path).write({'fallback': True})
    assert path.read_text(encoding='utf-8') == 'broken'


def test_corrupt_database_fails_closed(data):
    directory, database = data
    (directory / 'config.json').write_text('{"key":"secret"}', encoding='utf-8')
    database.path.write_bytes(b'broken database')
    with pytest.raises(sqlite3.DatabaseError):
        JsonStore(directory / 'config.json').read()
    assert not JsonStore(directory / 'config.json').write({})
    assert json.loads((directory / 'config.json').read_text(encoding='utf-8'))['key'] == 'secret'


def test_snapshot_is_valid_sqlite_and_account_isolation(data, tmp_path):
    directory, database = data
    assert JsonStore(directory / 'config.json').write({'key': 'first'})
    target = tmp_path / 'snapshot.sqlite3'
    database.snapshot(target)
    with sqlite3.connect(target) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert json.loads(connection.execute('SELECT payload FROM documents').fetchone()[0])['key'] == 'first'
    other = tmp_path / 'other' / 'Data'
    assert JsonStore(other / 'config.json').write({'key': 'second'})
    assert DocumentDatabase(other).read('config.json')['key'] == 'second'
    assert database.read('config.json')['key'] == 'first'


@pytest.mark.parametrize('name', ['../config.json', '/etc/config.json', 'config.txt', 'sub/config.json'])
def test_no_arbitrary_path_access(data, name):
    directory, database = data
    with pytest.raises(ValueError):
        database.read(name)


def test_source_stamp_avoids_reparsing_unchanged_json(data, monkeypatch):
    directory, database = data
    path = directory / 'config.json'
    JsonStore(path).write({'ok': True})
    original = Path.read_bytes
    def blocked(source):
        if source == path:
            raise AssertionError('unchanged JSON was read again')
        return original(source)
    monkeypatch.setattr(Path, 'read_bytes', blocked)
    assert JsonStore(path).read()['ok']


def test_explicit_directory_registration_and_non_data_files(tmp_path):
    path = tmp_path / 'config.json'
    JsonStore(path).write({'mode': 'json'})
    assert not (tmp_path / 'account_data.sqlite3').exists()
    register_directory(tmp_path)
    assert JsonStore(path).read()['mode'] == 'json'
    assert (tmp_path / 'account_data.sqlite3').exists()


def test_root_memory_uses_same_database_without_name_collision(data):
    directory, database = data
    root = directory.parent
    (root / 'bot_memory.json').write_text('{"root":true}', encoding='utf-8')
    (directory / 'bot_memory.json').write_text('{"root":false}', encoding='utf-8')
    result = database.migrate(include_root=True)
    assert {item['name'] for item in result['records']} == {'bot_memory.json', 'root/bot_memory.json'}
    assert JsonStore(root / 'bot_memory.json').read()['root'] is True
    assert JsonStore(directory / 'bot_memory.json').read()['root'] is False
    assert JsonStore(root / 'bot_memory.json').write({'root': True, 'new': True})
    assert not (root / 'account_data.sqlite3').exists()
    assert database.path.exists()


def test_corrupt_root_json_rolls_back_data_migration(data):
    directory, database = data
    (directory / 'config.json').write_text('{"ok":true}', encoding='utf-8')
    (directory.parent / 'bot_memory.json').write_bytes(b'broken')
    with pytest.raises(json.JSONDecodeError):
        database.migrate(include_root=True)
    assert not database.status()['records']


def test_multiple_processes_update_under_sqlite_lock(data):
    import subprocess
    import sys
    directory, database = data
    path = directory / 'counter.json'
    JsonStore(path).write({'count': 0})
    code = '''
import sys
from utils.storage import JsonStore
for iteration in range(15):
    def increment(value):
        value['count'] += 1
    if not JsonStore(sys.argv[1]).update(increment):
        raise SystemExit(1)
'''
    processes = [subprocess.Popen([sys.executable, '-c', code, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for process_index in range(4)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr.decode('utf-8', errors='replace')
    assert JsonStore(path).read()['count'] == 60
