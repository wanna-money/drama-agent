import chromadb
from chromadb.config import Settings as ChromaSettings
from drama_agent.config import settings


class RAGService:
    def __init__(self):
        self._client = chromadb.PersistentClient(
            path=settings.chroma_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._prompt_templates = self._client.get_or_create_collection("prompt_templates")
        self._cinematography = self._client.get_or_create_collection("cinematography_rules")
        self._character_profiles = self._client.get_or_create_collection("character_profiles")
        self._seed_knowledge()

    def _seed_knowledge(self):
        """Seed built-in knowledge if collections are empty."""
        if self._prompt_templates.count() == 0:
            self._seed_prompt_templates()
        if self._cinematography.count() == 0:
            self._seed_cinematography()

    def _seed_prompt_templates(self):
        templates = [
            (
                "seedance_cu",
                "Seedance CU shot template: Close-up shot, [subject] with [emotion] expression, [lighting] light, cinematic quality, shallow depth of field, 4K",
                {"provider": "seedance", "shot_type": "CU"},
            ),
            (
                "seedance_ls",
                "Seedance LS shot template: Long shot, [subject] in [environment], [camera_movement] camera movement, establishing atmosphere, cinematic wide angle",
                {"provider": "seedance", "shot_type": "LS"},
            ),
            (
                "seedance_ms",
                "Seedance MS shot template: Medium shot, [subject] [action], [lighting] lighting, film-quality, natural color grading",
                {"provider": "seedance", "shot_type": "MS"},
            ),
            (
                "seedance_els",
                "Seedance ELS template: Extreme long shot, vast [environment] with [subject] tiny in frame, epic scale, aerial perspective, cinematic landscape",
                {"provider": "seedance", "shot_type": "ELS"},
            ),
            (
                "bailian_cu",
                "近景特写：[人物]，[表情]神情，[光线]打光，电影质感，浅景深，4K超清画质",
                {"provider": "bailian", "shot_type": "CU"},
            ),
            (
                "bailian_ls",
                "远景：[人物]在[环境]中，[镜头运动]镜头，建立空间感，电影级广角",
                {"provider": "bailian", "shot_type": "LS"},
            ),
            (
                "bailian_ms",
                "中景：[人物][动作]，[光线]打光，电影质感，自然色彩",
                {"provider": "bailian", "shot_type": "MS"},
            ),
            (
                "continuity_tip",
                "Character continuity: For consistent character appearance across shots, include detailed physical description: hair color, clothing color and style, build, and any distinctive features in every prompt.",
                {"provider": "all", "shot_type": "continuity"},
            ),
        ]
        docs, ids, metas = zip(*[(t[1], t[0], t[2]) for t in templates])
        self._prompt_templates.add(
            documents=list(docs), ids=list(ids), metadatas=list(metas)
        )

    def _seed_cinematography(self):
        rules = [
            (
                "shot_types",
                "Shot types: ELS (Extreme Long Shot) - establishes vast environment; LS (Long Shot) - full body visible, establishes location; MS (Medium Shot) - waist up, dialogue scenes; CU (Close-Up) - face fills frame, emotional moments; ECU (Extreme Close-Up) - eyes or hands, intense detail",
                {"category": "shot_type"},
            ),
            (
                "camera_moves",
                "Camera movements: static - no movement, stable; pan - horizontal rotation; tilt - vertical rotation; dolly - physical camera move toward/away subject; zoom - lens focal length change; tracking - camera follows subject; crane - vertical arc movement",
                {"category": "camera"},
            ),
            (
                "lighting_types",
                "Lighting setups: natural light - outdoor sun/sky; golden hour - warm amber tones at sunrise/sunset; three-point - key+fill+backlight studio setup; low-key - dramatic shadows high contrast; high-key - bright evenly lit comedies/ads",
                {"category": "lighting"},
            ),
            (
                "continuity_rules",
                "Visual continuity rules: 1) Match eyeline direction between cuts. 2) Maintain screen direction (180-degree rule). 3) Match prop positions between shots. 4) Consistent lighting within same scene. 5) Character wardrobe unchanged within scene.",
                {"category": "continuity"},
            ),
            (
                "drama_pacing",
                "Short drama pacing: opening scene sets tone in first 30s; each scene max 3-5 shots; climax uses faster cuts (shorter duration); emotional peaks use close-ups; action sequences use medium/long shots with movement",
                {"category": "pacing"},
            ),
        ]
        docs, ids, metas = zip(*[(r[1], r[0], r[2]) for r in rules])
        self._cinematography.add(
            documents=list(docs), ids=list(ids), metadatas=list(metas)
        )

    def query_prompt_templates(
        self, shot_type: str, provider: str, n_results: int = 3
    ) -> list[str]:
        results = self._prompt_templates.query(
            query_texts=[f"{shot_type} {provider} video prompt"],
            n_results=n_results,
        )
        return results["documents"][0] if results["documents"] else []

    def query_cinematography(self, topic: str, n_results: int = 2) -> list[str]:
        results = self._cinematography.query(
            query_texts=[topic],
            n_results=n_results,
        )
        return results["documents"][0] if results["documents"] else []

    def save_character_profile(
        self, project_id: str, character_name: str, description: str
    ):
        doc_id = f"{project_id}_{character_name}"
        try:
            self._character_profiles.delete(ids=[doc_id])
        except Exception:
            pass
        self._character_profiles.add(
            documents=[description],
            ids=[doc_id],
            metadatas=[{"project_id": project_id, "character_name": character_name}],
        )

    def get_character_description(
        self, project_id: str, character_name: str
    ) -> str | None:
        doc_id = f"{project_id}_{character_name}"
        try:
            result = self._character_profiles.get(ids=[doc_id])
            return result["documents"][0] if result["documents"] else None
        except Exception:
            return None


rag_service = RAGService()
