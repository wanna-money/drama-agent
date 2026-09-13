"""**背景**参考图清单的唯一权威:类型归属、占位补全、读时兼容,全部收在这一处。

**角色形象不属于本模块,不要往这里加。** 角色的图只来自「角色」页配置的造型(Look),
经 subject_ref_service 下发给视频模型。参考图面板再承载一份角色图,就成了同一件事的
第二个入口 —— 两处各配一份,用户看到的就是"角色管理和参考图对不上"。
背景则相反:它没有实体(不像角色有 Character),只能按场景地点名关联。

ref_type 由本模块判定并持久化,调用方(API / 节点 / 前端)只消费结果、不各自推断 ——
在前端按 `chars.includes(key)` 之类反猜类型,会把从素材库选的图判进错误的组
(规范 4:同一规则不在前后端各写一遍)。

清单的构成:
  已持久化的条目(用户上传/从库选择/手动添加,类型权威)
∪ 探测出的未上传占位(地点来自 shots[].location)
image_url 为空串即"已列出但未上传",不是缺陷数据。
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from drama_agent.db.enums import ReferenceType
from drama_agent.workflow.state import ReferenceDict

_VALID_TYPES: frozenset[str] = frozenset(t.value for t in ReferenceType)


def view_url(storage_key: str) -> str:
    """Look 视图的访问 URL —— 与 api/characters.py 的 serve_view 路由同形。"""
    return f"/api/characters/view/{storage_key}"


def _entry(key: str, ref_type: str, image_url: str = "", prompt: str = "") -> ReferenceDict:
    return {"key": key, "ref_type": ref_type, "image_url": image_url, "prompt": prompt}


def normalize(raw: Iterable[Mapping[str, Any]]) -> list[ReferenceDict]:
    """校验并规整**客户端提交**的清单;非法 ref_type 抛 ValueError(API 层映射成 400)。

    写路径严格:宁可拒绝也不让自由字符串落进状态(规范 1)。key 在清单内唯一。
    """
    out: dict[str, ReferenceDict] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError(f"Invalid reference entry: {item!r}")
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        ref_type = str(item.get("ref_type") or "")
        if ref_type not in _VALID_TYPES:
            raise ValueError(
                f"Invalid ref_type: {ref_type!r} (expected one of {sorted(_VALID_TYPES)})"
            )
        out[key] = _entry(key, ref_type, str(item.get("image_url") or ""),
                          str(item.get("prompt") or ""))
    return list(out.values())


def _from_legacy(character_references: Mapping[str, str] | None) -> list[ReferenceDict]:
    """旧状态 `character_references: {name: url}` 升级为带类型的清单。

    旧结构丢了 ref_type,按其字面语义全部判为角色 —— 这是与旧数据唯一自洽的解释。
    这些历史角色条目仍会被读出来(不静默丢用户的数据),但界面已不再展示角色组;
    真正的角色形象请在「角色」页配置造型。
    """
    if not isinstance(character_references, Mapping):
        return []
    return [
        _entry(str(k), ReferenceType.CHARACTER.value, str(v or ""))
        for k, v in character_references.items()
        if str(k or "").strip()
    ]


def stored(source: Mapping[str, Any] | None) -> list[ReferenceDict]:
    """从图状态 / state_snapshot 读出已持久化的清单,自动兼容旧字段。

    读路径容错:单条脏数据跳过即可,不能让整个参考图面板取不出来(规范 6)。
    """
    source = source or {}
    raw = source.get("references")
    if isinstance(raw, list):
        out: dict[str, ReferenceDict] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            key = str(item.get("key") or "").strip()
            ref_type = str(item.get("ref_type") or "")
            if not key or ref_type not in _VALID_TYPES:
                continue
            out[key] = _entry(key, ref_type, str(item.get("image_url") or ""),
                              str(item.get("prompt") or ""))
        return list(out.values())
    return _from_legacy(source.get("character_references"))


def detected(shots: Iterable[Mapping[str, Any]] | None) -> list[ReferenceDict]:
    """探测出"应该有图"的背景条目(空 image_url 占位)。

    **不要从 story_analysis.characters 造角色占位**:角色形象的唯一配置处是「角色」页
    的造型,在这里再列一份就与造型指派重复表达同一件事。
    """
    out: dict[str, ReferenceDict] = {}
    for s in shots or []:
        if not isinstance(s, Mapping):
            continue
        loc = str(s.get("location") or "").strip()
        if loc and loc not in out:
            out[loc] = _entry(loc, ReferenceType.BACKGROUND.value)
    return list(out.values())


def build_list(source: Mapping[str, Any] | None) -> list[dict]:
    """完整清单 = 探测出的背景占位 + 用户已持久化的条目(同 key 时以已持久化的为准)。

    source 是图状态 values 或 Episode.state_snapshot —— 两者字段同名,故同一函数通吃。
    每条额外带 `removable`:能不能删是一条业务判断,由后端算好下发,前端只消费(规范 4)。
    纯探测出来的占位不是用户记录、删了下次还会被探测出来 → 不可删。
    """
    source = source or {}
    persisted = {e["key"]: e for e in stored(source)}
    out: list[dict] = []
    seen: set[str] = set()
    for placeholder in detected(source.get("shots")):
        key = placeholder["key"]
        hit = persisted.get(key)
        out.append({**(hit or placeholder), "removable": hit is not None})
        seen.add(key)
    for entry in persisted.values():
        if entry["key"] not in seen:
            out.append({**entry, "removable": True})
            seen.add(entry["key"])
    return out
