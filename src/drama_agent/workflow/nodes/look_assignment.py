import json

import structlog

from drama_agent.workflow.state import DramaState
from drama_agent.services.llm_service import llm_service

logger = structlog.get_logger()

SYSTEM = ("你是短剧的服装/造型统筹。根据剧本分镜,为每个场景里出场的角色指派该穿哪一套造型(Look)。"
          "只能从给定的候选 Look 里选,输出 JSON:{\"场景号\": {\"角色名\": \"look_id\"}}。")


def _default_look_id(looks: list) -> str | None:
    if not looks:
        return None
    for lk in looks:
        if getattr(lk, "is_default", False):
            return lk.id
    return looks[0].id


async def look_assignment_node(state: DramaState) -> dict:
    from drama_agent.services import character_entity_service as ce
    project_id = state["project_id"]
    shots = state["shots"]
    names_in = {c for s in shots for c in s.get("characters", [])}
    scenes = sorted({str(s.get("scene_number", 1)) for s in shots})

    # 收集出场角色的 Looks(名字-join)
    looks_by_name: dict[str, list] = {}
    for ch in await ce.list_characters(project_id):
        if ch.name in names_in:
            looks_by_name[ch.name] = await ce.list_looks(ch.id)

    # 默认指派:每场景每出场角色 → 该角色默认 Look
    def default_map() -> dict[str, dict[str, str]]:
        out: dict[str, dict[str, str]] = {}
        for s in shots:
            sc = str(s.get("scene_number", 1))
            for nm in s.get("characters", []):
                lid = _default_look_id(looks_by_name.get(nm, []))
                if lid:
                    out.setdefault(sc, {})[nm] = lid
        return out

    # 只有存在「多 Look」角色时才调 LLM(否则默认即最优)
    multi = any(len(v) > 1 for v in looks_by_name.values())
    assignments = default_map()
    if multi:
        catalog = {nm: [{"look_id": lk.id, "name": lk.name} for lk in looks]
                   for nm, looks in looks_by_name.items()}
        user = (f"场景号: {scenes}\n每场景出场角色见分镜。\n"
                f"候选造型(角色→Look列表): {json.dumps(catalog, ensure_ascii=False)}\n"
                f"分镜(场景→角色): "
                f"{json.dumps({str(s.get('scene_number', 1)): s.get('characters', []) for s in shots}, ensure_ascii=False)}\n"
                "为每个场景的每个出场角色选一个 look_id。")
        try:
            proposed = await llm_service.complete_json(SYSTEM, user, temperature=0.2,
                                                       model=state.get("llm_model"))
            # 合并:LLM 的合法选择覆盖默认(校验 look_id 属于该角色候选)
            valid_ids = {lk.id for looks in looks_by_name.values() for lk in looks}
            for sc, m in (proposed or {}).items():
                if not isinstance(m, dict):
                    continue
                for nm, lid in m.items():
                    if lid in valid_ids:
                        assignments.setdefault(str(sc), {})[nm] = lid
        except Exception as e:  # noqa: BLE001 — LLM 失败回退默认指派
            logger.warning("look assignment LLM failed, using defaults", error=str(e))

    return {"look_assignments": assignments, "current_stage": "looks_assigned"}
