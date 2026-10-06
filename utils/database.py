"""Transactional account document storage with lossless legacy JSON migration."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


_DIRECTORIES = {}


def register_directory(directory, database_directory=None):
    root = Path(directory).resolve()
    target = Path(database_directory).resolve() if database_directory is not None else root
    _DIRECTORIES[str(root).casefold()] = str(target)


def managed(path):
    path = Path(path).resolve()
    return path.suffix.lower() == '.json' and (
        path.parent.name.casefold() == 'data' or str(path.parent).casefold() in _DIRECTORIES)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


class DocumentDatabase:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.database_directory = Path(_DIRECTORIES.get(str(self.directory).casefold(), str(self.directory)))
        self.path = self.database_directory / 'account_data.sqlite3'

    def _record_name(self, name):
        return name if self.directory == self.database_directory else 'root/' + name

    @contextmanager
    def connect(self):
        self.database_directory.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute('PRAGMA busy_timeout=30000')
            connection.execute('PRAGMA journal_mode=WAL')
            connection.execute('PRAGMA synchronous=FULL')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS documents (
                    name TEXT PRIMARY KEY, payload TEXT NOT NULL CHECK(json_valid(payload)),
                    source_digest TEXT, revision INTEGER NOT NULL DEFAULT 1,
                    updated REAL NOT NULL, source_stamp TEXT);
                CREATE TABLE IF NOT EXISTS migration_originals (
                    name TEXT PRIMARY KEY, raw BLOB NOT NULL, source_digest TEXT NOT NULL,
                    migrated REAL NOT NULL);
                PRAGMA user_version=1;
            ''')
            if 'source_stamp' not in {row[1] for row in connection.execute('PRAGMA table_info(documents)')}:
                connection.execute('ALTER TABLE documents ADD COLUMN source_stamp TEXT')
            with connection:
                yield connection
        finally:
            connection.close()

    def _path(self, name):
        if not isinstance(name, str) or Path(name).name != name or not name.lower().endswith('.json'):
            raise ValueError('数据记录名称无效')
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory:
            raise ValueError('不允许读取目录外的JSON数据')
        return path

    def _sync(self, connection, name):
        path = self._path(name)
        name = self._record_name(name)
        row = connection.execute('SELECT payload,source_digest,source_stamp FROM documents WHERE name=?', (name,)).fetchone()
        if path.exists():
            stat = path.stat()
            stamp = f'{stat.st_mtime_ns}:{stat.st_size}'
            if row and row[2] == stamp:
                return json.loads(row[0])
            raw = path.read_bytes()
            signature = digest(raw)
            if not row or signature != row[1]:
                value = json.loads(raw.decode('utf-8-sig'))
                payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
                connection.execute('INSERT OR IGNORE INTO migration_originals VALUES(?,?,?,?)', (name, raw, signature, time.time()))
                connection.execute('''INSERT INTO documents(name,payload,source_digest,revision,updated,source_stamp) VALUES(?,?,?,1,?,?)
                    ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,
                    source_digest=excluded.source_digest,revision=documents.revision+1,updated=excluded.updated,source_stamp=excluded.source_stamp''',
                                   (name, payload, signature, time.time(), stamp))
                return value
            connection.execute('UPDATE documents SET source_stamp=? WHERE name=?', (stamp, name))
        elif row and row[1] is not None:
            connection.execute('DELETE FROM documents WHERE name=?', (name,))
            return None
        return json.loads(row[0]) if row else None

    def read(self, name, default=None):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            value = self._sync(connection, name)
            if value is None:
                row = connection.execute('SELECT payload FROM documents WHERE name=?', (self._record_name(name),)).fetchone()
                if row:
                    return json.loads(row[0])
            return default if value is None else value

    def write(self, name, value, mirror):
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
        path = self._path(name)
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._sync(connection, name)
            name = self._record_name(name)
            connection.execute('''INSERT INTO documents(name,payload,source_digest,revision,updated) VALUES(?,?,NULL,1,?)
                ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,
                revision=documents.revision+1,updated=excluded.updated''', (name, payload, time.time()))
            mirror(value, path)
            stat = path.stat()
            raw = path.read_bytes()
            connection.execute('INSERT OR IGNORE INTO migration_originals VALUES(?,?,?,?)', (name, raw, digest(raw), time.time()))
            connection.execute('UPDATE documents SET source_digest=?,source_stamp=? WHERE name=?',
                               (digest(raw), f'{stat.st_mtime_ns}:{stat.st_size}', name))

    def update(self, name, mutator, mirror):
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            value = self._sync(connection, name)
            if value is None:
                value = {}
            mutator(value)
            payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
            path = self._path(name)
            name = self._record_name(name)
            connection.execute('''INSERT INTO documents(name,payload,source_digest,revision,updated) VALUES(?,?,NULL,1,?)
                ON CONFLICT(name) DO UPDATE SET payload=excluded.payload,
                revision=documents.revision+1,updated=excluded.updated''', (name, payload, time.time()))
            mirror(value, path)
            stat = path.stat()
            raw = path.read_bytes()
            connection.execute('INSERT OR IGNORE INTO migration_originals VALUES(?,?,?,?)', (name, raw, digest(raw), time.time()))
            connection.execute('UPDATE documents SET source_digest=?,source_stamp=? WHERE name=?',
                               (digest(raw), f'{stat.st_mtime_ns}:{stat.st_size}', name))

    def exists(self, name):
        if self._path(name).exists():
            return True
        return False

    def migrate(self, include_root=False):
        sources = [self]
        if include_root and self.directory.name.casefold() == 'data':
            register_directory(self.directory.parent, self.database_directory)
            sources.append(DocumentDatabase(self.directory.parent))
        with self.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for source in sources:
                for path in sorted(source.directory.glob('*.json')):
                    source._sync(connection, path.name)
        return self.status()

    def status(self):
        with self.connect() as connection:
            records = [{'name': row[0], 'revision': row[1], 'updated': row[2], 'bytes': row[3]}
                       for row in connection.execute('SELECT name,revision,updated,length(CAST(payload AS BLOB)) FROM documents ORDER BY name')]
            originals = connection.execute('SELECT count(*) FROM migration_originals').fetchone()[0]
            healthy = connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        return {'backend': 'sqlite', 'schema_version': 1, 'records': records,
                'original_count': originals, 'healthy': healthy, 'json_compatibility': True}

    def snapshot(self, target):
        target = Path(target).resolve()
        if target == self.path:
            raise ValueError('备份路径不能覆盖当前数据库')
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
