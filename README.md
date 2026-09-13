# Drama Agent — AI 短剧制作平台

基于 LangGraph 多 Agent 的短剧制作平台。一段故事（或一整本小说）进来，自动完成故事分析 → 角色对齐 → 剧本 → 分镜 → 造型 → 视频 Prompt → 视频生成 → 合成，关键节点由人工确认。

## 核心概念

理解这四个词，产品结构就清楚了：

| 概念 | 是什么 | 关系 |
|------|--------|------|
| **作品**（Project） | 一部剧的容器 | 含多集；小说改编在作品级发起 |
| **剧本**（Script） | **内容唯一的家** —— 故事原文 + 剧本正文 + 角色名单 | 全局可复用，不限于某个作品 |
| **集**（Episode） | 一条独立流水线 | **只引用剧本**（`script_id` 必填），自身不存内容 |
| **角色 / 造型**（Character / Look） | 作品级的人物身份，及其不同服饰发型 | 剧本只按名字绑定身份，形象归 Look |

两条开拍入口，都先落成剧本再建集：

- **输入故事** —— 分析文本 → 确认角色身份 → 存入剧本库 → 建集
- **小说改编** —— 整本小说 → 确认全书角色 → 切成 N 个剧本 → 一次建出 N 集

> 一集**从哪儿起跑**取决于源剧本**有没有正文**：有正文（复用成稿 / 改编切片）直达分镜；只有故事原文则从故事分析跑起。判据的唯一权威是 `episode_service.entry_mode()`。

「新建创作」页还有第三种模式与上述两种入口并列：**直接生成**（简单模式）——手写发给视频模型的提示词，不经 LLM / 分镜 / 审核，提交即出一支视频（落成「散片」，Clip）。散片不参与剧集合成、不沉淀进素材库，用于快速验证 prompt 或单条素材产出。参考图/参考视频通过 `@` 引用素材库、本项目已有图或已同步存储的散片；视频编辑 / 延长这两种任务模式依赖「存储管理」配置的对象存储（见下方「视频生成说明」）。

完整的页面级操作步骤见 [使用手册](docs/user-manual.md)。

## 流水线

```
                    ┌── 有正文 ────────────────────────────────┐
   START ─ route_entry                                          ▼
                    └── 只有故事原文 ──┐                 storyboard_director
                                       ▼                        │
                            story_analyzer                storyboard_review
                                       │                    │        ▲
                                 cast_resolve               │        └─ 退回重排
                                       │                    ▼
                       [⏸ cast_review 确认角色身份]     look_assignment
                                       │                    │
                            screenplay_writer          [⏸ look_review 审核造型]
                                       │                    │
                     [⏸ screenplay_review 审核剧本]         ▼
                                  │        ▲           prompt_engineer
                                  │        └─ 退回改写       │
                                  └──────────────►  [⏸ prompts_review 审核 Prompt]
                                                            │
                                       ┌────────────────────┴──── 开了关键帧 ──┐
                                       ▼                                        ▼
                                video_generator ◄──── [⏸ keyframes_review] ─ keyframe_generator
                                       │
                                video_assembler ──► END
```

`⏸` 是 LangGraph `interrupt()` 的人工卡点，前端在剧集页对应步骤渲染审核面板。图定义在 `workflow/graph.py`，步骤清单的单一真相在 `workflow/pipeline_steps.py`（前端只渲染后端下发的结果）。

## 运行时设计

