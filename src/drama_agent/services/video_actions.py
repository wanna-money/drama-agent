"""视频动作注册表：能力由谓词实时计算，动作产出新产物字段。

能力真相在 provider 适配层 registry(model 粒度声明);此处按 artifact 的
provider 字段解析出 registry model,读其 supported_actions / resolutions。
"""
from typing import Any, Awaitable, Callable

from drama_agent import provider as provider_pkg
from drama_agent.services.video_service import video_service
from drama_agent.services.video_refs import RefImage, RefAudio


def _refs_of(artifact: dict) -> list[RefImage]:
    """从产物持久化的 references_json 重建 RefImage 列表(rerun/regenerate 用,避免丢参考图)。"""
    return [RefImage(**r) for r in (artifact.get("references_json") or [])]


def _audio_of(artifact: dict) -> list[RefAudio]:
    """从产物 audio_refs_json 重建 RefAudio(rerun/regenerate 保持音色一致)。"""
    return [RefAudio(**a) for a in (artifact.get("audio_refs_json") or [])]


def _replay_kwargs(artifact: dict) -> dict:
    """重放这次生成所需的入参(只带产物上真有的):比例、负向提示、seed。

    比例缺省时不传,让 provider 用自己的默认 —— 硬塞一个会把旧产物(那时还没有该列)
    重跑成另一种画面比例。
    """
    out: dict = {}
    if artifact.get("aspect_ratio"):
        out["ratio"] = artifact["aspect_ratio"]
    if artifact.get("negative_prompt"):
        out["negative_prompt"] = artifact["negative_prompt"]
    if artifact.get("seed") is not None:
        out["seed"] = artifact["seed"]
    return out


def _video_model(provider_name: str):
    """按 video_provider 字符串(= registry 里的 video model id)解析出 Model;未知返回 None。"""
    try:
        _, model = provider_pkg.provider_registry.resolve_model(provider_name)
        return model
    except ValueError:
        return None


def _provider_resolutions(provider_name: str) -> list[str]:
    model = _video_model(provider_name)
    return model.resolutions if model else []


def _supported_actions(provider_name: str) -> list[str]:
    model = _video_model(provider_name)
    return model.supported_actions if model else []


class Action:
    def __init__(
        self,
        id: str,
        label: str,
        param_schema_fn: Callable[[dict], list[dict]],
        available_fn: Callable[[dict, Any], bool],
        execute_fn: Callable[[dict, dict], Awaitable[dict]],
    ):
        self.id = id
        self.label = label
        self._param_schema_fn = param_schema_fn
        self._available_fn = available_fn
        self._execute_fn = execute_fn

    def param_schema(self, artifact: dict) -> list[dict]:
        return self._param_schema_fn(artifact)

    def available(self, artifact: dict, provider) -> bool:
        return self._available_fn(artifact, provider)

    async def execute(self, artifact: dict, params: dict) -> dict:
        return await self._execute_fn(artifact, params)


def _base_new(artifact: dict, action: str) -> dict:
    """继承父产物同源属性的新产物骨架。"""
    return {
        "project_id": artifact["project_id"],
        "shot_id": artifact["shot_id"],
        "parent_id": artifact["id"],
        "provider": artifact["provider"],
        "model": artifact.get("model", ""),
        "resolution": artifact["resolution"],
        "aspect_ratio": artifact.get("aspect_ratio") or "",
        "duration": artifact["duration"],
        "action": action,
        "prompt_text": artifact.get("prompt_text"),
        "negative_prompt": artifact.get("negative_prompt"),
        "references_json": artifact.get("references_json"),
        "audio_refs_json": artifact.get("audio_refs_json"),
        "task_id": "",
        "video_url": None,
        "local_path": None,
    }


