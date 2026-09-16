"""知识存取抽象:节点只依赖 KnowledgeStore.retrieve;实现可换(常量 / 未来 pgvector)。"""
import importlib.resources
from typing import Protocol
from drama_agent.knowledge import constants as K


class KnowledgeStore(Protocol):
    def retrieve(
        self, kind: str, key: str | None = None, query: str | None = None, k: int = 3
    ) -> list[str]:
        ...


class ConstantKnowledgeStore:
    """从 knowledge.constants 按 kind/key 精确取,确定性、无 IO。"""

    def retrieve(
        self, kind: str, key: str | None = None, query: str | None = None, k: int = 3
    ) -> list[str]:
        return self._lookup(kind, key)[:k]

    def _lookup(self, kind: str, key: str | None) -> list[str]:
        if kind == "prompt_template":
            provider_map = K.PROMPT_TEMPLATES
            if key and ":" in key:  # "provider:shot_type" 精确取,不混 provider
                prov, shot = key.split(":", 1)
                return list(provider_map.get(prov, {}).get(shot, []))
            if key in provider_map:  # key 是 provider
                return [t for shots in provider_map[key].values() for t in shots]
            out: list[str] = []
            for shots in provider_map.values():  # key 是 shot_type(旧行为,向后兼容)
                out.extend(shots.get(key or "", []))
            return out
        if kind == "prompt_guide":
            return list(K.PROMPT_GUIDES.get(key or "all", K.PROMPT_GUIDES.get("all", [])))
        if kind == "cinematography":
            if key:
                return list(K.CINEMATOGRAPHY.get(key, []))
            return [v for lst in K.CINEMATOGRAPHY.values() for v in lst]
        if kind == "screenplay_guide":
            return list(K.SCREENPLAY_GUIDE)
        if kind == "storyboard_guide":
            return list(K.STORYBOARD_GUIDE)
        return []


CRAFT_KINDS = {"shot_language", "shot_sequence", "story_structure", "visual_aesthetics",
               "image_prompt_guide", "story_text_guide",
               "multi_character_blocking", "camera_movement_prompts",
               "vfx_spell_prompt_guide", "lighting_prompt_guide",
               "xianxia_combat_moves", "epic_manifestation_prompts",
               "lens_language_prompts", "mythical_creature_battle_prompts",
               "facial_expression_prompts", "xianxia_spell_techniques"}


def _read_craft(kind: str) -> str:
    """读打包的方法论 markdown 全文;文件缺失返回空串(降级为无该方法论,不崩)。"""
    try:
        res = importlib.resources.files("drama_agent.knowledge").joinpath("craft", f"{kind}.md")
        return res.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return ""


class MarkdownKnowledgeStore:
    """只服务 CRAFT_KINDS:读打包 markdown 全文;非 craft 返回 []。

    路由与兜底由 KnowledgeRegistry 负责(本类不自委派)。整份注入可接受,k 不切分。
    """

    def retrieve(
        self, kind: str, key: str | None = None, query: str | None = None, k: int = 3
    ) -> list[str]:
        if kind in CRAFT_KINDS:
            text = _read_craft(kind)
            return [text] if text else []
        return []


def _default_store() -> KnowledgeStore:
    """按声明式注册表构建;来源选择/降级全在 registry。惰性 import 避免循环。"""
    from drama_agent.knowledge.registry import build_default_registry
    return build_default_registry()


knowledge_store: KnowledgeStore = _default_store()