- **任务不跑在请求里**：start/resume 入队一条 `Job`（`UNIQUE(episode_id, kind, dedup_key)` 保证幂等），后台 `JobWorker` 领取执行（PG 用 `FOR UPDATE SKIP LOCKED`，SQLite 用原子 UPDATE）。心跳续租 + 启动回收僵尸 → 崩溃可恢复、多实例分摊。
- **状态两层**：`Project.status` / `Episode.status` 存粗粒度生命周期枚举（created/queued/running/paused/completed/failed）；细阶段以 LangGraph checkpointer 为准。
- **事件流**：节点状态变更与业务变更同事务写 `events` 表，带每集自增 `seq`。前端 WebSocket 带 `last_seq` 重连，断线不丢事件。
- **声明式 Provider**：LLM / 视频 / 图像三类 provider 由注册表统一路由，调用方对具体厂商零感知；接一个已有协议的新 provider = 加一条声明。
- **声明式知识层**：`KnowledgeStore` 协议 + 按 kind 路由的注册表，内置 `constant` / `markdown` / `dify` 三种后端（`pgvector` 预留），降级统一在注册表一处兜。

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端 | FastAPI + Python 3.12+ |
| 工作流 | LangGraph（StateGraph + interrupt + SQLite checkpointer）|
| 文本模型 | 统一 OpenAI 兼容接口，按 provider 注册表路由 |
| 视频模型 | Seedance 2.0 / 2.5（火山引擎）、MiniMax H3 |
| 图像模型 | 豆包 Seedream、OpenAI GPT Image |
| 知识层 | 声明式多后端（constant / markdown / dify）|
| 数据库 | SQLAlchemy 2.0 async · SQLite（本地）/ PostgreSQL（多实例）|
| 前端 | React + TypeScript + Semi Design + Vite |
| 包管理 | uv（后端）/ pnpm（前端）|

## 快速开始

### 1. 安装依赖

```bash
uv sync --extra dev            # 后端 + 开发依赖(pytest/ruff/mypy)
cd frontend && pnpm install    # 前端
```

### 2. 配置

```bash
cp .env.example .env
```

模型凭证既可写进 `.env`，也可在前端「模型管理」页直接填（存 DB，改完即时生效）。至少配一个视频 provider：

```env
# 文本模型(内置 DeepSeek provider 读的是 DRAMA_API_KEY;base_url 锁死官方地址)
DRAMA_API_KEY=sk-xxx

# 视频（至少一个）
ARK_API_KEY=xxx                     # 火山引擎 Seedance
SEEDANCE_ENDPOINT_ID=ep-xxx
MINIMAX_VIDEO_API_KEY=xxx           # MiniMax H3（注意域名是 api.minimaxi.com）

# 知识库（可选，留空走内置常量兜底）
DIFY_BASE_URL=
DIFY_API_KEY=
DIFY_DATASET_IDS={}

# 存储
DATABASE_URL=sqlite+aiosqlite:///./data/drama_agent.db
LANGGRAPH_DB_PATH=./data/langgraph_checkpoints.db
```

### 3. 启动

```bash
bash start.sh          # 前后端一起（推荐），./stop.sh 停
```

单独起后端：

```bash
.venv/bin/python -m uvicorn drama_agent.main:app --reload --reload-dir src --port 8888
cd frontend && pnpm dev                                    # 前端 :5173
```

> ⚠️ **后端不要用 `uv run uvicorn` 起。** uv 把 uvicorn 当子进程拉起却不转发 SIGTERM，信号只到 uv，FastAPI lifespan 的关停分支便不执行 → checkpointer 连接不关 → 进程占着 DB 退不掉，多次重启后堆出一批僵尸，只能 `kill -9`。判据：停机日志里应出现 `Drama Agent shutting down`。

访问 http://localhost:5173

## 使用流程

1. **新建作品** —— 纯剧本作品直接建；小说作品把整本正文贴进去
2. **（小说）改编分集** —— 作品页点「开始改编」→ 确认全书角色身份 → 切出 N 个剧本 → 点「建出 N 集」
3. **（逐集）新建一集** —— 输入故事（自动存入剧本库）或从剧本库挑一条复用；也可选「直接生成」跳过流水线，手写 prompt 直出一支散片
4. **开拍** —— 剧集页点「开始制作」，流水线按左栏步骤推进
5. **人工卡点** —— 依次确认：角色身份 → 剧本 → 造型 → Prompt →（可选）关键帧
6. **成片** —— 各分镜视频合成为完整短剧，可在线预览、下载；单镜可重跑 / 改参重生 / 升清

