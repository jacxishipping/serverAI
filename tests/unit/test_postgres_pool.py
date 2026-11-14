from __future__ import annotations

import sys
from types import ModuleType

from ai_bridge.control import db


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self.rowcount = 1
        self.lastrowid = None

    def execute(self, sql, parameters=()):
        self.conn.calls.append((sql, parameters))
        if sql.startswith("SELECT"):
            self.description = [("value",)]
        if "FAIL" in sql:
            raise RuntimeError("query failed")

    def fetchall(self):
        return [("ok",)]


class FakeConnection:
    def __init__(self):
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakePool:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.conn = FakeConnection()
        self.checked_out = 0
        self.returned = 0
        self.closed = False

    def getconn(self, timeout):
        self.checked_out += 1
        return self.conn

    def putconn(self, conn):
        self.returned += 1

    def close(self):
        self.closed = True


def make_db(monkeypatch):
    module = ModuleType("psycopg_pool")
    module.ConnectionPool = FakePool
    monkeypatch.setitem(sys.modules, "psycopg_pool", module)
    return db.PostgresConnection("postgresql://unused")


def test_postgres_read_releases_clean_connection(monkeypatch):
    conn = make_db(monkeypatch)
    result = conn.execute("SELECT value FROM sample WHERE id=?", (1,))
    assert result.fetchone()["value"] == "ok"
    assert conn._pool.checked_out == 1
    assert conn._pool.returned == 1
    assert conn._pool.conn.rollbacks == 1


def test_postgres_write_holds_connection_until_commit(monkeypatch):
    conn = make_db(monkeypatch)
    conn.execute("UPDATE sample SET value=?", ("x",))
    assert conn._pool.returned == 0
    conn.commit()
    assert conn._pool.conn.commits == 1
    assert conn._pool.returned == 1


def test_postgres_transaction_commits_and_releases_once(monkeypatch):
    conn = make_db(monkeypatch)
    with conn.transaction():
        conn.execute("UPDATE sample SET value=?", ("x",))
        conn.execute("UPDATE sample SET value=?", ("y",))
    assert conn._pool.checked_out == 1
    assert conn._pool.conn.commits == 1
    assert conn._pool.returned == 1


def test_postgres_failed_statement_rolls_back_and_releases(monkeypatch):
    conn = make_db(monkeypatch)
    try:
        conn.execute("UPDATE sample SET value=FAIL")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected query failure")
    assert conn._pool.conn.rollbacks == 1
    assert conn._pool.returned == 1
