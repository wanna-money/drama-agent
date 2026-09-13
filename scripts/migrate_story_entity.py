"""把 1:1 的 Script(原文+剧本同一行)迁成 1:N 的 Story ← Script。

做四件事,幂等(可反复跑):
  1. 建 stories 表 + 给 scripts 加 story_id 列、给 episodes 加 story_id 列
     (本仓库无迁移工具,create_all 只建缺的表,加列须手动 ALTER)
  2. 每条已有 Script 的 source_text / story_analysis / cast 抽成一条 Story,
     Script.story_id 指向它
  3. Project.source_text(整本小说)抽成一条顶层 Story;该作品下由改编切出的剧本
     (自身没有 source_text)挂到它下面 —— 它们本就是这本小说的片段
  4. Episode.story_id 从它引用的 Script 回填(集的锚点从"方案"改成"原文")

用法(务必先停后端:SQLite 排他锁会让 ALTER 阻塞):
    uv run python scripts/migrate_story_entity.py
"""
import asyncio
import uuid

from sqlalchemy import text

from drama_agent.db import session as db_session
from drama_agent.db.models import Base


async def _columns(conn, table: str) -> set[str]:
    def _inspect(sync_conn):
        from sqlalchemy import inspect
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return set()
        return {c["name"] for c in insp.get_columns(table)}
    return await conn.run_sync(_inspect)


