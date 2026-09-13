"""给已有 clips 表补 video_refs_json / task_type / storage_key(幂等)。

`create_all` 只建新表、不 ALTER 已存在的表。逐列检查,已存在则跳过。
"""
import asyncio

from sqlalchemy import inspect, text

from drama_agent.db.session import engine

_COLS = {
    "video_refs_json": ("JSON", "JSONB"),
    "task_type": ("VARCHAR(20) DEFAULT 'reference'", "VARCHAR(20) DEFAULT 'reference'"),
    "storage_key": ("TEXT", "TEXT"),
}


async def main() -> None:
    pg = engine.dialect.name == "postgresql"
    try:
        async with engine.begin() as conn:
            existing = await conn.run_sync(
                lambda c: [x["name"] for x in inspect(c).get_columns("clips")])
            for col, (sqlite_type, pg_type) in _COLS.items():
                if col in existing:
                    print(f"{col} 已存在,跳过")
                    continue
                await conn.execute(text(
                    f"ALTER TABLE clips ADD COLUMN {col} {pg_type if pg else sqlite_type}"))
                print(f"已添加 {col}")
    finally:
        # aiosqlite 的工作线程是非 daemon 的:不 dispose 进程不会退出
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