async def _rerun_execute(artifact: dict, params: dict) -> dict:
    """原样重放这次生成:同 prompt / 参考图 / 比例 / 负向提示,并带上原 seed。

    不带 seed 的重跑只是"再抽一次"(出来必然是另一支视频)。seed 由平台在首次生成时回传
    并落库;provider 不支持 seed 时它为 None,此处照旧不传 —— 那种模型上"重跑"本就无法复现。
    """
    from drama_agent.services.ref_delivery import inline_local_refs
    provider = video_service.get_provider(artifact["provider"])
    sent_refs, sent_audio = await inline_local_refs(_refs_of(artifact), _audio_of(artifact))
    task_id = await provider.create_task(
        prompt=artifact.get("prompt_text") or "",
        duration=artifact["duration"],
        resolution=artifact["resolution"],
        **_replay_kwargs(artifact),
        references=sent_refs or None,
        audio_refs=sent_audio or None,
    )
    result = await provider.wait_for_task(task_id)
    new = _base_new(artifact, "rerun")
    new.update(task_id=task_id, video_url=result.video_url,
               seed=result.seed, revised_prompt=result.revised_prompt)
    return new


async def _regenerate_execute(artifact: dict, params: dict) -> dict:
    """改参数重生:**不带 seed** —— 用户改了参数就是要一个不一样的结果,
    固定 seed 会让部分改动看不出变化。比例/负向提示仍沿用父产物(用户没要求改它们)。"""
    from drama_agent.services.ref_delivery import inline_local_refs
    provider = video_service.get_provider(artifact["provider"])
    resolution = params.get("resolution", artifact["resolution"])
    duration = int(params.get("duration", artifact["duration"]))
    prompt = params.get("prompt") or artifact.get("prompt_text") or ""
    sent_refs, sent_audio = await inline_local_refs(_refs_of(artifact), _audio_of(artifact))
    kwargs = _replay_kwargs(artifact)
    kwargs.pop("seed", None)
    task_id = await provider.create_task(
        prompt=prompt, duration=duration, resolution=resolution, **kwargs,
        references=sent_refs or None, audio_refs=sent_audio or None)
    result = await provider.wait_for_task(task_id)
    new = _base_new(artifact, "regenerate")
    new.update(
        task_id=task_id, video_url=result.video_url,
        resolution=resolution, duration=duration, prompt_text=prompt,
        seed=result.seed, revised_prompt=result.revised_prompt,
    )
    return new


async def _upscale_execute(artifact: dict, params: dict) -> dict:
    provider = video_service.get_provider(artifact["provider"])
    task_id = await provider.create_regeneration(source_task_id=artifact["task_id"], resolution="2K")
    result = await provider.wait_for_task(task_id)
    new = _base_new(artifact, "upscale")
    new.update(task_id=task_id, video_url=result.video_url, resolution="2K")
    return new


def _supports(action_id: str):
    def _fn(artifact: dict, provider) -> bool:
        return action_id in _supported_actions(artifact["provider"])
    return _fn


def _upscale_available(artifact: dict, provider) -> bool:
    return (
        "upscale" in _supported_actions(artifact["provider"])
        # provider 实例必须真的实现 create_regeneration —— 即便被误配声明了 upscale,
        # 不具备该方法的 provider(seedance)也不放行,避免运行时 AttributeError。
        and hasattr(provider, "create_regeneration")
        and artifact.get("resolution") == "768P"
    )


ACTIONS: dict[str, Action] = {
    "rerun": Action(
        "rerun", "相同 prompt 重跑",
        param_schema_fn=lambda a: [],
        available_fn=_supports("rerun"),
        execute_fn=_rerun_execute,
    ),
    "regenerate": Action(
        "regenerate", "改参数重生",
        param_schema_fn=lambda a: [
            {"name": "resolution", "type": "enum", "label": "分辨率",
             "options": _provider_resolutions(a["provider"]), "default": a["resolution"]},
            {"name": "duration", "type": "int", "label": "时长(秒)", "min": 4, "max": 15,
             "default": a["duration"]},
            {"name": "prompt", "type": "text", "label": "Prompt",
             "default": a.get("prompt_text") or ""},
        ],
        available_fn=_supports("regenerate"),
        execute_fn=_regenerate_execute,
    ),
    "upscale": Action(
        "upscale", "升清 2K",
        param_schema_fn=lambda a: [],
        available_fn=_upscale_available,
        execute_fn=_upscale_execute,
    ),
}


def available_actions(artifact: dict) -> list[dict]:
    provider = video_service.get_provider(artifact["provider"])
    out = []
    for action in ACTIONS.values():
        if action.available(artifact, provider):
            out.append({
                "id": action.id,
                "label": action.label,
                "param_schema": action.param_schema(artifact),
            })
    return out
