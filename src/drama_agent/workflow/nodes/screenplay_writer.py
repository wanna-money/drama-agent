from drama_agent.config import settings
from drama_agent.workflow.state import DramaState
from drama_agent.knowledge.store import knowledge_store
from drama_agent.services.llm_service import llm_service
from drama_agent.workflow.cast_constraint import cast_constraint_block
from drama_agent.workflow.prompt_rules import system_prompt

SYSTEM = system_prompt("""You are a professional screenplay writer specializing in short dramas.
Write screenplays in standard format with scene headings, action lines, and dialogue.
Each scene should be self-contained and visually compelling.""")


def build_prompt(
    analysis: dict, target_seconds: int | None = None,
    cast_names: list[str] | None = None,
) -> tuple[str, str]:
    """target_seconds:全片目标时长(秒),驱动篇幅与场次;缺省取 config 的 target_episode_seconds。

    cast_names:已确认身份的角色名单(cast_review 的产物)。非空时作为**硬约束**下发:
    有台词/有形象的角色只能取自名单。名单外的人物没有 character_id,拿不到造型与外貌,
    在视频里的形象将完全失控 —— 需要群演时用 UNNAMED_EXTRA_HINT 的写法,不给它起名字。
    """
    target_seconds = target_seconds or settings.target_episode_seconds
    char_list = "\n".join(
        f"- {c.get('name', 'Unknown')}: {c.get('appearance', '')} | {c.get('personality', '')}"
        for c in analysis.get("characters", [])
        if c.get("name")
    )
    cast_block = cast_constraint_block(cast_names)

    # 软知识(如何写好)来自 knowledge;硬性格式要求留在下方 prompt。
    guides = knowledge_store.retrieve("screenplay_guide")
    guide_block = "\n".join(f"- {g}" for g in guides)

    methodology = "\n\n".join(knowledge_store.retrieve("story_structure"))
    methodology_block = f"\n\nStory-structure methodology:\n{methodology}" if methodology else ""

    user_prompt = f"""Write a complete short drama screenplay based on this analysis:

TITLE: {analysis.get("title")}
GENRE: {analysis.get("genre")}
SETTING: {analysis.get("setting")}
TONE: {analysis.get("tone")}
THEMES: {", ".join(analysis.get("themes", []))}
PLOT: {analysis.get("plot_summary")}

CHARACTERS:
{char_list}{cast_block}

Format requirements:
- Use standard screenplay format (INT./EXT. LOCATION - DAY/NIGHT)
- 全片目标时长约 {target_seconds} 秒（约 {target_seconds // 60} 分 {target_seconds % 60} 秒）。
  按这个长度控制篇幅:场次数、每场的动作与对白量都要匹配,不要写成远超目标时长的长片。
  参考 {analysis.get("scene_count_estimate", 5)} 场左右,但以目标时长为准。
- 只输出剧本本体(场景标题 / 动作 / 对白)。**不要**在开头写"剧本标题/类型/时长"之类的
  元信息表头 —— 时长由系统按分镜实际计算,你写的任何时长数字都是编的。

Craft guidelines:
{guide_block}{methodology_block}

Write the complete screenplay now:"""
    return SYSTEM, user_prompt


async def screenplay_writer_node(state: DramaState) -> dict:
    from drama_agent.services import cast_service
    analysis = state["story_analysis"]
    cast_names = await cast_service.roster_names(state["project_id"], state.get("cast"))
    system, user_prompt = build_prompt(
        analysis, settings.target_episode_seconds, cast_names=cast_names,
    )

    screenplay = await llm_service.complete(
        system, user_prompt, temperature=0.7, model=state.get("llm_model")
    )

    return {
        "screenplay": screenplay,
        "screenplay_approved": False,
        "current_stage": "screenplay_written",
    }
