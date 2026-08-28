"""Tests for workflow state types."""
from drama_agent.workflow.state import DramaState, ShotDict, PromptDict, VideoDict


def test_drama_state_keys():
    """DramaState TypedDict should have all required keys."""
    required_keys = [
        "project_id", "title", "raw_input", "genre", "script_id",
        "story_analysis", "screenplay", "screenplay_approved",
        "shots", "prompts", "prompts_approved",
        "videos", "references",
        "current_stage", "error", "llm_model", "video_model", "video_provider",
    ]
    annotations = DramaState.__annotations__
    for key in required_keys:
        assert key in annotations, f"Missing key in DramaState: {key}"


def test_shot_dict_keys():
    required = ["shot_id", "scene_number", "shot_number", "shot_type",
                "camera_movement", "duration_seconds", "description",
                "characters", "dialogue", "action", "location"]
    for key in required:
        assert key in ShotDict.__annotations__


def test_prompt_dict_keys():
    required = ["shot_id", "prompt_text", "negative_prompt",
                "reference_image_url", "approved", "edited_prompt"]
    for key in required:
        assert key in PromptDict.__annotations__
