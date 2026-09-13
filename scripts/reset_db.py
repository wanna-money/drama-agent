"""重置开发库:drop 库里全部业务表,保留 custom_providers(界面 provider 凭证)。

「清库重来」用。custom_providers **整表保留**(不 drop),故凭证零风险;其余业务表 drop
后由 create_all 重建为空表(本仓库无迁移工具,建表靠 create_all)。

清理范围以**库里实际存在的表**为准,不以 Base.metadata 为准:模型删掉后它的表不再出现
在 metadata 里,按 metadata 清理会把这类残表永久留在库里 —— 而残表的旧列会让"清库重来"
得到一个并不干净的库。

langgraph checkpointer 是另一个 sqlite 文件(settings.langgraph_db_path),不在本脚本内,
需在后端停机后单独删除文件以获得干净分镜/图状态。

用法(务必先停后端,否则 SQLite 排他锁会让 DROP 阻塞/报 database is locked):
    uv run python scripts/reset_db.py
"""
import asyncio

from sqlalchemy import text

from drama_agent.db import session as db_session
from drama_agent.db.models import Base

# 只保留 provider 凭证表;其余业务表全部清空重建。
KEEP = {"custom_providers"}


def live_tables(conn) -> list[str]:
    """库里实际存在的表名(同步回调,供 run_sync 调用)。"""
    from sqlalchemy import inspect
    return list(inspect(conn).get_table_names())


async def main() -> None:
    engine = db_session.engine
    async with engine.begin() as conn:
        existing = await conn.run_sync(live_tables)
        known = {t.name for t in Base.metadata.sorted_tables}
        # 已建模的表按依赖倒序先 drop(无真实 FK,顺序其实无所谓,但保持规范);
        # 其余是模型已删除留下的残表,一并清掉。
        ordered = [t.name for t in reversed(Base.metadata.sorted_tables)]
        orphans = sorted(set(existing) - known - KEEP)
        for name in [*ordered, *orphans]:
            if name in KEEP or name not in existing:
                continue
            await conn.execute(text(f"DROP TABLE IF EXISTS {name}"))
        if orphans:
            print(f"已清理残表(模型已删除): {', '.join(orphans)}")
        # 重建被 drop 的表(custom_providers 未 drop → create_all 跳过它,凭证不动)
        await conn.run_sync(Base.metadata.create_all)

    async with engine.connect() as conn:
        for t in ("projects", "stories", "episodes", "scripts", "custom_providers"):
            n = (await conn.execute(text(f"SELECT COUNT(*) FROM {t}"))).scalar()
            print(f"{t}: {n}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
