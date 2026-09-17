import uuid
from typing import cast
import structlog
from drama_agent.workflow.state import DramaState, ShotDict
from drama_agent.workflow.constants import (
    ShotType, CameraMovement, ColorTemp, Lighting,
    DEFAULT_SHOT_DURATION, MAX_SHOT_DURATION, SHOT_TYPE_DESC,
)
from drama_agent.config import settings
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.cast_constraint import cast_constraint_block
from drama_agent.workflow.prompt_rules import system_prompt

logger = structlog.get_logger()

# 打斗/法术类 craft 知识只在题材命中时才检索——这批文档是仙侠/玄幻专项内容
# (招式模板、法术公式、终极大招、长镜头打戏铁律),塞给现代剧/爱情剧等无战斗
# 元素的题材只会稀释 prompt 里真正有用的通用方法论、徒增 token,对产出没有帮助。
_GENRE_COMBAT_KNOWLEDGE_KINDS = ("xianxia_combat_moves", "xianxia_spell_techniques",
                                 "vfx_spell_prompt_guide", "epic_manifestation_prompts",
                                 "long_take_fight_prompts")
_COMBAT_GENRES = {"fantasy", "action"}

SYSTEM = system_prompt("""You are a professional film director and storyboard artist.
Break screenplays into individual shots for video production.
Each shot's duration_seconds is the true narrative length this beat should last on screen —
decide it purely from emotional intensity and pacing, not from any technical constraint.""")


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
    notes: str | None = None, cast_names: list[str] | None = None, genre: str = "",
) -> tuple[str, str]:
    """target_seconds:全片目标时长(秒),约束镜头总时长;缺省取 config 的 target_episode_seconds。
    notes:分镜被打回重做时的人工意见,拼进 prompt 尾部引导重生成(仿 prompt_engineer)。

    cast_names:已确认阵容,作为 shots[].characters 的**受约束取值**下发。名单外的名字
    进了 characters,下游按 character_id 取造型与外貌就会落空(该角色形象逐镜漂移)。

    genre:决定是否额外检索仙侠/玄幻打斗类 craft 知识(见 _COMBAT_GENRES)——
    非战斗题材不该被这批专项内容稀释掉更该优先的通用镜头方法论。

    不再需要 model_ref:duration_seconds 是纯叙事时长,与视频模型的生成能力无关
    (生成时长由 workflow.constants.generation_duration_for 在 prompt_engineer 阶段
    按需现算,不影响这里怎么写分镜)。
    """
    target_seconds = target_seconds or settings.target_episode_seconds
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

    if genre in _COMBAT_GENRES:
        for kind in _GENRE_COMBAT_KNOWLEDGE_KINDS:
            content = "\n\n".join(knowledge_store.retrieve(kind))
            if content:
                methodology_block += f"\n\nCombat/VFX reference ({kind}):\n{content}"

    user_prompt = f"""Break this screenplay into individual production shots.

SCREENPLAY:
{screenplay}

CHARACTER VISUAL REFERENCES:
{_format_characters(analysis)}{cast_constraint_block(cast_names)}

Rules for shots:
- shots[].characters 里只填已确认阵容里的名字;无名群演不进该字段(写在 action 里)
- **按叙事强度自由决定单镜时长(建议 0.5–{MAX_SHOT_DURATION} 秒)**:这是这一镜在
  成片里应该演多久,不是"视频模型能生成多久" —— 后者由系统在生成阶段单独处理
  (必要时会把生成时长垫高到模型下限,再在生成后裁剪回你写的时长,画面不会因此
  变形)。冲击/爆发类镜头(击中、爆炸、惊吓、反转揭示)该短就写短,可以是
  0.5-1 秒,**不要因为"怕太短生成不了"而给它一个更长的时长** —— 那正是冲击力
  消失、成片变成"动态 PPT"的根源
- 全片目标时长约 {target_seconds} 秒:所有镜头 duration_seconds 之和应接近该值,
  不要大幅超出
- Use shot types: {_shot_types_line()}
- Use camera movements: {_camera_moves_line()}
- lighting 取值: {_lighting_line()}
- color_temp 取值: {_color_temp_line()}
- **同一场景(scene_number 相同)的 lighting、color_temp 与 location 必须一致**:
  同一场戏里光线不该在镜间跳变,location 也不要写成"同一地点 - 继续"这种变体
  (如"外景 青云宗论道台 - 黄昏"与"外景 青云宗论道台 - 继续")—— 同场次内每镜
  location 原样重复即可,不需要额外区分。要变光/换地点就换场景,或让它随剧情
  推进(白天→黄昏)整段迁移
- **一镜内有多个明显节拍时**(如击中 + 跌出),用 `beats` 按顺序列出各节拍
  (自然语言,写明各自占多久),`duration_seconds` 给这些节拍的总长。
  例:`duration_seconds: 2`,`beats: ["前 0.4 秒:拳头击中下颌,头部急偏",
  "随后 1.6 秒:身体失衡跌出画面,烟尘扬起"]`。单一连续动作的镜头,`beats`
  给 null 或省略

节奏硬约束(违反其一即为"动态 PPT",见 shot-sequence 方法论第七节):
- **时长必须有变化**:同一场景内至少出现 3 种不同的 duration_seconds。
  全部相同(不管收敛到哪个数值)是最常见的失败 —— 那让成片像翻页 PPT
- **冲击性镜头取短时长**:击中、爆炸、惊吓、反转揭示这类镜头写 0.5-1 秒
  (必要时用上面的 `beats` 列出镜内节拍);建立/交代与情绪停留的镜头才用长时长
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

Return JSON array of shots. **The two example shots below use deliberately different
duration_seconds(3 vs 1)** — that difference is itself part of the example: copy the
shape of these objects, never the numbers, and let every real shot's duration_seconds
come from its own narrative weight instead of echoing an example value:
[
  {{
    "scene_number": 1,
    "shot_number": 1,
    "shot_type": "{ShotType.ELS.value}",
    "camera_movement": "{CameraMovement.STATIC.value}",
    "lighting": "{Lighting.NATURAL.value}",
    "color_temp": "{ColorTemp.NEUTRAL.value}",
    "duration_seconds": 3,
    "beats": null,
    "location": "内景 咖啡馆 - 日",
    "description": "晨光里熙熙攘攘的城市咖啡馆,大远景建立环境",
    "characters": [],
    "action": "客人穿行于店内,杯口热气升腾",
    "dialogue": ""
  }},
  {{
    "scene_number": 1,
    "shot_number": 2,
    "shot_type": "{ShotType.CU.value}",
    "camera_movement": "{CameraMovement.ZOOM.value}",
    "lighting": "{Lighting.NATURAL.value}",
    "color_temp": "{ColorTemp.NEUTRAL.value}",
    "duration_seconds": 1,
    "beats": null,
    "location": "内景 咖啡馆 - 日",
    "description": "杯子被猛地推倒,瓷片飞溅",
    "characters": [],
    "action": "手掌猛拍桌面,杯子应声碎裂",
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


def _unify_scene_fields(shots: list[dict]) -> list[dict]:
    """把同一场景内的 lighting / color_temp / location 统一为该场景首镜的取值。

    prompt 里的"同场景一致"是软约束,LLM 仍会逐镜漂移(与阵容名单同理,见 _filter_cast)。
    不统一的话,同一场戏的光线在镜间跳变、地点文案也会漂(如首镜写"外景 青云宗论道台 -
    黄昏",同场次镜写成"外景 青云宗论道台 - 继续")—— 这正是加这些字段要消除的现象,
    只声明不收敛等于没做。以首镜为准而不取众数:首镜定调是拍摄惯例,也让结果可预测。

    location 一并收敛的直接收益:reference_service.detected() 按 shots[].location
    的字面值去重生成背景参考图占位,同场次里哪怕只有一镜漂了文案,也会在参考图面板里
    多出一条本不存在的"新地点"——收敛在这里比在参考图那层做模糊匹配更根本。
    """
    first: dict[int, tuple[str, str, str]] = {}
    out: list[dict] = []
    for s in shots:
        scene = s.get("scene_number", 1)
        if scene not in first:
            first[scene] = (
                s.get("lighting", ""), s.get("color_temp", ""), s.get("location", ""))
            out.append(s)
            continue
        light, temp, location = first[scene]
        if (s.get("lighting"), s.get("color_temp"), s.get("location")) != (
                light, temp, location):
            logger.warning(
                "storyboard: unified scene fields to first shot of scene",
                scene=scene, got=(s.get("lighting"), s.get("color_temp"), s.get("location")),
                unified_to=(light, temp, location),
            )
        out.append({**s, "lighting": light, "color_temp": temp, "location": location})
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


def _rhythm_ok(shots: list[dict], target_seconds: int) -> str:
    """产出是否可用;返回空串表示可用,否则返回该重试的原因。

    只写在 prompt 里的约束等于没有约束 —— 模型无视时代码必须发现。
    时长趋同是"成片像动态 PPT"的直接成因(见 knowledge/craft/shot_sequence.md)。
    不再检查"镜头数 × 下限超目标" —— duration_seconds 现在是纯叙事时长,没有
    统一下限,总时长只由 LLM 实际写的每镜时长之和决定,由 _converge_duration 收敛。
    """
    durs = [int(s.get("duration_seconds") or 0) for s in shots]
    if len(set(durs)) < 3:
        return f"单镜时长只有 {len(set(durs))} 种取值,节奏是平的"
    return ""


def _retry_notes(notes: str | None, reason: str, target_seconds: int) -> str:
    """构造节奏重试的 notes:必须同时给出总时长与时长多样性两个硬指标。

    只说"节奏不合格,请重新生成"时,模型可能把"凑时长"与"保节奏"当成互换的 ——
    两条约束必须一并写明,不给模型选择空间。
    """
    ask = (
        f"{reason}。请重新生成,同时满足两条:"
        f"(1) 所有镜头 duration_seconds 之和接近目标 {target_seconds} 秒;"
        f"(2) 单镜时长必须出现至少 3 种取值 —— 建立/交代镜用长时长、"
        f"常规叙事居中、冲击镜用 0.5-1 秒的短时长。"
        f"两条都要满足,不可用一条换另一条。"
    )
    return f"{notes}\n{ask}" if notes else ask


def _converge_duration(
    shots: list[dict], target_seconds: int,
) -> tuple[list[dict], bool]:
    """总时长收敛:超目标时**从最长的镜头开始逐秒扣**,保住镜头间的相对长短。

    返回 (收敛后的镜头, 是否仍超目标)。duration_seconds 是纯叙事时长,不再有
    "平台生成下限"这个约束要保护 —— 削峰可以一直削到 1 秒(不能是 0 或负数),
    不设更高的地板。总时长已在目标内则原样返回(收敛是纠偏,不无条件重排)。

    **不按比例各自缩放**:那种做法会把节奏抹平 —— 一组 {5:11, 6:1, 7:1} 在
    目标 60s 下按比例缩放,"开场建立镜比其他长"这个节奏信息会整段消失。
    而节奏多样性本身是要保的目标(见 _rhythm_ok 与 craft/shot_sequence.md),
    两个目标不该互相拆台:总时长该由"削峰"来收,不是由"压平"来收。
    """
    total = sum(int(s.get("duration_seconds") or 0) for s in shots)
    if total <= target_seconds:
        return shots, False
    out = [
        {**s, "duration_seconds": min(
            MAX_SHOT_DURATION, max(1, int(s.get("duration_seconds") or 0)))}
        for s in shots
    ]
    # 削峰:每轮从当前最长的镜头扣 1 秒(并列时扣靠后的,让前面的建立镜优先保住长度)。
    # 止步于"所有镜头都已在 1 秒"这一安全终止条件 —— 极端情况下(镜头数本身就多)
    # 即使全削到 1 秒仍可能超标,那是 LLM 产出镜头数过多的问题,交
    # duration_over_target 让用户决策(退回重生成 / 手动删镜头 / 接受超时长),
    # 代码不擅自砍镜头。
    while sum(int(s["duration_seconds"]) for s in out) > target_seconds:
        above = [i for i, s in enumerate(out) if int(s["duration_seconds"]) > 1]
        if not above:
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
) -> list[ShotDict]:
    """调一次 LLM 并把产出规范化成 ShotDict 列表(枚举卡回、阵容过滤、时长夹取)。
    抽成独立函数是为了让节奏校验失败时能原样重试一次(见 storyboard_director_node)。
    """
    system, user_prompt = build_prompt(
        state["screenplay"], state.get("story_analysis") or {},
        target_seconds, notes=notes, cast_names=cast_names, genre=state.get("genre", ""),
    )

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
        # 只夹 [1, MAX_SHOT_DURATION] —— 纯叙事上下限,不再引入任何模型相关的下限。
        duration_seconds = max(
            1, min(int(s.get("duration_seconds", DEFAULT_SHOT_DURATION)), MAX_SHOT_DURATION))
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
            "duration_seconds": duration_seconds,
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
    cast_names = await cast_service.roster_names(state["project_id"], state.get("cast"))
    # cast 的键可能是别名(用户把「程序员」link 到已有角色「角色1」)。分镜里用的是规范名,
    # 故把 cast 的键一并换成规范名 —— 否则 prompt_engineer 按规范名查 cast 取不到
    # character_id,该角色的造型与外貌整段丢失。
    roster = await cast_service.roster_by_id(state["project_id"])
    canon_cast = cast_service.canonical_cast(state.get("cast"), roster)

    notes = state.get("storyboard_revision_notes") or None
    shots = await _generate_shots(state, target_seconds, cast_names, notes)

    # 节奏硬约束只写在 prompt 里等于没有约束(LLM 会无视)。产出不合格时重试一次,
    # 把不合格的原因追加进 notes 引导重生成;第二次仍不合格则照常继续(记 warning,
    # 不阻断 —— 卡住整条流水线比节奏平更糟),交后面的 duration_over_target 提示兜底。
    # cast:list[ShotDict] 是 list[dict] 的安全放宽(_rhythm_ok 只读 duration_seconds),
    # mypy 因不变性不自动放宽(与下方 _unify_scene_fields 同例)。
    reason = _rhythm_ok(cast(list[dict], shots), target_seconds)
    if reason:
        logger.warning("storyboard: rhythm check failed, retrying once",
                       reason=reason, shots=len(shots))
        retry_notes = _retry_notes(notes, reason, target_seconds)
        shots = await _generate_shots(state, target_seconds, cast_names, retry_notes)
        reason = _rhythm_ok(cast(list[dict], shots), target_seconds)
        if reason:
            logger.warning("storyboard: rhythm check still failing after retry",
                           reason=reason, shots=len(shots))

    # 同场景光影/地点收敛(prompt 约束是软的,须在落状态前统一)
    unified = _unify_scene_fields(cast(list[dict], shots))
    # 总时长收敛:超目标从最长镜头逐秒削峰,镜头一个不少;削到人人都在 1 秒仍超
    # 只标记不阻断(交审核决策)。
    # cast:list[ShotDict] 是 list[dict] 的安全放宽(收敛只读 duration_seconds),mypy 因不变性不自动放宽。
    converged, over = _converge_duration(unified, target_seconds)
    if over:
        logger.warning(
            "storyboard: total duration over target even at per-shot floor",
            target=target_seconds,
            total=sum(int(s["duration_seconds"]) for s in converged),
            shots=len(converged),
        )
    # 每次(重新)生成追加一版,不覆盖 —— 否则"退回重新生成"会让上一版分镜
    # (可能更满意、已看过)无法再对比或恢复(见 episode_service 分镜版本树)。
    # 旁路失败不阻断出片(规范 6):版本历史丢一条不影响本集能不能继续跑。
    try:
        from drama_agent.db import session as db_session
        from drama_agent.services import episode_service
        label = notes or "初始生成"
        async with db_session.AsyncSessionLocal() as db:
            await episode_service.append_shots_version_db(
                db, state["episode_id"], shots=cast(list[dict], converged), label=label)
    except Exception:  # noqa: BLE001
        logger.warning("storyboard: append shots version failed", exc_info=True)
    return {
        "shots": converged,
        "cast": canon_cast,
        "duration_over_target": over,
        "current_stage": "storyboard_ready",
    }
