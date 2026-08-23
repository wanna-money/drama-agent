"""评测样本集：每节点的输入 + 通过阈值。第一版每节点 1 个种子样本。"""

CASES: dict[str, list[dict]] = {
    "story_analyzer": [
        {"node": "story_analyzer",
         "inputs": {"raw_input": "A lonely lighthouse keeper receives a mysterious letter.",
                    "genre": "drama"},
         "min_pass": 1.0},
    ],
    "screenplay_writer": [
        {"node": "screenplay_writer",
         "inputs": {"analysis": {
             "title": "The Letter", "genre": "drama", "setting": "remote island lighthouse",
             "tone": "somber", "themes": ["isolation"], "plot_summary": "A keeper reads a letter.",
             "scene_count_estimate": 3,
             "characters": [{"name": "Elias", "appearance": "old man, grey beard, wool sweater",
                             "personality": "stoic"}]}},
         "min_pass": 1.0},
    ],
    "storyboard_director": [
        {"node": "storyboard_director",
         "inputs": {"screenplay": "INT. LIGHTHOUSE - NIGHT\nElias opens the letter, hands trembling.",
                    "analysis": {"characters": [{"name": "Elias", "appearance": "old man, grey beard"}]}},
         "min_pass": 1.0},
    ],
    "prompt_engineer": [
        {"node": "prompt_engineer",
         "inputs": {"shot": {"shot_type": "CU", "camera_movement": "static", "duration_seconds": 5,
                             "location": "INT. LIGHTHOUSE",
                             "description": "trembling hands holding a letter",
                             "action": "opens envelope", "dialogue": "", "characters": ["Elias"]},
                    "char_descriptions": ["Elias: old man, grey beard, wool sweater"],
                    "templates": [], "cin_rules": [], "provider": "seedance"},
         "min_pass": 1.0},
    ],
}