async def main() -> None:
    engine = db_session.engine
    is_sqlite = engine.dialect.name == "sqlite"

    # ① 建缺的表(stories)。create_all 只建不存在的表,已有表不动。
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # ② 加 scripts.story_id(有则跳过 —— 幂等)
    async with engine.begin() as conn:
        cols = await _columns(conn, "scripts")
        if "story_id" not in cols:
            await conn.execute(text("ALTER TABLE scripts ADD COLUMN story_id VARCHAR(36)"))
            print("scripts.story_id 已添加")
        else:
            print("scripts.story_id 已存在,跳过")
        # 索引:SQLite 与 PG 都支持 IF NOT EXISTS
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_scripts_story_id ON scripts (story_id)"))

    # ②' 加 episodes.story_id(集的锚点)。DB 上可空:给已有表加 NOT NULL 列在 SQLite
    # 要重建表;业务必填由 episode_service.create 强制。
    async with engine.begin() as conn:
        cols = await _columns(conn, "episodes")
        if "story_id" not in cols:
            await conn.execute(text("ALTER TABLE episodes ADD COLUMN story_id VARCHAR(36)"))
            print("episodes.story_id 已添加")
        else:
            print("episodes.story_id 已存在,跳过")
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_episodes_story_id ON episodes (story_id)"))

    now = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"

    async with engine.begin() as conn:
        # ③ Project.source_text → 顶层 Story(每个作品一条)
        projects = (await conn.execute(text(
            "SELECT id, title, genre, source_text, cast_analysis FROM projects "
            "WHERE source_text IS NOT NULL AND TRIM(source_text) <> ''"
        ))).mappings().all()
        project_story: dict[str, str] = {}
        for p in projects:
            # 幂等:该作品已有顶层 Story 就复用,不重复建
            existing = (await conn.execute(text(
                "SELECT id FROM stories WHERE project_id = :pid AND parent_id IS NULL "
                "ORDER BY created_at LIMIT 1"
            ), {"pid": p["id"]})).scalar()
            if existing:
                project_story[p["id"]] = existing
                continue
            sid = str(uuid.uuid4())
            await conn.execute(text(
                f"INSERT INTO stories (id, project_id, parent_id, order_index, title, genre,"
                f" content, story_analysis, \"cast\", created_at, updated_at)"
                f" VALUES (:id, :pid, NULL, 0, :title, :genre, :content, :analysis, NULL,"
                f" {now}, {now})"
            ), {"id": sid, "pid": p["id"], "title": p["title"], "genre": p["genre"],
                "content": p["source_text"], "analysis": p["cast_analysis"]})
            project_story[p["id"]] = sid
            print(f"作品「{p['title']}」的小说正文 → Story {sid[:8]}")

        # ④ 每条 Script → 一条 Story(或挂到作品的顶层 Story 下)
        scripts = (await conn.execute(text(
            "SELECT id, project_id, title, genre, source_text, story_analysis, \"cast\""
            " FROM scripts WHERE story_id IS NULL"
        ))).mappings().all()
        for sc in scripts:
            own_text = (sc["source_text"] or "").strip()
            parent = project_story.get(sc["project_id"]) if sc["project_id"] else None
            if own_text:
                # 自带原文 → 独立一条 Story(手工新建的剧本走这条)
                sid = str(uuid.uuid4())
                await conn.execute(text(
                    f"INSERT INTO stories (id, project_id, parent_id, order_index, title,"
                    f" genre, content, story_analysis, \"cast\", created_at, updated_at)"
                    f" VALUES (:id, :pid, NULL, 0, :title, :genre, :content, :analysis,"
                    f" :cast, {now}, {now})"
                ), {"id": sid, "pid": sc["project_id"], "title": sc["title"],
                    "genre": sc["genre"], "content": own_text,
                    "analysis": sc["story_analysis"], "cast": sc["cast"]})
            elif parent:
                # 无原文但属于有小说的作品 → 它是那本小说的切片:建一条子 Story 占位。
                # content 留空:旧数据里这段原文压根没保存过(那正是 1:1 的缺陷),
                # 不能凭剧本正文倒推 —— 那会把剧本当成原文,后续"重新改编"就是改编剧本。
                sid = str(uuid.uuid4())
                await conn.execute(text(
                    f"INSERT INTO stories (id, project_id, parent_id, order_index, title,"
                    f" genre, content, story_analysis, \"cast\", created_at, updated_at)"
                    f" VALUES (:id, :pid, :parent, 0, :title, :genre, NULL, :analysis,"
                    f" :cast, {now}, {now})"
                ), {"id": sid, "pid": sc["project_id"], "parent": parent,
                    "title": sc["title"], "genre": sc["genre"],
                    "analysis": sc["story_analysis"], "cast": sc["cast"]})
            else:
                # 既无原文也无小说来源(如从剧集存入的散稿)→ 建一条空原文,保住 1:N 形状。
                # 留 story_id 为空会让下游"取原文"到处判 None,而那正是要消除的分叉。
                sid = str(uuid.uuid4())
                await conn.execute(text(
                    f"INSERT INTO stories (id, project_id, parent_id, order_index, title,"
                    f" genre, content, story_analysis, \"cast\", created_at, updated_at)"
                    f" VALUES (:id, :pid, NULL, 0, :title, :genre, NULL, :analysis,"
                    f" :cast, {now}, {now})"
                ), {"id": sid, "pid": sc["project_id"], "title": sc["title"],
                    "genre": sc["genre"], "analysis": sc["story_analysis"],
                    "cast": sc["cast"]})
            await conn.execute(text(
                "UPDATE scripts SET story_id = :sid WHERE id = :id"
            ), {"sid": sid, "id": sc["id"]})
        print(f"已迁移 {len(scripts)} 条剧本")

        # ⑤ Episode.story_id ← 它引用的 Script 的 story_id(集的锚点从"方案"改成"原文")。
        # 只填空的,幂等。填不上的(script_id 指向已删剧本)留空:那种集本就跑不起来,
        # 猜一个原文只会让它跑出错误的内容。
        filled = (await conn.execute(text(
            "UPDATE episodes SET story_id = ("
            "  SELECT s.story_id FROM scripts s WHERE s.id = episodes.script_id"
            ") WHERE story_id IS NULL AND script_id IS NOT NULL"
        ))).rowcount
        print(f"已回填 {filled} 条剧集的 story_id")
        orphan = (await conn.execute(text(
            "SELECT COUNT(*) FROM episodes WHERE story_id IS NULL"))).scalar()
        if orphan:
            print(f"⚠️  {orphan} 条剧集仍无 story_id(源剧本已删?)——"
                  "它们取不到原文,开拍会失败,需人工指定或删除")

    await engine.dispose()
    print("迁移完成。Script 上的 source_text / story_analysis / cast 三列保留未删 ——"
          "确认无误后可手动 DROP。")


if __name__ == "__main__":
    asyncio.run(main())
