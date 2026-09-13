import uuid
from typing import cast
import structlog
from drama_agent.workflow.state import DramaState, ShotDict
from drama_agent.workflow.constants import (
    ShotType, CameraMovement, ColorTemp, Lighting,
    DEFAULT_SHOT_DURATION, SHOT_TYPE_DESC,
    shot_duration_bounds,
)
from drama_agent.config import settings
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.cast_constraint import cast_constraint_block
from drama_agent.workflow.prompt_rules import system_prompt

logger = structlog.get_logger()

SYSTEM = system_prompt("""You are a professional film director and storyboard artist.
Break screenplays into individual shots for video production.
Each shot must be filmable as a single continuous clip within the duration range given below.""")


def _format_characters(analysis: dict) -> str:
    chars = (analysis or {}).get("characters", [])
    return "\n".join(
        f"- {c['name']}: {c['appearance']}"
        for c in chars
        if c.get("name") and c.get("appearance")
    )


def _shot_types_line() -> str:
    return ", ".join(f"{t.value} ({SHOT_TYPE_DESC[t.value]})" for t in ShotType)


def _camera_moves_line() -> str:
    return ", ".join(c.value for c in CameraMovement)


def _lighting_line() -> str:
    return ", ".join(m.value for m in Lighting)


def _color_temp_line() -> str:
    return ", ".join(m.value for m in ColorTemp)


