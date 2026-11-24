"""One aiosqlite connection behind a lock. Use db.tx() for multi-statement writes."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from sage.schema import SCHEMA


class _Ops:
    def __init__(self, conn):
        self._c = conn

    async def execute(self, sql, params=()):
        cur = await self._c.execute(sql, params)
        return cur.lastrowid

    async def fetchone(self, sql, params=()):
        cur = await self._c.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql, params=()):
        cur = await self._c.execute(sql, params)
        return [dict(r) for r in await cur.fetchall()]


class Database(_Ops):
    def __init__(self, path):
        super().__init__(None)
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def connect(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._c = await aiosqlite.connect(self._path)
        self._c.row_factory = aiosqlite.Row
        await self._c.execute("PRAGMA journal_mode=WAL")
        await self._c.execute("PRAGMA foreign_keys=ON")
        await self._c.executescript(SCHEMA)
        await self._c.commit()

    async def close(self):
        await self._c.close()

    async def execute(self, sql, params=()):
        async with self.tx() as t:
            return await t.execute(sql, params)

    async def fetchone(self, sql, params=()):
        async with self._lock:
            return await super().fetchone(sql, params)

    async def fetchall(self, sql, params=()):
        async with self._lock:
            return await super().fetchall(sql, params)

    @asynccontextmanager
    async def tx(self):
        async with self._lock:
            try:
                yield _Ops(self._c)
                await self._c.commit()
            except BaseException:
                await self._c.rollback()
                raise
