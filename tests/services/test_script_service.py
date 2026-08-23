import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


@pytest.fixture
async def session():
    from drama_agent.db.models import Base
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        yield s
    await eng.dispose()


@pytest.mark.asyncio
async def test_create_list_update(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", genre="drama", source_text="故事")
    assert r["status"] == "created" and r["content"] is None
    assert any(x["id"] == r["id"] for x in await ss.list_scripts(session))
    upd = await ss.update(session, r["id"], title="T2", content="正文")
    assert upd["title"] == "T2" and upd["content"] == "正文"


@pytest.mark.asyncio
async def test_list_filter_by_project(session):
    from drama_agent.services import script_service as ss
    await ss.create(session, title="A", genre="drama", source_text="x", project_id="p1")
    await ss.create(session, title="B", genre="drama", source_text="y")  # 散稿
    assert len(await ss.list_scripts(session, project_id="p1")) == 1


@pytest.mark.asyncio
async def test_get_status_and_delete(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    st = await ss.get_status(session, r["id"])
    assert st["status"] == "created" and st["id"] == r["id"]
    assert await ss.delete(session, r["id"]) is True
    assert await ss.get(session, r["id"]) is None
    assert await ss.get_status(session, "no-such") is None


@pytest.mark.asyncio
async def test_append_screenplay_version_seeds_draft_then_appends(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]

    result = await ss.append_screenplay_version(
        session, sid, new_screenplay="改写后正文", seed_screenplay="初稿正文", label="改成搞笑风格",
    )

    assert result["screenplay"] == "改写后正文"
    assert result["version_index"] == 1
    assert result["versions_len"] == 2

    st = await ss.get_status(session, sid)
    assert st["screenplay_version_current"] == 1
    versions = st["screenplay_versions"]
    assert len(versions) == 2
    assert versions[0]["label"] == "初稿" and versions[0]["screenplay"] == "初稿正文"
    assert versions[1]["label"] == "改成搞笑风格" and versions[1]["screenplay"] == "改写后正文"


@pytest.mark.asyncio
async def test_append_screenplay_version_no_reseed_when_versions_exist(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]
    await ss.append_screenplay_version(
        session, sid, new_screenplay="v1", seed_screenplay="v0", label="第一次改",
    )

    result = await ss.append_screenplay_version(
        session, sid, new_screenplay="v2", seed_screenplay="v0(不应再被种)", label="第二次改",
    )

    assert result["version_index"] == 2
    assert result["versions_len"] == 3
    st = await ss.get_status(session, sid)
    assert [v["screenplay"] for v in st["screenplay_versions"]] == ["v0", "v1", "v2"]


@pytest.mark.asyncio
async def test_append_screenplay_version_missing_script_returns_none(session):
    from drama_agent.services import script_service as ss
    result = await ss.append_screenplay_version(
        session, "no-such", new_screenplay="x", seed_screenplay="y", label="l",
    )
    assert result is None


@pytest.mark.asyncio
async def test_set_current_version_switches_and_updates_snapshot(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]
    await ss.append_screenplay_version(
        session, sid, new_screenplay="v1", seed_screenplay="v0", label="改动",
    )

    result = await ss.set_current_version(session, sid, 0)

    assert result == {"screenplay": "v0", "version_index": 0}
    st = await ss.get_status(session, sid)
    assert st["screenplay_version_current"] == 0
    assert st["content"] == "v0"  # get_status 的 content 回落 state_snapshot.screenplay


@pytest.mark.asyncio
async def test_set_current_version_out_of_range_raises(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]
    await ss.append_screenplay_version(
        session, sid, new_screenplay="v1", seed_screenplay="v0", label="改动",
    )
    with pytest.raises(IndexError):
        await ss.set_current_version(session, sid, 99)


@pytest.mark.asyncio
async def test_set_current_version_missing_script_returns_none(session):
    from drama_agent.services import script_service as ss
    assert await ss.set_current_version(session, "no-such", 0) is None


@pytest.mark.asyncio
async def test_get_status_synthesizes_draft_version_when_none_stored(session):
    """剧本尚未调用过 revise/edit(versions 列仍空)但已有正文快照时,
    get_status 应合成一份「初稿」供前端版本下拉展示,而不是空列表。"""
    from drama_agent.db.models import Script
    from drama_agent.services import script_service as ss
    sid = "seed-1"
    session.add(Script(
        id=sid, title="剧", source_text="x", status="paused",
        state_snapshot={"screenplay": "第一场 海边", "paused_at": "screenplay_review"},
    ))
    await session.commit()

    st = await ss.get_status(session, sid)

    assert st["screenplay_versions"] == [
        {"screenplay": "第一场 海边", "label": "初稿", "created_at": None}
    ]
    assert st["screenplay_version_current"] == 0


@pytest.mark.asyncio
async def test_set_current_version_accepts_synthesized_draft(session):
    """get_status 合成出来的「初稿」(versions 列仍空)必须也能被 revert 选中 ——
    否则 status 端点刚广播存在的版本 0,/revert 却 422 说它不存在。"""
    from drama_agent.db.models import Script
    from drama_agent.services import script_service as ss
    sid = "synth-1"
    session.add(Script(
        id=sid, title="剧", source_text="x", status="paused",
        state_snapshot={"screenplay": "初稿正文", "paused_at": "screenplay_review"},
    ))
    await session.commit()
    st = await ss.get_status(session, sid)
    assert len(st["screenplay_versions"]) == 1  # 前端据此认为版本 0 可选

    result = await ss.set_current_version(session, sid, 0)

    assert result == {"screenplay": "初稿正文", "version_index": 0}
    st2 = await ss.get_status(session, sid)
    assert st2["screenplay_version_current"] == 0
    assert st2["content"] == "初稿正文"
    assert st2["paused_at"] == "screenplay_review"  # revert 不该抹掉快照其它键
    with pytest.raises(IndexError):  # 合成态只有版本 0,1 仍越界
        await ss.set_current_version(session, sid, 1)


@pytest.mark.asyncio
async def test_set_current_version_no_versions_no_screenplay_raises(session):
    """既无 versions 列也无正文 —— 没有任何版本可选,0 也必须越界。"""
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    assert (await ss.get_status(session, r["id"]))["screenplay_versions"] == []
    with pytest.raises(IndexError):
        await ss.set_current_version(session, r["id"], 0)


@pytest.mark.asyncio
async def test_reset_for_retry_clears_version_history(session):
    """retry 会清 checkpointer 线程从头重跑,版本历史属于被丢弃的那次运行必须一起清 ——
    否则重跑后 _effective_versions 看到非空的旧 versions 列就不再按新正文合成初稿,
    前端会拿旧运行的版本列表配新正文,/revert 还能把废弃正文写回新线程。"""
    from sqlalchemy import select

    from drama_agent.db.models import Script
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]
    await ss.append_screenplay_version(
        session, sid, new_screenplay="v1", seed_screenplay="v0", label="改动",
    )
    assert (await ss.get_status(session, sid))["screenplay_version_current"] == 1

    await ss.reset_for_retry(session, sid)

    row = (await session.execute(select(Script).where(Script.id == sid))).scalar_one()
    assert not row.screenplay_versions  # 旧运行的版本列表不得残留
    assert row.screenplay_version_current == 0
    # 版本列已空 → 读时合成路径重新接管(新正文产生后合成的初稿即新正文)
    assert (await ss.get_status(session, sid))["screenplay_version_current"] == 0


@pytest.mark.asyncio
async def test_get_status_clamps_current_index_when_no_versions(session):
    """versions 为空时当前下标必须被夹到 0 —— 后端保证 (versions, current) 恒自洽,
    否则前端 versions[current] 直接崩。"""
    from drama_agent.db.models import Script
    from drama_agent.services import script_service as ss
    sid = "clamp-1"
    session.add(Script(  # 绕过正常写路径直接造出越界组合
        id=sid, title="剧", source_text="x", status="queued",
        screenplay_versions=None, screenplay_version_current=3,
    ))
    await session.commit()

    st = await ss.get_status(session, sid)

    assert st["screenplay_versions"] == []
    assert st["screenplay_version_current"] == 0


@pytest.mark.asyncio
async def test_get_status_clamps_current_index_beyond_versions_len(session):
    """当前下标超出实际版本数时夹到最后一版,而不是原样透出越界值。"""
    from drama_agent.db.models import Script
    from drama_agent.services import script_service as ss
    sid = "clamp-2"
    session.add(Script(
        id=sid, title="剧", source_text="x", status="paused",
        screenplay_versions=[
            {"screenplay": "v0", "label": "初稿", "created_at": None},
            {"screenplay": "v1", "label": "改动", "created_at": None},
        ],
        screenplay_version_current=9,
    ))
    await session.commit()

    assert (await ss.get_status(session, sid))["screenplay_version_current"] == 1


@pytest.mark.asyncio
async def test_append_screenplay_version_label_stripped_and_truncated(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]

    await ss.append_screenplay_version(
        session, sid, new_screenplay="v1", seed_screenplay="v0", label="  前后有空格  ",
    )
    await ss.append_screenplay_version(
        session, sid, new_screenplay="v2", seed_screenplay="v0", label="改" * 100,
    )

    versions = (await ss.get_status(session, sid))["screenplay_versions"]
    assert versions[1]["label"] == "前后有空格"
    assert versions[2]["label"] == "改" * 80
    assert len(versions[2]["label"]) == 80


@pytest.mark.asyncio
async def test_append_screenplay_version_blank_label_falls_back(session):
    from drama_agent.services import script_service as ss
    r = await ss.create(session, title="T", source_text="故事")
    sid = r["id"]

    await ss.append_screenplay_version(
        session, sid, new_screenplay="v1", seed_screenplay="v0", label="   ",
    )

    versions = (await ss.get_status(session, sid))["screenplay_versions"]
    assert versions[1]["label"] == "改写"


@pytest.mark.asyncio
async def test_append_screenplay_version_preserves_other_snapshot_keys(session):
    """追加版本只该覆盖 state_snapshot.screenplay,paused_at 等其它键必须存活
    (get_status 要读 paused_at,整体替换快照会让前端丢掉审核位置)。"""
    from drama_agent.db.models import Script
    from drama_agent.services import script_service as ss
    sid = "snap-1"
    session.add(Script(
        id=sid, title="剧", source_text="x", status="paused",
        state_snapshot={
            "screenplay": "旧正文", "paused_at": "screenplay_review",
            "story_analysis": {"theme": "复仇"},
        },
    ))
    await session.commit()

    await ss.append_screenplay_version(
        session, sid, new_screenplay="新正文", seed_screenplay="旧正文", label="改一版",
    )

    st = await ss.get_status(session, sid)
    assert st["content"] == "新正文"
    assert st["paused_at"] == "screenplay_review"
    assert st["story_analysis"] == {"theme": "复仇"}