def build_prompt(
    screenplay: str, analysis: dict, target_seconds: int | None = None,
    notes: str | None = None, cast_names: list[str] | None = None, model_ref: str = "",
) -> tuple[str, str]:
    """target_seconds:全片目标时长(秒),约束镜头总时长;缺省取 config 的 target_episode_seconds。
    notes:分镜被打回重做时的人工意见,拼进 prompt 尾部引导重生成(仿 prompt_engineer)。

    cast_names:已确认阵容,作为 shots[].characters 的**受约束取值**下发。名单外的名字
    进了 characters,下游按 character_id 取造型与外貌就会落空(该角色形象逐镜漂移)。

    model_ref:目标视频模型(用于 shot_duration_bounds 求交模型能力区间)。空串时退回
    纯叙事区间——分镜先于视频模型确定的路径(如复用剧本直达分镜)没有 model_ref 可传。
    """
    target_seconds = target_seconds or settings.target_episode_seconds
    # 下限随集级目标 × 模型能力变(shot_duration_bounds 是唯一权威);prompt 与收敛
    # 必须用同一个值,否则一边按模型下限收敛、另一边告诉模型下限是别的数。
    min_dur, max_dur = shot_duration_bounds(target_seconds, model_ref)
    guides = knowledge_store.retrieve("storyboard_guide")
    guide_block = "\n".join(f"- {g}" for g in guides)

    shot_lang = "\n\n".join(knowledge_store.retrieve("shot_language"))
    # 序列方法论管"镜与镜之间的节奏与因果",是防"动态 PPT"的关键 ——
    # 只给单镜语言(景别/角度/运镜)时,模型会产出等长、全 static、彼此孤立的镜头表。
    shot_seq = "\n\n".join(knowledge_store.retrieve("shot_sequence"))
    visual = "\n\n".join(knowledge_store.retrieve("visual_aesthetics"))
    # 运镜实战范例(按叙事目的组织)+ 群像站位锁定 —— 前者补 shot_language 的"选哪个
    # 运镜"落地范例,后者补三人以上场景才会暴露的站位崩坏问题(shot_language 的轴线
    # 准则只覆盖两人对话)。
    camera_prompts = "\n\n".join(knowledge_store.retrieve("camera_movement_prompts"))
    blocking = "\n\n".join(knowledge_store.retrieve("multi_character_blocking"))
    methodology_block = ""
    if shot_lang:
        methodology_block += f"\n\nShot-language methodology:\n{shot_lang}"
    if shot_seq:
        methodology_block += f"\n\nShot-sequence & rhythm methodology:\n{shot_seq}"
    if visual:
        methodology_block += f"\n\nVisual-aesthetics methodology:\n{visual}"
    if camera_prompts:
        methodology_block += f"\n\nCamera-movement prompt reference:\n{camera_prompts}"
    if blocking:
        methodology_block += f"\n\nMulti-character blocking methodology:\n{blocking}"

    user_prompt = f"""Break this screenplay into individual production shots.

SCREENPLAY:
{screenplay}

CHARACTER VISUAL REFERENCES:
{_format_characters(analysis)}{cast_constraint_block(cast_names)}

Rules for shots:
- shots[].characters 里只填已确认阵容里的名字;无名群演不进该字段(写在 action 里)
- 单镜时长 {min_dur}–{max_dur} 秒
- 全片目标时长约 {target_seconds} 秒:所有镜头 duration_seconds 之和应接近该值
  (约 {max(1, target_seconds // min_dur)} 个镜头上下),不要大幅超出
- Use shot types: {_shot_types_line()}
- Use camera movements: {_camera_moves_line()}
- lighting 取值: {_lighting_line()}
- color_temp 取值: {_color_temp_line()}
- **同一场景(scene_number 相同)的 lighting 与 color_temp 必须一致**:
  同一场戏里光线不该在镜间跳变。要变光就换场景,或让它随剧情推进(白天→黄昏)整段迁移
- 需要 <{min_dur} 秒的短促节拍时(击中/爆炸/惊吓/反转揭示),**不要单独成镜** ——
  视频模型收不下这么短的单支。把它与相邻节拍合并成一镜:`duration_seconds` 给合并后的
  总长(不低于 {min_dur}),`beats` 按顺序列出镜内节拍(自然语言,写明各自占多久)。
  例:击中(0.4s) + 跌出(1.6s) → 一镜 `duration_seconds: {min_dur}`,
  `beats: ["前 0.4 秒:拳头击中下颌,头部急偏", "随后:身体失衡跌出画面,烟尘扬起"]`。
  不需要镜内节拍的镜头,`beats` 给 null 或省略

节奏硬约束(违反其一即为"动态 PPT",见 shot-sequence 方法论第七节):
- **时长必须有变化**:同一场景内至少出现 3 种不同的 duration_seconds。
  全部相同(如每镜都 {DEFAULT_SHOT_DURATION}s)是最常见的失败 —— 那让成片像翻页 PPT
- **冲击性镜头取下限**:击中、爆炸、惊吓、反转揭示这类镜头用 {min_dur}s(允许的最短值,
  必要时用上面的 `beats` 合并短促节拍);建立/交代与情绪停留的镜头才用长时长
- **camera_movement 为 static 的镜头不得超过总数 1/3**:其余必须有运镜;
  即使 static,action 也必须描述**镜内运动**(主体动作 / 风雪烟尘等环境动势)
- **每个镜头的 action 必须含明确动词**:"站在崖边"不合格(那是状态),
  "风掀起衣袍、他握紧断剑"合格(那是动作)
- **相邻镜头要有连接**:动作-反应、视线-对象、或形状/动作/颜色匹配。
  两个镜头各说一件事、彼此无关,就是孤立感的来源
- **动作段落按节奏曲线排**:建立(长) → 蓄力(中) → 冲击(最短) → 反应(中);
  每 3-4 个近景插一个全景作空间锚点
- **结尾镜给足停留**:比中间镜更长

Craft guidelines:
{guide_block}{methodology_block}

Return JSON array of shots:
[
  {{
    "scene_number": 1,
    "shot_number": 1,
    "shot_type": "{ShotType.ELS.value}",
    "camera_movement": "{CameraMovement.STATIC.value}",
    "lighting": "{Lighting.NATURAL.value}",
    "color_temp": "{ColorTemp.NEUTRAL.value}",
    "duration_seconds": {DEFAULT_SHOT_DURATION},
    "beats": null,
    "location": "内景 咖啡馆 - 日",
    "description": "晨光里熙熙攘攘的城市咖啡馆,大远景建立环境",
    "characters": [],
    "action": "客人穿行于店内,杯口热气升腾",
    "dialogue": ""
  }},
  ...
]"""
    if notes:
        user_prompt += f"\n\nRevision notes (address these when regenerating the shots):\n{notes}"
    return SYSTEM, user_prompt


def _filter_cast(names, cast_names: list[str], shot_idx: int) -> list[str]:
    """把 characters 卡回已确认阵容,名单外的丢弃并记 warning(可观测,不静默)。

    prompt 约束只是软的,LLM 仍会发明人物。名单外的名字留在 characters 里,下游按
    character_id 取造型/外貌必然落空 → 该角色在每个镜头里长相都不同。丢弃后它退化为
    "无名群演"(仍在 action 描述里),形象由文本引导,这是可接受的降级;留着则是失控。

    cast_names 为空(未经确认流程,如复用剧本直达分镜)时不过滤 —— 那时没有名单可依据。
    """
    if not isinstance(names, list):
        return []
    if not cast_names:
        return [str(n) for n in names if str(n or "").strip()]
    allowed = set(cast_names)
    kept: list[str] = []
    dropped: list[str] = []
    for n in names:
        name = str(n or "").strip()
        if not name:
            continue
        (kept if name in allowed else dropped).append(name)
    if dropped:
        logger.warning(
            "storyboard: dropped off-roster characters from shot",
            shot_index=shot_idx, dropped=dropped, roster=sorted(allowed),
        )
    return kept


