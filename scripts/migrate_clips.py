"""给已有库建 clips 表(本仓库无迁移工具;新库由 create_all 自动建)。

幂等:表已存在则跳过。用法(先停后端,避免 SQLite 排他锁):
    .venv/bin/python scripts/migrate_clips.py
"""
import asyncio

from sqlalchemy import inspect

from drama_agent.db import session as db_session
from drama_agent.db.models import Base, Clip


def _has_clips(conn) -> bool:
    return "clips" in inspect(conn).get_table_names()


async def main() -> None:
    # dispose 放 finally:aiosqlite 的工作线程是非 daemon 的,不 dispose 就可能
    # 让脚本进程挂着不退。"表已存在"是最常走的那条路径,提前 return 尤其要覆盖到。
    try:
        async with db_session.engine.begin() as conn:
            if await conn.run_sync(_has_clips):
                print("clips 表已存在,跳过")
                return
            await conn.run_sync(Base.metadata.create_all, tables=[Clip.__table__])
            print("clips 表已建")
    finally:
        await db_session.engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
