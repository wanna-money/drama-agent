"""给已有库补 custom_providers.config_json(幂等)。

本项目无迁移工具:`create_all` 只建新表、不会 ALTER 已存在的表。
列已存在则跳过,可重复执行。
"""
import asyncio

from sqlalchemy import text

from drama_agent.db.session import engine


async def main() -> None:
    dialect = engine.dialect.name
    try:
        async with engine.begin() as conn:
            cols = await conn.run_sync(
                lambda sync_conn: [
                    c["name"] for c in
                    __import__("sqlalchemy").inspect(sync_conn)
                    .get_columns("custom_providers")
                ]
            )
            if "config_json" in cols:
                print("config_json 已存在,跳过")
                return
            ddl = ("ALTER TABLE custom_providers ADD COLUMN config_json JSONB "
                   "DEFAULT '{}'::jsonb" if dialect == "postgresql"
                   else "ALTER TABLE custom_providers ADD COLUMN config_json JSON")
            await conn.execute(text(ddl))
            print(f"已添加 config_json({dialect})")
    finally:
        # aiosqlite 的工作线程是非 daemon 的:不 dispose 进程不会退出。
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