def _unify_scene_light(shots: list[dict]) -> list[dict]:
    """把同一场景内的 lighting / color_temp 统一为该场景首镜的取值。

    prompt 里的"同场景光影一致"是软约束,LLM 仍会逐镜漂移(与阵容名单同理,见 _filter_cast)。
    不统一的话,同一场戏的光线在镜间跳变 —— 这正是加这两个字段要消除的现象,只声明不收敛
    等于没做。以首镜为准而不取众数:首镜定调是拍摄惯例,也让结果可预测。
    """
    first: dict[int, tuple[str, str]] = {}
    out: list[dict] = []
    for s in shots:
        scene = s.get("scene_number", 1)
        if scene not in first:
            first[scene] = (s.get("lighting", ""), s.get("color_temp", ""))
            out.append(s)
            continue
        light, temp = first[scene]
        if (s.get("lighting"), s.get("color_temp")) != (light, temp):
            logger.warning(
                "storyboard: unified scene lighting to first shot of scene",
                scene=scene, got=(s.get("lighting"), s.get("color_temp")),
                unified_to=(light, temp),
            )
        out.append({**s, "lighting": light, "color_temp": temp})
    return out


def _coerce_enum(value, enum_cls, default, field: str, shot_idx: int):
    """把模型给的值卡回枚举;越界则 fallback 到默认并记 warning(可观测,不静默)。"""
    valid = {m.value for m in enum_cls}
    if value in valid:
        return value
    logger.warning(
        "storyboard: invalid enum value from model, using default",
        field=field, got=value, default=default, shot_index=shot_idx,
    )
    return default


def _rhythm_ok(shots: list[dict], target_seconds: int, model_ref: str = "") -> str:
    """产出是否可用;返回空串表示可用,否则返回该重试的原因。

    只写在 prompt 里的约束等于没有约束 —— 模型无视时代码必须发现。
    两条都是"成片像动态 PPT"的直接成因(见 knowledge/craft/shot_sequence.md)。
    """
    durs = [int(s.get("duration_seconds") or 0) for s in shots]
    if len(set(durs)) < 3:
        return f"单镜时长只有 {len(set(durs))} 种取值,节奏是平的"
    floor, _ = shot_duration_bounds(target_seconds, model_ref)
    if len(shots) * floor > target_seconds * 1.2:
        return (f"{len(shots)} 镜 × 下限 {floor}s 已达 {len(shots) * floor}s,"
                f"无法收敛到目标 {target_seconds}s")
    return ""