详细的逐页操作步骤（含角色造型、素材库、模型 / 存储管理、产物树动作）见 [docs/user-manual.md](docs/user-manual.md)。

## 项目结构

```
drama-agent/
├── src/drama_agent/
│   ├── api/              # FastAPI 路由(projects/episodes/workflow/scripts/
│   │                     #   adaptation/characters/assets/artifacts/providers/…)
│   ├── db/               # SQLAlchemy 模型、会话、枚举、方言适配(PG/SQLite 差异集中处)
│   ├── provider/         # LLM / video / image provider 注册表 + 内置声明
│   ├── knowledge/        # 声明式知识后端(constant/markdown/dify)+ 按 kind 路由
│   ├── services/         # 业务服务(script/episode/cast/adaptation/video/job/cost/…)
│   ├── evals/            # 节点质量评测(独立于 pytest 跑)
│   └── workflow/
│       ├── graph.py            # StateGraph 定义 + 人工卡点节点
│       ├── runner.py           # 图执行、初始状态构建、事件广播
│       ├── worker.py           # JobWorker 后台任务运行时
│       ├── pipeline_steps.py   # 流水线步骤单一真相(下发前端)
│       ├── state.py            # DramaState TypedDict
│       └── nodes/              # 各单职责 Agent 节点
├── frontend/src/
│   ├── pages/            # 作品/剧集/剧本/角色/素材/模型管理
│   ├── components/       # PageShell、审核面板、改编面板等公共组件
│   └── services/api.ts   # 后端接口类型与调用
├── tests/                # pytest 套件(api/services/workflow/db/ops)
├── scripts/reset_db.py   # 清库重来(保留 provider 凭证)
├── start.sh / stop.sh
└── pyproject.toml
```

## 开发

```bash
# 后端
uv run pytest -q                       # 全量测试
uv run pytest tests/api -v             # 按目录
uv run ruff check src tests
uv run mypy src

# 前端(先 cd frontend)
npx vitest run                         # 全量测试
npx tsc --noEmit                       # 类型检查
pnpm build                             # 生产构建 → frontend/dist/
```

## 数据库说明

**无迁移工具**，建表靠 `db/session.py:init_db()` 的 `create_all`。

- 新增**表**：加到 `db/models.py` 即自动建。
- 新增/删除**列**：`create_all` **不会**改已有表，须手动执行一次 `ALTER`。
- 新增**模型能力字段**：内置 provider 的 `models_json` 已存进 DB，且 seeder 不覆盖用户可改字段，
  故代码独占的能力字段（如 `supports_seed`）由 `provider/seed.py` 的 `CODE_OWNED_MODEL_FIELDS` 回填，
  列表字段仅在库里为空时补。**加了新能力字段要同步登记到那两个元组里**，否则它对已装机器永远不可见。
- 新增 `Project.visual_style`（作品级视觉风格）：已有库跑一次
  `uv run python scripts/migrate_visual_style.py`（幂等，列已存在则跳过）。
- 本地清库重来：先停后端，再 `uv run python scripts/reset_db.py`（provider 凭证整表保留；langgraph checkpoint 是另一个 sqlite 文件，需单独删）。

生产用 PostgreSQL（`postgresql+asyncpg://…`）可启用多实例；需自行安装 `asyncpg`（未列入默认依赖）。方言差异只在 `db/dialect.py`。

## 功能面板一览

除主流水线外，前端还有几个独立管理面板：

| 面板 | 路由 | 做什么 |
|------|------|--------|
| 素材库 | `/assets` | 全局共享的参考图（人物/背景/道具/服饰四类）；可直接上传，或用图像模型 AI 生成 / AI 改图后存入 |
| 角色管理 | `/projects/:id/characters` | 作品级角色 + 造型（Look）+ 四视图管理；四视图可 AI 生成一整张 sheet 自动裁切，或从素材库导入现成图裁切；角色还可挂音色（wav/mp3） |
| 模型管理 | `/providers` | 配置 LLM / 视频 / 图像三类 provider 的凭证与模型声明；「自定义接入路径」高级选项用于同协议不同网关的路径/响应差异（见 [docs/user-manual.md](docs/user-manual.md) 附录「自定义接入路径」） |
| 存储管理 | `/storage` | 配置对象存储（如腾讯云 COS），供参考视频拿到公网 URL——视频编辑/延长依赖它 |

