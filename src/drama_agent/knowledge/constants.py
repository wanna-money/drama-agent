"""内置领域软知识常量。从原 ChromaDB seed + 节点硬编码 prompt 收敛而来。

软知识("如何做得好")在此;硬约束枚举(合法取值)在 workflow/constants.py。
"""

PROMPT_TEMPLATES: dict[str, dict[str, list[str]]] = {
    "seedance": {
        "CU": ["Seedance CU shot template: Close-up shot, [subject] with [emotion] expression, "
               "[lighting] light, cinematic quality, shallow depth of field, 4K"],
        "LS": ["Seedance LS shot template: Long shot, [subject] in [environment], "
               "[camera_movement] camera movement, establishing atmosphere, cinematic wide angle"],
        "MS": ["Seedance MS shot template: Medium shot, [subject] [action], [lighting] lighting, "
               "film-quality, natural color grading"],
        "ELS": ["Seedance ELS template: Extreme long shot, vast [environment] with [subject] tiny "
                "in frame, epic scale, aerial perspective, cinematic landscape"],
    },
}

PROMPT_GUIDES: dict[str, list[str]] = {
    "seedance": [
        "结构:精准主体 + 动作细节 + 场景环境 + 光影色调 + 镜头运镜 + 视觉风格 + 画质 + 约束。"
        "用「镜头1/镜头2」按事件顺序分段,每段依次写:运镜或切换 → 主体动作与表情 → 位置/空间变化 → 音效人声。",
        "不要用精确秒数(如「0-3秒」)控时,Seedance 2.0 对硬时长支持不稳定;用镜头分段表达先后顺序。",
        "参考素材在文本里显式绑定编号与用途:「将 图片1 中穿红裙戴草帽的女人定义为 主体1」,"
        "之后统一用同一标签或 主体N@图片N;用 2-3 个稳定静态特征(服饰/发型/外观)保证唯一可识别。",
        "动作肢体化并量化幅度速度(缓慢抬手、用力蹬地),优先低缓连续小动作、写清前后承接;"
        "情绪外化为身体细节(写「肩膀微颤、攥紧衣角」而非「很悲伤」)。",
        "一个镜头只指定 1 种运镜;标准术语(中景/特写/全景/缓慢推镜/平稳横移/固定镜头)可直写,小众术语补描述性解释。"
        "用符号区分信息类型:()音乐、<>音效、{}台词、【】字幕;台词语言统一,避免中英混用。",
        "约束词必写「保持无字幕」「不要生成水印/Logo」;竖屏(9:16)出字幕概率明显高于横屏,短剧要额外强化无字幕约束。"
        "人物 ID 漂移的根因是人脸参考权重不足——用独立大头照+全身照,越需精准的素材放越前。",
    ],
    "minimax": [
        "结构:时长与画幅 + 题材风格 + 素材序号映射 + 核心剧情 + 镜别与情绪 + 声音。"
        "开头就点明时长与画幅(如「15s, 9:16 vertical」);输出 768P/2K、时长 4-15 秒整数;提示词上限 7000 字符。英文为主,中文亦可。",
        "运镜用方括号紧跟在关键描述之后:[pan]、[zoom]、[static]——这是 H3 特有的相机控制写法。",
        "多素材按上传顺序用序数指代并说明各自用途:"
        "'appearance follows reference images 1 and 2; motion follows reference video 1'。",
        "H3 原生生成音频,声音需求直接写进提示词(环境音、音色、配乐节奏)。",
        "竖屏短剧推荐写法:画幅 + 题材(如 ReelShort/DramaBox 风格)+ 人物与场景图映射 + 剧情主线 + "
        "'medium-close and close shots for eye contact and tension' 这类镜别情绪指示。",
    ],
    "all": [
        "Character continuity: for consistent appearance across shots, include detailed physical "
        "description in every prompt: hair color, clothing color/style, build, distinctive features.",
        "Frame chaining: with first_frame reference, keep subject position, lighting direction, "
        "color temperature; add 'seamlessly continuing from previous shot, consistent lighting and color'.",
    ],
}

CINEMATOGRAPHY: dict[str, list[str]] = {
    "shot_type": ["Shot types: ELS establishes vast environment; LS full body/location; MS waist "
                  "up for dialogue; CU face for emotion; ECU eyes/hands for intense detail"],
    "camera": ["Camera movements: static stable; pan horizontal; tilt vertical; dolly toward/away; "
               "zoom focal change; tracking follows subject; crane vertical arc"],
    "lighting": ["Lighting: natural outdoor sun; golden hour warm amber; three-point key+fill+back "
                 "studio; low-key dramatic shadows; high-key bright even"],
    "continuity": ["Continuity: match eyeline; keep screen direction (180-degree rule); match prop "
                   "positions; consistent lighting within scene; wardrobe unchanged within scene"],
    "pacing": ["Short drama pacing: opening sets tone in first 30s; each scene max 3-5 shots; "
               "climax faster cuts; emotional peaks use close-ups; action uses medium/long with movement"],
}

SCREENPLAY_GUIDE: list[str] = [
    "Each scene should advance plot or reveal character.",
    "Write natural, character-appropriate dialogue.",
    "Include clear action lines describing visual elements.",
    "End with a satisfying resolution; each scene 30-90 seconds when filmed.",
]

STORYBOARD_GUIDE: list[str] = [
    "Break scenes into filmable single-clip shots; be specific about action and visual content.",
    "Opening shot (ELS/LS): establish setting; development (MS/CU): reactions/dialogue; "
    "climax (CU/ECU, fast): intensity; resolution (LS/MS): aftermath.",
    "Include which characters appear in each shot.",
]
