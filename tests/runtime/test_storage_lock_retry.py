"""SQLite write-lock retry regressions."""
import sqlite3
import unittest
from contextlib import contextmanager

from social_operations.storage import Store


class FakeDB:
    def __init__(self, *, error='database is locked'):
        self.error = error
        self.begin_attempts = 0
        self.commits = 0
        self.rollbacks = 0

    def execute(self, sql, *args):
        if sql == 'BEGIN IMMEDIATE':
            self.begin_attempts += 1
            if self.begin_attempts == 1:
                raise sqlite3.OperationalError(self.error)
        return self

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class StubStore(Store):
    def __init__(self, db):
        self._db = db

    @contextmanager
    def connection(self):
        yield self._db


class StorageLockRetryTests(unittest.TestCase):
    def test_tx_retries_one_locked_begin_instead_of_crashing_worker(self):
        db = FakeDB()
        store = StubStore(db)
        with store.tx():
            pass
        self.assertEqual(db.begin_attempts, 2)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)

    def test_tx_does_not_retry_unrelated_sqlite_errors(self):
        db = FakeDB(error='disk I/O error')
        store = StubStore(db)
        with self.assertRaises(sqlite3.OperationalError):
            with store.tx():
                pass
        self.assertEqual(db.begin_attempts, 1)
        self.assertEqual(db.commits, 0)


if __name__ == '__main__':
    unittest.main()