逐页操作细节见 [docs/user-manual.md](docs/user-manual.md)。

## 扩展点

加东西走这些，别另起炉灶：

| 要加什么 | 怎么加 |
|----------|--------|
| LLM / 视频 / 图像 provider | `provider/{llm,video,image}/providers.py` 加一条声明；新协议再在 `protocols.py` 登记 |
| 视频动作（重跑/重生成/超分） | `services/video_actions.py` 的 `ACTIONS` 加一个 `Action`（谓词 + execute + 参数 schema，前端按 schema 自动渲染表单）|
| 知识库来源 | 已有类型：config 的 `knowledge_backends` 加一条声明（零代码）；新协议：实现 `KnowledgeStore` + `BACKEND_TYPES` 登记一行 |
| 流水线节点 | `workflow/nodes/` 加节点 + `graph.py` 连边 + `pipeline_steps.py` 补步骤 |

工程规范（枚举而非自由字符串、任务必须持久化、接口幂等、架构层收敛而非打补丁、前端只消费后端结论）见 [CLAUDE.md](CLAUDE.md)。

## 视频生成说明

- 单镜时长受各 provider API 限制；分镜总时长由后端按各镜求和，超集级目标会提示退回重排
- **角色一致性**：角色 → Look（服饰/发型）→ 参考图，逐镜带入生成请求
- **光影一致性**：分镜逐镜声明 `lighting` / `color_temp`（枚举，见 `workflow/constants.py`），
  同一 `scene_number` 内由后端统一到首镜 —— 交给模型每镜自由发挥会让同一场戏的光线跳变；
  prompt 层查表译成固定措辞写入，不让 LLM 每镜自行翻译
- **画面比例**是集级配置（短剧默认竖屏 9:16）；合法取值与默认值由 provider 声明下发，前端不自带清单
- **可复现**：平台回传的 `seed` 与 `revised_prompt` 落进产物，「重跑」带原 seed 重放 → 复现同一支视频；
  「改参数重生」不带 seed（要的就是不一样的结果）。模型是否支持见声明的 `supports_seed` ——
  不支持的（如 MiniMax H3 v2 无该字段）重跑只是「再抽一次」
- **负向提示**对无该字段的 provider（Seedance / MiniMax）折进 prompt 文本，不静默丢弃
- **产物树**：每支视频是自指树上的一个节点（`parent_id`）。剧集镜头当前只挂三个动作
  （`services/video_actions.py` 的 `ACTIONS` 注册表）：
  | 动作 | 参数 | 说明 |
  |------|------|------|
  | 相同 prompt 重跑（rerun） | 无 | 带原 seed 原样重放 → 复现同一支视频 |
  | 改参数重生（regenerate） | 分辨率 / 时长 / Prompt（均默认沿用父产物） | 不带 seed，结果必然不同 |
  | 升清 2K（upscale） | 无 | 仅模型声明支持、provider 已实现、且当前分辨率恰为 768P 时可见 |

  加一个新动作只需在该注册表加一条声明（谓词 + execute + 参数 schema），前端按 schema 自动渲染表单。
- **视频编辑 / 延长不是产物树动作**，是「直接生成」（散片）里的任务模式（`ClipTaskType.EDIT` /
  `EXTEND`），依赖至少一支参考视频，且要求该视频已同步到对象存储（拿到公网 URL）——
  故这两个模式只在「存储管理」配好一个存储 provider 后才可用，否则在前端呈禁用态并提示原因
- **失败分层**：单镜失败不拖垮整批（规范 6）；外部调用走 tenacity 退避（429/5xx/超时重试，创建类不重试以免重复建单）
