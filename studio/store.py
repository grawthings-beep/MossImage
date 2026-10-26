"""Small durable store. Only the server writes project/job state."""
import json
from pathlib import Path
import sqlite3
import time


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'assets').mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / 'studio.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS documents (kind TEXT, id TEXT, updated REAL, data TEXT, PRIMARY KEY(kind,id))')
        self.db.commit()

    def get(self, kind, key):
        row = self.db.execute('SELECT data FROM documents WHERE kind=? AND id=?', (kind, key)).fetchone()
        if row is None:
            raise KeyError(key)
        return json.loads(row[0])

    def list(self, kind):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM documents WHERE kind=? ORDER BY updated DESC', (kind,))]

    def put(self, kind, data):
        with self.db:
            self.db.execute('INSERT INTO documents VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET updated=excluded.updated,data=excluded.data',
                            (kind, data['id'], time.time(), json.dumps(data, ensure_ascii=False)))

    def project(self, data):
        try:
            previous = self.get('project', data['id'])
        except KeyError:
            previous = None
        if previous and data['revision'] != previous['revision']:
            raise Conflict('別の画面で更新されています。再読込してから編集してください。')
        data['revision'] = (previous['revision'] if previous else 0) + 1
        self.put('project', data)
        return data

    def asset_path(self, key):
        # Resolve only asset IDs recorded by this server; no client file paths.
        self.get('asset', key)
        return self.root / 'assets' / (key + '.png')

    def close(self):
        self.db.close()
