import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.account_workspaces import AccountWorkspaces


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr('core.account_workspaces.port_available', lambda port: True)
    return AccountWorkspaces(tmp_path / 'profile')


def test_ten_independent_accounts_and_ports(registry):
    accounts = [registry.create('账号 ' + str(number)) for number in range(10)]
    assert [account['port'] for account in accounts] == list(range(18083, 18093))
    assert len({account['workspace'] for account in accounts}) == 10
    for account in accounts:
        workspace = Path(account['workspace'])
        assert (workspace / 'KnowledgeBase').is_dir()
        assert not (workspace / 'Data' / 'bilibili_cookies.json').exists()
        assert json.loads((workspace / 'Data' / 'config.json').read_text())['web']['port'] == account['port']
    with pytest.raises(ValueError, match='10'):
        registry.create('第11个')


@pytest.mark.parametrize('port', [True, 80, 65536, 'abc', 18083.5])
def test_invalid_ports(registry, port):
    with pytest.raises(ValueError):
        registry.create('无效', port)


def test_port_collision_and_busy_port(registry, monkeypatch):
    registry.create('主账号', 19000)
    with pytest.raises(ValueError, match='占用'):
        registry.create('副账号', 19000)
    monkeypatch.setattr('core.account_workspaces.port_available', lambda port: False)
    with pytest.raises(ValueError, match='占用'):
        registry.create('副账号', 19001)


@pytest.mark.parametrize('account_id', ['../outside', 'account-011', 'account-000', 'account-001/../../outside'])
def test_reject_traversal(registry, account_id):
    with pytest.raises(ValueError):
        registry.workspace(account_id)


def test_corrupt_index_preserved(registry):
    registry.root.mkdir()
    registry.index.write_text('{broken')
    with pytest.raises(ValueError, match='损坏'):
        registry.create('主账号')
    assert registry.index.read_text() == '{broken'


def test_delete_confirm_backup_and_no_other_account_changes(registry):
    first = registry.create('主账号')
    second = registry.create('副账号')
    cookie = Path(second['workspace']) / 'Data' / 'bilibili_cookies.json'
    cookie.write_text('{"SESSDATA":"private"}')
    with pytest.raises(ValueError, match='二次确认'):
        registry.delete(second['id'], '')
    assert cookie.exists()
    backup = registry.delete(second['id'], second['id'])
    assert Path(backup).is_file()
    assert Path(first['workspace']).is_dir()
    assert len(registry.list()) == 1
    with pytest.raises(ValueError, match='不能删除'):
        registry.delete(first['id'], first['id'])


def test_migrate_legacy_with_backup_and_no_cookie_copy_to_second(registry, tmp_path):
    legacy = registry.root / 'Data'
    legacy.mkdir(parents=True)
    (legacy / 'bilibili_cookies.json').write_text('{"SESSDATA":"private"}')
    (legacy / 'config.json').write_text(json.dumps({'api': {'unified_api_key': 'secret'}, 'web': {'username': 'owner'}}))
    project = tmp_path / 'project'
    (registry.root / 'KnowledgeBase').mkdir()
    (registry.root / 'KnowledgeBase' / 'note.md').write_text('stale profile mirror')
    (project / 'KnowledgeBase').mkdir(parents=True)
    (project / 'KnowledgeBase' / 'note.md').write_text('existing knowledge')
    first = registry.ensure_default(project)
    workspace = Path(first['workspace'])
    assert (workspace / 'KnowledgeBase' / 'note.md').read_text() == 'existing knowledge'
    assert (workspace / 'Data' / 'bilibili_cookies.json').read_text() == (legacy / 'bilibili_cookies.json').read_text()
    assert list((registry.root / 'backups').glob('legacy-*/Data/bilibili_cookies.json'))
    assert json.loads((workspace / 'Data' / 'config.json').read_text())['api']['unified_api_key'] == 'secret'
    assert registry.ensure_default(project) == first
    second = registry.create('全新账号')
    assert not (Path(second['workspace']) / 'Data' / 'bilibili_cookies.json').exists()
    assert 'secret' not in registry.index.read_text(encoding='utf-8')


def test_parallel_creation_has_unique_ids_and_ports(registry):
    with ThreadPoolExecutor(max_workers=6) as pool:
        accounts = list(pool.map(lambda number: registry.create(str(number)), range(10)))
    assert len({account['id'] for account in accounts}) == 10
    assert len({account['port'] for account in accounts}) == 10
    assert len(registry.list()) == 10


def test_rename_and_change_port(registry):
    first = registry.create('主账号')
    second = registry.create('副账号')
    changed = registry.update(second['id'], '新名称', 20000)
    assert changed['name'] == '新名称'
    assert changed['port'] == 20000
    with pytest.raises(ValueError, match='占用'):
        registry.update(second['id'], port=first['port'])


def test_bad_legacy_config_does_not_publish_registry(registry, tmp_path):
    legacy = registry.root / 'Data'
    legacy.mkdir(parents=True)
    (legacy / 'config.json').write_text('{bad')
    with pytest.raises(ValueError):
        registry.ensure_default(tmp_path / 'project')
    assert not registry.index.exists()
    assert (legacy / 'config.json').read_text() == '{bad'


def test_failed_atomic_publish_rolls_back_new_workspace(registry, monkeypatch):
    registry.create('main')
    original = registry.index.read_bytes()
    from core import account_workspaces
    real_replace = account_workspaces.os.replace
    def fail_index(source, destination):
        if Path(destination) == registry.index:
            raise OSError('simulated disk error')
        return real_replace(source, destination)
    monkeypatch.setattr(account_workspaces.os, 'replace', fail_index)
    with pytest.raises(OSError):
        registry.create('second')
    assert registry.index.read_bytes() == original
    assert not registry.workspace('account-002').exists()
    assert not list(registry.root.glob('accounts.json.*'))


def test_custom_knowledge_migrates_into_account(registry, tmp_path):
    legacy = registry.root / 'Data'
    legacy.mkdir(parents=True)
    custom = tmp_path / 'custom-kb'
    custom.mkdir()
    (custom / 'note.md').write_text('custom note')
    (legacy / 'config.json').write_text(json.dumps({'knowledge_base_dir': str(custom)}))
    first = registry.ensure_default(tmp_path / 'project')
    workspace = Path(first['workspace'])
    assert (workspace / 'KnowledgeBase' / 'note.md').read_text() == 'custom note'
    assert 'knowledge_base_dir' not in json.loads((workspace / 'Data' / 'config.json').read_text())
    assert (custom / 'note.md').read_text() == 'custom note'
