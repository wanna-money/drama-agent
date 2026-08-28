"""角色身份对齐(cast)的行为测试。

拦的是真实回归:LLM 造野名字导致"角色管理与剧本人物对不上"、未确认的名字自动变实体、
停在没有 resume 入口的中断点、改名后外貌描述失联。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _char(cid: str, name: str, appearance: str | None = None):
    m = MagicMock()
    m.id = cid
    m.name = name
    m.appearance = appearance
    m.description = None
    return m


def _analysis(names=("林夏", "陆沉"), new_names=()):
    return {
        "title": "T",
        "characters": [{"name": n, "appearance": f"{n}的外貌"} for n in names],
        "new_characters": [{"name": n, "appearance": f"{n}的外貌"} for n in new_names],
    }


# ── A1:已有角色作为硬约束下发 ────────────────────────────────────────
def test_prompt_carries_existing_cast_as_constraint():
    """作品已有角色时,prompt 必须带上名单并要求只从中选用。

    约束丢了 LLM 就会继续发明名字,与用户手建的角色各自为政 —— 这正是用户反馈的割裂。
    """
    from drama_agent.workflow.nodes.story_analyzer import build_prompt
    _sys, user = build_prompt("故事正文", "drama", [
        {"name": "路人甲-女1", "appearance": "白衬衫黑裤"},
    ])
    assert "路人甲-女1" in user
    assert "白衬衫黑裤" in user
    assert "只能" in user            # 硬约束措辞在位
    assert "new_characters" in user  # 名单外的新人物有单独去处,不混进 characters


def test_prompt_without_existing_cast_has_no_roster_block():
    """全新作品(还没有角色)不加约束 —— 此时没有可对齐的对象,抽取结果就是角色库初值。"""
    from drama_agent.workflow.nodes.story_analyzer import build_prompt
    _sys, user = build_prompt("故事正文", "drama", [])
    assert "EXISTING CAST" not in user


@pytest.mark.asyncio
async def test_story_analyzer_does_not_create_characters():
    """story_analyzer **不得**再建角色实体 —— 身份要由 cast_review 人工确认后才落库。

    旧实现在这里 auto-provision,LLM 造的名字直接变成实体,是割裂的源头。
    """
    import drama_agent.workflow.nodes.story_analyzer as sa
    created = []
    with patch.object(sa.llm_service, "complete_json", AsyncMock(return_value=_analysis())), \
         patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[])), \
         patch("drama_agent.services.character_entity_service.create_character",
               AsyncMock(side_effect=lambda *a, **k: created.append(a))):
        out = await sa.story_analyzer_node({
            "raw_input": "x", "genre": "drama", "project_id": "p1",
            "title": "T", "llm_model": None})
    assert created == []
    assert out["story_analysis"]["title"] == "T"


@pytest.mark.asyncio
async def test_story_analyzer_survives_cast_lookup_failure():
    """角色库读不到时退回无约束分析,不阻断出片。"""
    import drama_agent.workflow.nodes.story_analyzer as sa
    with patch.object(sa.llm_service, "complete_json", AsyncMock(return_value=_analysis())), \
         patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(side_effect=RuntimeError("db down"))):
        out = await sa.story_analyzer_node({
            "raw_input": "x", "genre": "drama", "project_id": "p1",
            "title": "T", "llm_model": None})
    assert out["story_analysis"]["title"] == "T"


# ── A2:解析与确认 ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_resolve_matches_existing_and_flags_unknown():
    from drama_agent.services import cast_service
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "陆沉")])):
        out = await cast_service.resolve("p1", _analysis(names=("林夏", "陆沉")))
    assert out["cast"] == {"陆沉": "c1"}
    assert [p["name"] for p in out["pending"]] == ["林夏"]
    # 候选项由后端算好下发,前端不再自己拉一次角色列表(规范 4)
    assert out["pending"][0]["suggestions"] == [{"character_id": "c1", "name": "陆沉"}]


@pytest.mark.asyncio
async def test_resolve_includes_new_characters_field():
    """LLM 按约束把名单外的人放进 new_characters —— 那些同样要确认身份,不能漏掉。"""
    from drama_agent.services import cast_service
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "陆沉")])):
        out = await cast_service.resolve("p1", _analysis(names=("陆沉",), new_names=("新人",)))
    assert [p["name"] for p in out["pending"]] == ["新人"]


@pytest.mark.asyncio
async def test_resolve_does_not_block_when_roster_unreadable():
    """角色库读不到时不能把所有人都判成待确认 —— 那会把用户堵在确认步。"""
    from drama_agent.services import cast_service
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(side_effect=RuntimeError("db down"))):
        out = await cast_service.resolve("p1", _analysis())
    assert out["pending"] == []


@pytest.mark.asyncio
async def test_apply_decisions_links_and_creates():
    from drama_agent.services import cast_service
    created = []

    async def _create(pid, name, appearance=None):
        created.append((name, appearance))
        return _char(f"new-{name}", name, appearance)

    with patch("drama_agent.services.character_entity_service.create_character", _create):
        cast = await cast_service.apply_decisions(
            "p1", _analysis(names=("林夏", "陆沉")),
            {"林夏": {"action": "link", "character_id": "c9"},
             "陆沉": {"action": "create"}},
        )
    assert cast["林夏"] == "c9"          # 关联到已有角色
    assert cast["陆沉"] == "new-陆沉"     # 新建
    assert created == [("陆沉", "陆沉的外貌")]   # 建实体时带上 AI 抽的外貌,省得用户重填


@pytest.mark.asyncio
async def test_apply_decisions_creates_when_decision_missing():
    """没给决策的角色按新建处理 —— 悄悄丢掉它会让下游永远取不到该角色的图/外貌。"""
    from drama_agent.services import cast_service
    with patch("drama_agent.services.character_entity_service.create_character",
               AsyncMock(side_effect=lambda p, n, a=None: _char(f"new-{n}", n, a))):
        cast = await cast_service.apply_decisions("p1", _analysis(names=("林夏",)), {})
    assert cast["林夏"] == "new-林夏"


# ── A2:中断行为 ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cast_review_does_not_interrupt_when_nothing_pending():
    """无待确认项时不得中断 —— 停在一个前端没有 resume 入口的中断点会让整集卡死
    (look_review 踩过一次,见 graph.py 里那段注释)。"""
    from drama_agent.workflow.graph import cast_review_node
    out = await cast_review_node({
        "project_id": "p1", "story_analysis": _analysis(),
        "cast": {"林夏": "c1"}, "cast_pending": []})
    assert out["current_stage"] == "cast_confirmed"


@pytest.mark.asyncio
async def test_cast_resolve_writes_pending_into_state():
    """待确认清单必须落进状态:interrupt 载荷不进 state,前端读的是 status 投影 ——
    不写的话面板拿不到"要确认什么"。"""
    from drama_agent.workflow.graph import cast_resolve_node
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[])):
        out = await cast_resolve_node({"project_id": "p1", "story_analysis": _analysis()})
    assert [p["name"] for p in out["cast_pending"]] == ["林夏", "陆沉"]
    assert out["current_stage"] == "cast_resolved"


# ── B:外貌按 id 取,改名不断链 ────────────────────────────────────────
@pytest.mark.asyncio
async def test_prompt_engineer_reads_appearance_by_character_id():
    """按 cast 的 character_id 取外貌 —— 角色改名后仍取得到。

    退回按名字 join 就会在改名后静默丢掉外貌描述(视频里角色形象随之漂移)。
    """
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node
    shot = {"shot_id": "s1", "scene_number": 1, "shot_type": "MS", "camera_movement": "static",
            "duration_seconds": 5, "description": "d", "characters": ["改过的新名"],
            "dialogue": "", "action": "a", "location": "l"}
    captured = {}

    async def _complete_json(system, user, **kw):
        captured["user"] = user
        return {"prompt_text": "p", "negative_prompt": "n"}

    with patch("drama_agent.services.llm_service.llm_service.complete_json", _complete_json), \
         patch("drama_agent.services.character_entity_service.get_appearance",
               AsyncMock(return_value="长发白裙")):
        out = await prompt_engineer_node({
            "shots": [shot], "project_id": "p1", "video_provider": "seedance",
            "llm_model": None, "cast": {"改过的新名": "c1"}, "references": []})
    assert out["prompts"][0]["prompt_text"] == "p"
    assert "长发白裙" in captured["user"]


@pytest.mark.asyncio
async def test_prompt_engineer_skips_characters_absent_from_cast():
    """cast 里没有的名字不去猜 —— 按名字兜底就是刚被消除的那条脆弱路径。"""
    from drama_agent.workflow.nodes.prompt_engineer import prompt_engineer_node
    shot = {"shot_id": "s1", "scene_number": 1, "shot_type": "MS", "camera_movement": "static",
            "duration_seconds": 5, "description": "d", "characters": ["查无此人"],
            "dialogue": "", "action": "a", "location": "l"}
    get_app = AsyncMock(return_value="不该被取到")
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               AsyncMock(return_value={"prompt_text": "p", "negative_prompt": "n"})), \
         patch("drama_agent.services.character_entity_service.get_appearance", get_app):
        await prompt_engineer_node({
            "shots": [shot], "project_id": "p1", "video_provider": "seedance",
            "llm_model": None, "cast": {}, "references": []})
    get_app.assert_not_called()


# ── A(下游约束):写剧本/分镜不得发明名单外的具名角色 ──────────────────
def test_screenplay_prompt_carries_confirmed_cast():
    """已确认阵容要作为硬约束传给编剧 —— 否则写剧本时 LLM 自己加的角色没有
    character_id,拿不到造型与外貌,视频里形象逐镜漂移。"""
    from drama_agent.workflow.nodes.screenplay_writer import build_prompt
    _sys, user = build_prompt({"title": "T", "characters": []}, 120,
                              cast_names=["店员", "林夏"])
    assert "店员" in user and "林夏" in user
    assert "只能" in user
    assert "characters 字段" in user      # 群演的出路(不给名字)也要交代


def test_storyboard_prompt_carries_confirmed_cast():
    from drama_agent.workflow.nodes.storyboard_director import build_prompt
    _sys, user = build_prompt("剧本正文", {"characters": []}, 120, cast_names=["店员"])
    assert "店员" in user and "只能" in user


def test_no_cast_block_when_roster_empty():
    """无阵容(复用剧本直达分镜)时不下发空约束段 —— 空名单的"只能用这些名字"
    会把 LLM 逼进无角色可用的死角。"""
    from drama_agent.workflow.nodes.storyboard_director import build_prompt
    _sys, user = build_prompt("剧本正文", {"characters": []}, 120, cast_names=[])
    assert "CONFIRMED CAST" not in user


def test_storyboard_drops_off_roster_characters():
    """prompt 约束是软的,LLM 仍会发明人物 → 必须在落状态前把名单外的名字过滤掉。

    留着它们,下游按 character_id 取造型/外貌必然落空,该角色每个镜头长相都不同;
    丢掉则退化为"无名群演"(仍在 action 里),形象由文本引导 —— 可接受的降级。
    这条删掉就放走"分镜出现阵容外角色"的回归(E2E 实测出过)。
    """
    from drama_agent.workflow.nodes.storyboard_director import _filter_cast
    kept = _filter_cast(["店员", "女人"], ["店员"], 0)
    assert kept == ["店员"]


def test_storyboard_keeps_all_when_no_roster():
    """没有名单时不过滤 —— 那时没有依据,全丢会让所有镜头都没有角色。"""
    from drama_agent.workflow.nodes.storyboard_director import _filter_cast
    assert _filter_cast(["女人", "店员"], [], 0) == ["女人", "店员"]


def test_storyboard_filter_tolerates_non_list():
    """LLM 给 characters 一个非列表值时不得崩(脏数据容错)。"""
    from drama_agent.workflow.nodes.storyboard_director import _filter_cast
    assert _filter_cast("店员", ["店员"], 0) == []


@pytest.mark.asyncio
async def test_storyboard_node_actually_filters_off_roster():
    """走整个节点验证过滤**已接线** —— 只测 _filter_cast 函数的话,删掉调用点测试照过,
    而调用点恰是最容易被误删的地方(E2E 实测到的"分镜出现阵容外角色"就在这一层)。"""
    from drama_agent.workflow.nodes.storyboard_director import storyboard_director_node
    llm_shots = [{
        "scene_number": 1, "shot_number": 1, "shot_type": "MS", "camera_movement": "static",
        "duration_seconds": 5, "location": "便利店", "description": "d",
        "characters": ["店员", "女人"], "action": "a", "dialogue": "",
    }]
    with patch("drama_agent.services.llm_service.llm_service.complete_json",
               AsyncMock(return_value=llm_shots)), \
         patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "店员")])):
        out = await storyboard_director_node({
            "screenplay": "正文", "story_analysis": {"characters": []},
            "project_id": "p1", "target_seconds": 60, "llm_model": None,
            "cast": {"店员": "c1"},          # 女人不在阵容内
            "storyboard_revision_notes": "",
        })
    assert out["shots"][0]["characters"] == ["店员"]


@pytest.mark.asyncio
async def test_roster_prefers_character_table_over_state():
    """名单以角色库为准:cast 写入状态后,下游节点读它要跨 interrupt 的状态合并边界,
    时序上不可靠(实测过分镜拿到空 cast 而放过了名单外角色)。库是作品级持久权威。"""
    from drama_agent.services import cast_service
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(return_value=[_char("c1", "店员"), _char("c2", "夜客")])):
        names = await cast_service.roster_names("p1", state_cast=None)   # state 里没有
    assert names == ["夜客", "店员"]


@pytest.mark.asyncio
async def test_roster_falls_back_to_state_when_table_unreadable():
    """库读不到时退回 state 的键 —— 空名单会让下游的约束段整体消失。"""
    from drama_agent.services import cast_service
    with patch("drama_agent.services.character_entity_service.list_characters",
               AsyncMock(side_effect=RuntimeError("db down"))):
        names = await cast_service.roster_names("p1", {"店员": "c1"})
    assert names == ["店员"]


# ── B(外貌回填):link 到已有角色时补外貌 ──────────────────────────────
@pytest.mark.asyncio
async def test_link_backfills_appearance_when_missing():
    """link 到还没有外貌的已有角色时,用本次分析抽出的外貌补上。

    不补的话下游 prompt 只能回落到简略的 description,视频里的角色形象大幅缩水
    (实测:LLM 抽出了详细外貌,但因走 link 分支而丢失)。
    """
    from drama_agent.services import cast_service
    updated = {}
    with patch("drama_agent.services.character_entity_service.get_appearance",
               AsyncMock(return_value=None)), \
         patch("drama_agent.services.character_entity_service.update_character",
               AsyncMock(side_effect=lambda cid, **kw: updated.update({cid: kw}))):
        await cast_service.apply_decisions(
            "p1", _analysis(names=("林夏",)),
            {"林夏": {"action": "link", "character_id": "c9"}})
    assert updated == {"c9": {"appearance": "林夏的外貌"}}


@pytest.mark.asyncio
async def test_link_does_not_overwrite_existing_appearance():
    """已有外貌不覆盖 —— 那可能是用户手写或前几集沉淀的,比单次分析更可信。"""
    from drama_agent.services import cast_service
    upd = AsyncMock()
    with patch("drama_agent.services.character_entity_service.get_appearance",
               AsyncMock(return_value="用户手写的外貌")), \
         patch("drama_agent.services.character_entity_service.update_character", upd):
        await cast_service.apply_decisions(
            "p1", _analysis(names=("林夏",)),
            {"林夏": {"action": "link", "character_id": "c9"}})
    upd.assert_not_called()
