"""镜头主体(角色)参考图的**唯一权威**:一个镜头该带哪些 subject 图,只由这里决定。

为什么必须只有一处:subject 图一旦在多处解析(如 prompt_engineer 从参考图清单取一份、
video_generator 再按名字查 Character/Look 取一份),两条路彼此不知情、无法按角色去重,
同一角色的图就会被投喂两次(规范 4)。解析只发生在本模块,结构上不可能重复 ——
**不要在调用方另加取图分支**。

图的来源只有一处:该角色在本场景生效的 Look(指派 → 默认 → 首个)的各视图。
角色形象在「角色」页配置造型即生效,参考图面板不再承载角色图(那是同一件事的第二个入口)。
没有造型图 → 不带图,降级为仅文本一致。
"""
from __future__ import annotations

import logging

from drama_agent.services import reference_service
from drama_agent.services.video_refs import RefImage

logger = logging.getLogger(__name__)

# face 必须在内:它是四视图里唯一清晰展示五官/肌肤/发丝的那张,而角色一致性最容易崩的
# 地方正是脸 —— 特写镜头(CU/ECU)不带它,模型只能从全身图里猜五官。
# 数量不成问题:两个角色 × 4 视图 = 8 张,仍在 provider 的 9 张上限内;真超了由
# cap_refs 按声明截断(那是 provider 层的职责,不在此处预先削减)。
_LOOK_VIEWS = ("front", "side", "back", "face")


async def _look_refs(project_id: str, name: str, scene: str,
                     look_assignments: dict) -> list[RefImage]:
    """该角色在本场景生效 Look 的各视图 → subject RefImage。join 不到则空。"""
    from drama_agent.services import character_entity_service as ce
    ch = await ce.get_character_by_name(project_id, name)
    if ch is None:
        return []
    looks = await ce.list_looks(ch.id)
    if not looks:
        return []
    assigned = (look_assignments.get(scene) or {}).get(name)
    look = next((lk for lk in looks if lk.id == assigned), None) \
        or next((lk for lk in looks if getattr(lk, "is_default", False)), looks[0])
    out: list[RefImage] = []
    for view in _LOOK_VIEWS:
        key = getattr(look, f"{view}_key", None)
        if key:
            out.append(RefImage(
                url=reference_service.view_url(key), kind="subject",
                subject_name=name, view=view))
    return out


async def subject_refs(
    project_id: str,
    shot: dict,
    look_assignments: dict | None = None,
) -> list[RefImage]:
    """本镜头所有出场角色的 subject 参考图(每个角色只出一组,不重复)。

    角色图**只**来自造型(Look):角色管理是形象的唯一配置处,参考图面板不再有角色组。
    单个角色解析失败不阻断整镜(规范 6);出场名单里的重复名字只算一次。
    """
    scene = str(shot.get("scene_number", 1))
    out: list[RefImage] = []
    seen: set[str] = set()
    for name in shot.get("characters", []) or []:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            out.extend(await _look_refs(project_id, name, scene, look_assignments or {}))
        except Exception:  # noqa: BLE001 — 单角色解析失败不阻断出片
            logger.warning("subject ref resolve failed for %s", name)
    return out
