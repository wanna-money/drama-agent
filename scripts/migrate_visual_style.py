"""给已有库补 projects.visual_style(幂等)。

本项目无迁移工具:`create_all` 只建新表、不会 ALTER 已存在的表。
列已存在则跳过,可重复执行。存量行回填为 'realistic',之后可在
作品设置里改成真正想要的风格。
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
                    .get_columns("projects")
                ]
            )
            if "visual_style" in cols:
                print("visual_style 已存在,跳过")
                return
            ddl = (
                "ALTER TABLE projects ADD COLUMN visual_style VARCHAR(20) "
                "NOT NULL DEFAULT 'realistic'"
            )
            await conn.execute(text(ddl))
            print(f"已添加 visual_style({dialect}),存量行回填为 'realistic'")
    finally:
        # aiosqlite 的工作线程是非 daemon 的:不 dispose 进程不会退出。
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
