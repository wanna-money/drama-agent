"""Seed the RAG knowledge base with video generation rules and prompt templates.

Run: python -m drama_agent.knowledge.seed
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


SEEDANCE_PROMPT_GUIDE = [
    {
        "id": "seedance_action_guide",
        "text": "Seedance action prompts: Use present continuous tense for actions. Good: 'A warrior is slashing the sword upward, sparks flying'. Bad: 'A warrior slash sword'. Include motion direction and intensity.",
        "meta": {"provider": "seedance", "category": "action"}
    },
    {
        "id": "seedance_camera_guide",
        "text": "Seedance camera movement: Specify camera moves at end of prompt. Examples: 'camera slowly pushes in', 'camera tracks left following the character', 'static camera, locked off', 'camera cranes down from above'.",
        "meta": {"provider": "seedance", "category": "camera"}
    },
    {
        "id": "seedance_quality_guide",
        "text": "Seedance quality keywords: Append to all prompts: 'cinematic quality, professional lighting, 4K, film grain, color graded'. For emotional scenes add: 'shallow depth of field, bokeh background'.",
        "meta": {"provider": "seedance", "category": "quality"}
    },
    {
        "id": "seedance_character_consistency",
        "text": "Seedance character consistency: Describe character appearance in EVERY shot they appear. Include: specific hair (color, length, style), clothing (color, type, any details), build, and one distinctive feature. Example: 'A young woman with shoulder-length black hair, wearing a red qipao dress, slim build, entering the tea house'.",
        "meta": {"provider": "seedance", "category": "consistency"}
    },
    {
        "id": "seedance_negative_guide",
        "text": "Seedance negative prompts: Always include: 'blurry, low quality, artifacts, watermark, text overlay, duplicate frames, flickering, distorted faces, extra limbs'. For dialogue shots add: 'mouth not moving, static expression'.",
        "meta": {"provider": "seedance", "category": "negative"}
    },
    {
        "id": "bailian_prompt_guide",
        "text": "百炼/万相视频生成提示词规范：可用中文，描述要具体。格式：[主体] + [动作] + [环境] + [光线] + [质感]。例如：'一位身穿白色汉服的古装女子在竹林中缓缓行走，阳光从竹叶间洒落，电影质感，色调清新'。",
        "meta": {"provider": "bailian", "category": "general"}
    },
    {
        "id": "bailian_character_guide",
        "text": "百炼人物一致性：每个镜头都需描述人物外貌。格式：[发型颜色长度]+[肤色]+[服装颜色款式]+[体型特征]。示例：'黑色长发、白皙皮肤、身穿蓝色牛仔外套的年轻男子'。",
        "meta": {"provider": "bailian", "category": "consistency"}
    },
    {
        "id": "drama_pacing_guide",
        "text": "Short drama video pacing: Opening shot (ELS/LS, 5-10s): establish setting and mood. Development shots (MS/CU, 5s each): character reactions and dialogue. Climax (fast cuts, CU/ECU, 5s): intense close-ups. Resolution (LS/MS, 5-10s): wider shots showing aftermath.",
        "meta": {"provider": "all", "category": "pacing"}
    },
    {
        "id": "frame_chaining_guide",
        "text": "Frame chaining for visual continuity: When using first_frame reference (last frame of previous clip), keep the same subject position, lighting direction, and color temperature in the new prompt. Add 'seamlessly continuing from previous shot, consistent lighting and color' to the prompt.",
        "meta": {"provider": "all", "category": "continuity"}
    },
]


def seed_knowledge():
    from drama_agent.services.rag_service import RAGService
    svc = RAGService()

    # Add extended prompt guides
    collection = svc._prompt_templates
    for item in SEEDANCE_PROMPT_GUIDE:
        try:
            collection.delete(ids=[item["id"]])
        except Exception:
            pass
        collection.add(
            documents=[item["text"]],
            ids=[item["id"]],
            metadatas=[item["meta"]],
        )
    print(f"Seeded {len(SEEDANCE_PROMPT_GUIDE)} knowledge entries")
    print(f"Total prompt templates: {collection.count()}")


if __name__ == "__main__":
    seed_knowledge()