def _retry_notes(notes: str | None, reason: str, target_seconds: int, model_ref: str = "") -> str:
    """构造节奏重试的 notes:必须同时给出镜头数与时长多样性两个硬指标。

    只说"收敛不到目标,请重新生成"时,模型会把两条约束当成可互换的 ——
    实测:35 镜(时长多样)重试后变成 20 镜(全部压平到下限 5s):
    模型用"牺牲节奏"换了"镜头数达标"。两条约束必须一并写明,不给模型选择空间。
    """
    floor, _ = shot_duration_bounds(target_seconds, model_ref)
    want = max(1, target_seconds // floor)
    ask = (
        f"{reason}。请重新生成,同时满足两条:"
        f"(1) 产出约 {want} 个镜头(不超过 {want + 2} 个);"
        f"(2) 单镜时长必须出现至少 3 种取值 —— 建立/交代镜用长时长、"
        f"常规叙事居中、冲击镜取下限 {floor}s。"
        f"两条都要满足,不可用一条换另一条。"
    )
    return f"{notes}\n{ask}" if notes else ask


def _converge_duration(
    shots: list[dict], target_seconds: int, model_ref: str = "",
) -> tuple[list[dict], bool]:
    """总时长收敛:超目标时**从最长的镜头开始逐秒扣**,保住镜头间的相对长短。

    返回 (收敛后的镜头, 是否仍超目标)。扣到人人都在下限仍超 = 镜头数过多,这是 LLM 的
    产出问题,交给用户决策(duration_over_target),代码不擅自砍镜头 —— 砍镜头 = 代码替
    用户做剪辑决策。总时长已在目标内则原样返回(收敛是纠偏,不无条件重排)。

    **不按比例各自缩放再夹下限**:那种做法会把节奏抹平 —— 一组 {5:11, 6:1, 7:1} 在
    目标 60s 下,6s 与 7s 都 round 到下限 5s,于是"开场建立镜比其他长"这个节奏信息
    整段消失。而节奏多样性本身是要保的目标(见 _rhythm_ok 与 craft/shot_sequence.md),
    两个目标不该互相拆台:总时长该由"削峰"来收,不是由"压平"来收。
    """
    total = sum(int(s.get("duration_seconds") or 0) for s in shots)
    if total <= target_seconds:
        return shots, False
    floor, ceil_ = shot_duration_bounds(target_seconds, model_ref)
    out = [
        {**s, "duration_seconds": min(
            ceil_, max(floor, int(s.get("duration_seconds") or 0)))}
        for s in shots
    ]
    # 削峰:每轮从当前最长的镜头扣 1 秒(并列时扣靠后的,让前面的建立镜优先保住长度)。
    #
    # **扣到只剩一种时长就停** —— 这是本函数最要紧的一条约束。
    # 当 `镜头数 × floor` 本身就超过目标时(如 13 镜 × 5s = 65s > 60s),
    # 没有任何时长分配能同时"落在目标内"且"人人不低于下限":继续扣只会把所有镜头
    # 抹到下限,把节奏也一起抹掉,而总时长**依然超标**。那时既没换来达标、又赔掉了节奏。
    # 故止步于"还剩多种时长"的那一刻,把超标交给 duration_over_target 让用户决策
    # (退回重生成 / 手动删镜头 / 接受超时长)—— 代码不擅自砍镜头,也不擅自毁节奏。
    while sum(int(s["duration_seconds"]) for s in out) > target_seconds:
        above = [i for i, s in enumerate(out) if int(s["duration_seconds"]) > floor]
        if len(above) <= 1:
            # 只剩一个(或零个)高于下限的镜头:再扣就只剩一种时长了,停手
            break
        longest = max(above, key=lambda i: (int(out[i]["duration_seconds"]), i))
        out[longest]["duration_seconds"] = int(out[longest]["duration_seconds"]) - 1
    new_total = sum(int(s["duration_seconds"]) for s in out)
    return out, new_total > target_seconds


def _normalize_beats(value) -> list[str] | None:
    """把模型给的 beats 规范化:非列表 → None;过滤空串项;过滤后为空 → None
    (不留 `[]`,免得下游要判两种"没有")。"""
    if not isinstance(value, list):
        return None
    cleaned = [str(b).strip() for b in value if str(b or "").strip()]
    return cleaned or None


async def _generate_shots(
    state: DramaState, target_seconds: int, cast_names: list[str], notes: str | None,
    model_ref: str = "",
) -> list[ShotDict]:
    """调一次 LLM 并把产出规范化成 ShotDict 列表(枚举卡回、阵容过滤、时长夹取)。
    抽成独立函数是为了让节奏校验失败时能原样重试一次(见 storyboard_director_node)。
    """
    system, user_prompt = build_prompt(
        state["screenplay"], state.get("story_analysis") or {},
        target_seconds, notes=notes, cast_names=cast_names, model_ref=model_ref,
    )
    min_dur, max_dur = shot_duration_bounds(target_seconds, model_ref)

    shots_data = await llm_service.complete_json(system, user_prompt, temperature=0.3, model=state.get("llm_model"))

    if isinstance(shots_data, dict) and "shots" in shots_data:
        shots_data = shots_data["shots"]

    if not isinstance(shots_data, list):
        shots_data = []

    # 一个镜头都没有时必须抛错交 job 重试,不得带着空清单继续:
    # 图会照常停在 storyboard_review,而面板上没有任何镜头可审 —— 「通过」让后续每步
    # 都在空清单上跑(prompt/视频全空),「退回」只是再赌一次 LLM,用户界面上无路可走。
    if not shots_data:
        raise ValueError(
            "分镜生成失败:模型未产出任何镜头(检查剧本正文与 LLM 返回格式)")

    shots: list[ShotDict] = []
    for idx, s in enumerate(shots_data):
        shot: ShotDict = {
            "shot_id": str(uuid.uuid4()),
            "scene_number": s.get("scene_number", 1),
            "shot_number": s.get("shot_number", 1),
            "shot_type": _coerce_enum(
                s.get("shot_type"), ShotType, ShotType.MS.value, "shot_type", idx),
            "camera_movement": _coerce_enum(
                s.get("camera_movement"), CameraMovement, CameraMovement.STATIC.value,
                "camera_movement", idx),
            "lighting": _coerce_enum(
                s.get("lighting"), Lighting, Lighting.NATURAL.value, "lighting", idx),
            "color_temp": _coerce_enum(
                s.get("color_temp"), ColorTemp, ColorTemp.NEUTRAL.value, "color_temp", idx),
            "duration_seconds": max(
                min_dur,
                min(int(s.get("duration_seconds", DEFAULT_SHOT_DURATION)), max_dur)),
            "beats": _normalize_beats(s.get("beats")),
            "description": s.get("description", ""),
            "characters": _filter_cast(s.get("characters", []), cast_names, idx),
            "dialogue": s.get("dialogue", ""),
            "action": s.get("action", ""),
            "location": s.get("location", ""),
        }
        shots.append(shot)
    return shots


async def storyboard_director_node(state: DramaState, target_seconds: int | None = None) -> dict:
    # 目标时长优先级:显式传参 > 集级 state["target_seconds"] > config 默认。
    # 生产中图按 (state) 单参调用,故靠 state 携带集级目标(见 runner._build_initial_state)。
    from drama_agent.services import cast_service
    target_seconds = target_seconds or state.get("target_seconds") or settings.target_episode_seconds
    # 解析键用 video_model(真正的模型 id);为空时退到 provider,与 prompt_engineer/
    # video_generator 解析视频模型的口径一致(规范 4:同一份能力,唯一解析路径)。
    model_ref = state.get("video_model") or state.get("video_provider") or ""
    cast_names = await cast_service.roster_names(state["project_id"], state.get("cast"))
    # cast 的键可能是别名(用户把「程序员」link 到已有角色「角色1」)。分镜里用的是规范名,
    # 故把 cast 的键一并换成规范名 —— 否则 prompt_engineer 按规范名查 cast 取不到
    # character_id,该角色的造型与外貌整段丢失。
    roster = await cast_service.roster_by_id(state["project_id"])
    canon_cast = cast_service.canonical_cast(state.get("cast"), roster)

    notes = state.get("storyboard_revision_notes") or None
    shots = await _generate_shots(state, target_seconds, cast_names, notes, model_ref)

    # 节奏硬约束只写在 prompt 里等于没有约束(LLM 会无视)。产出不合格时重试一次,
    # 把不合格的原因追加进 notes 引导重生成;第二次仍不合格则照常继续(记 warning,
    # 不阻断 —— 卡住整条流水线比节奏平更糟),交后面的 duration_over_target 提示兜底。
    # cast:list[ShotDict] 是 list[dict] 的安全放宽(_rhythm_ok 只读 duration_seconds),
    # mypy 因不变性不自动放宽(与下方 _unify_scene_light 同例)。
    reason = _rhythm_ok(cast(list[dict], shots), target_seconds, model_ref)
    if reason:
        logger.warning("storyboard: rhythm check failed, retrying once",
                       reason=reason, shots=len(shots))
        retry_notes = _retry_notes(notes, reason, target_seconds, model_ref)
        shots = await _generate_shots(state, target_seconds, cast_names, retry_notes, model_ref)
        reason = _rhythm_ok(cast(list[dict], shots), target_seconds, model_ref)
        if reason:
            logger.warning("storyboard: rhythm check still failing after retry",
                           reason=reason, shots=len(shots))

    # 同场景光影收敛(prompt 约束是软的,须在落状态前统一)
    unified = _unify_scene_light(cast(list[dict], shots))
    # 总时长收敛:超目标按比例压缩,镜头一个不少;压到下限仍超只标记不阻断(交审核决策)。
    # cast:list[ShotDict] 是 list[dict] 的安全放宽(收敛只读 duration_seconds),mypy 因不变性不自动放宽。
    converged, over = _converge_duration(unified, target_seconds, model_ref)
    if over:
        logger.warning(
            "storyboard: total duration over target even at per-shot floor",
            target=target_seconds,
            total=sum(int(s["duration_seconds"]) for s in converged),
            shots=len(converged),
        )
    return {
        "shots": converged,
        "cast": canon_cast,
        "duration_over_target": over,
        "current_stage": "storyboard_ready",
    }
