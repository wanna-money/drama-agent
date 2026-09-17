"""给已有库补 episodes.shots_versions / shots_version_current(幂等)。

本项目无迁移工具:`create_all` 只建新表、不会 ALTER 已存在的表。
列已存在则跳过,可重复执行。存量行的版本树留空(读侧 _effective_shots_versions
会从 state_snapshot.shots 现算出一条"初稿",不需要在此回填)。
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
                    .get_columns("episodes")
                ]
            )
            added = []
            if "shots_versions" not in cols:
                json_type = "JSONB" if dialect == "postgresql" else "JSON"
                await conn.execute(text(f"ALTER TABLE episodes ADD COLUMN shots_versions {json_type}"))
                added.append("shots_versions")
            if "shots_version_current" not in cols:
                await conn.execute(text(
                    "ALTER TABLE episodes ADD COLUMN shots_version_current INTEGER NOT NULL DEFAULT 0"
                ))
                added.append("shots_version_current")
            if not added:
                print("shots_versions / shots_version_current 已存在,跳过")
                return
            print(f"已添加 {', '.join(added)}({dialect})")
    finally:
        # aiosqlite 的工作线程是非 daemon 的:不 dispose 进程不会退出。
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
