"""流水线步骤的单一真相:有哪些步、顺序、哪步是条件分支、当前处在哪步。

与 graph.py 的图结构一一对应;图变了就改这里(同处维护)。前端只渲染本模块经
status 端点下发的结果,不再自带一份步骤定义 —— 避免前后端流水线结构漂移。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineStep:
    key: str
    label: str
    stages: tuple[str, ...]  # 归属该步的 current_stage / 中断点取值


# canonical 顺序(与图对齐)。keyframes 步仅在 use_keyframes 开启时插入(见 build_pipeline)。
_STEPS: tuple[PipelineStep, ...] = (
    PipelineStep("analysis", "故事分析", ("starting", "analyzing", "story_analyzed")),
    PipelineStep("screenplay", "生成剧本", ("screenplay_written", "screenplay_revision_requested")),
    PipelineStep("screenplay_review", "审核剧本", ("screenplay_review", "screenplay_approved")),
    PipelineStep("storyboard", "分镜", ("storyboard_ready",)),
    PipelineStep("looks", "审核造型",
                 ("looks_assigned", "look_review", "looks_approved", "looks_revision_requested")),
    PipelineStep("prompts", "Prompt",
                 ("prompts_ready", "prompts_review", "prompts_approved", "prompts_revision_requested")),
    PipelineStep("video", "生成视频", ("videos_generated", "assembly_failed")),
    PipelineStep("done", "完成", ("completed",)),
)

_KEYFRAME_STEP = PipelineStep(
    "keyframes", "关键帧",
    ("keyframes_ready", "keyframes_review", "keyframes_approved", "keyframes_revision_requested"),
)


def build_pipeline(
    use_keyframes: bool, current_stage: str | None, costs: dict[str, float] | None = None
) -> dict:
    """据本集配置算出实际步骤序列 + 当前步 key,可选挂上每步成本。

    use_keyframes 决定是否含"关键帧"步(插在 Prompt 与 生成视频 之间)。
    current_stage 命中某步的 stages 集 → 该步为当前步;命中不到(如 created/failed)→ current=None。
    costs 的键是 current_stage(记账 node 用的词表),按 stages 归并到步上 —— 同一步的多个
    stage 相加;不属任何步的 stage 丢弃(不凭空造步)。无记账的步不挂 cost 字段。
    """
    steps = list(_STEPS)
    if use_keyframes:
        idx = next(i for i, s in enumerate(steps) if s.key == "video")
        steps.insert(idx, _KEYFRAME_STEP)
    current: str | None = None
    for s in steps:
        if current_stage in s.stages:
            current = s.key
            break
    by_stage = costs or {}
    out = []
    for s in steps:
        item: dict = {"key": s.key, "label": s.label}
        hit = [by_stage[st] for st in s.stages if st in by_stage]
        if hit:
            item["cost"] = round(sum(hit), 4)
        out.append(item)
    return {"steps": out, "current": current}
