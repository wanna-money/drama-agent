# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AI 短剧制作平台。输入故事文本 → LangGraph 多 Agent 流水线自动完成:故事分析 → 剧本 → 分镜 → 视频 Prompt → 人工审核 → 视频生成 → 合成。后端 FastAPI + Python 3.12+,前端 React + TypeScript + Semi Design,包管理 uv / npm。

## Commands

```bash
# 依赖(首次或改依赖后)
uv sync --extra dev          # 后端 + 开发依赖(pytest/ruff/mypy),并 editable-install 本包
cd frontend && pnpm install  # 前端(pnpm,registry 走淘宝源见 frontend/.npmrc)

# 后端测试
uv run pytest -q                                   # 全量
uv run pytest tests/services/test_video_service.py -v   # 单文件
uv run pytest tests/services/test_video_service.py::test_provider_declarations -v  # 单测
uv run pytest -k "minimax and not regeneration" -v # 按表达式筛

# 后端 lint / 类型
uv run ruff check src tests
uv run mypy src

# 前端(必须先 cd frontend)
npx vitest run                         # 全量测试
npx vitest run src/test/X.test.tsx     # 单文件
npx tsc --noEmit                       # 类型检查
pnpm build                             # 生产构建

# 本地起服务
uv run uvicorn drama_agent.main:app --reload --port 8888   # 后端(单独)
cd frontend && pnpm dev                                    # 前端 :5173
bash start.sh                                              # 前后端一起
```

测试框架:pytest `asyncio_mode=auto`;异步测试仍沿用现有风格 `@pytest.mark.asyncio` + `unittest.mock`(AsyncMock/MagicMock/patch)。API 测试用 in-memory SQLite fixture(见 `tests/api/test_projects.py`:`create_async_engine(":memory:")` + `Base.metadata.create_all`,monkey-patch `db_session.AsyncSessionLocal` + override `get_db`)。ruff `line-length=100`。

## Architecture — 大局(需读多文件才能拼出)

**核心是一张 LangGraph StateGraph**(`workflow/graph.py`),Orchestrator 模式,每个节点是单职责 Agent(`workflow/nodes/*`):

```
START → story_analyzer → screenplay_writer → screenplay_review[interrupt]
  ├ approved → storyboard_director → prompt_engineer → prompts_review[interrupt]
  │              ├ approved → video_generator → video_assembler → END
  │              └ rejected → prompt_engineer(回环)
  └ rejected → screenplay_revision → screenplay_review(回环)
```

- 状态载体是 `DramaState`(`workflow/state.py`,TypedDict);节点返回 dict 增量合并。
- 人工介入用 LangGraph `interrupt()` 在两处暂停;前端 `resume` 用 `Command(resume=...)` 续跑。
- 运行入口:`api/workflow.py` 的 `_run_workflow` 在 FastAPI `BackgroundTasks` 里跑 `graph.astream`,逐节点广播 WebSocket 事件并回写 DB。
- 图与 checkpointer 是模块级单例(`graph.py:get_graph/init_graph`),用 SQLite checkpointer 持久化。

**⚠️ 当前状态存储分裂成三处**(改状态相关逻辑前必读,这是已知架构债):
1. `Project.status`(`db/models.py`,单列 String)—— 实际写入的是节点的 `current_stage` 自由字符串。
2. `current_stage`(DramaState 字段)—— 各节点自赋值(`story_analyzed`/`screenplay_written`/`prompts_ready`/`videos_generated`/…),**词表与 `ProjectStatus` 枚举对不上**。
3. LangGraph checkpointer —— 图状态机的真正权威。

`ProjectStatus` 枚举目前形同虚设(声明了但没被强制使用)。三者无事务一致性、无单一真相。**新代码不要再往这个分裂上叠加**;涉及状态时优先向"单一枚举 + 单一权威存储"收敛(见下方规范 1、4)。

**服务层**(`services/`):
- `video_service.py`:`VideoService.get_provider(name)` 工厂 → `Seedance/Bailian/MinimaxH3VideoService`,统一 `create_task/get_task/wait_for_task` → `VideoTaskResult`。每个 provider 声明 `provider_name` + `supported_actions`(能力的唯一真相)。
- `video_actions.py`:视频"产物动作"注册表 `ACTIONS`(rerun/regenerate/upscale)。**能力由谓词实时计算**(`available(artifact, provider)`),不预存能力态;`available_actions(artifact)` 返回可用动作 + 参数 schema。
- `artifact_service.py` + `VideoArtifact`(`db/models.py`):**产物树**(自指 `parent_id`,参考会话树)。视频生成/动作产出的每支视频是树上一个节点,沿 parent 追溯血统。`video_generator` 成功后**额外**写根产物(不改 LangGraph 拓扑)。注意:产物树目前独立于 `DramaState.videos` 与 `video_assembler`,两者尚未打通(已知非目标)。
- `llm_service.py`:统一 OpenAI 兼容接口;按模型名前缀路由到厂商 key/base_url,否则走 `DRAMA_*` fallback。
- `knowledge/`(知识层 · 声明式多后端,Provider 化):调用方只依赖 `KnowledgeStore` 协议 `retrieve(kind, key?, query?, k)`。`knowledge/registry.py` 的 `KnowledgeRegistry` 按 `kind` 路由到主后端 + 一个全局兜底后端(声明 `fallback=True`);降级(主后端命中空 / kind 未认领 / 主后端抛)统一在 `registry.retrieve` 一处,各后端只"检索或抛/返回空"、不自兜。后端类型注册表 `BACKEND_TYPES`(constant/markdown/dify;pgvector 占位)。**接已有类型的知识库 = config `knowledge_backends` 加一条声明(零代码);接新协议 = 写实现 `KnowledgeStore` 的类 + `BACKEND_TYPES` 登记一行 + 声明**(与 video/llm provider 同构;见规范 4)。默认未配 `knowledge_backends` 时由 `build_default_registry()` 从 `dify_*` settings 派生:craft kind(`CRAFT_KINDS`)→ 本地打包 markdown 全文,dify 配了 dataset 的 kind → dify,其余 → constant 兜底。⚠️ `registry.py` 顶层禁止运行时 import 后端类(用 `TYPE_CHECKING` + 三个工厂 `_make_*` 内惰性 import),否则与 `store.py` 模块级单例 `knowledge_store = _default_store()` 构成循环 import。

**扩展点**(加东西走这些,别另起炉灶):
- 加 LLM 模型:`config.py` 的 `llm_models` 追加条目。
- 加视频 provider:`video_service.py` 新增 `*VideoService`(声明 `provider_name`/`supported_actions`)并在 `get_provider` 注册;`config.py` 的 `video_models` 加条目(含 `resolutions`/`default_resolution`,驱动前端联动下拉)。
- 加视频动作:`video_actions.py` 的 `ACTIONS` 加一个 `Action`(谓词 + execute),参数走 `param_schema`(前端 `ActionParamForm` 按 schema 自动渲染,支持 enum/int/text/file/audio)。
- 配置:全部集中在 `config.py`(pydantic-settings,读 `.env`);MiniMax 文本用 `minimax_*`,H3 视频用独立的 `minimax_video_*`(域名 `api.minimaxi.com`,勿与旧版 `api.minimax.chat` 混淆)。

**任务运行时与状态**(重构后,分布式设计):
- 状态真相分两层:`Project.status` 存粗粒度**生命周期枚举** `LifecycleStatus`(created/queued/running/paused/completed/failed),细阶段以 LangGraph checkpointer 为准。`current_stage` 自由字符串已废弃。
- start/resume **不直接跑图**,而是 `job_service.enqueue` 入队一条 `Job`(幂等,靠 `UNIQUE(project_id,kind,dedup_key)`);后台 `JobWorker`(每实例一个,`main.py` lifespan 启)用 `dialect.claim_one_job`(PG `FOR UPDATE SKIP LOCKED` / SQLite 原子 UPDATE)领取,`runner.run_job` 跑图。心跳续租 + 启动 `reap_stale` 回收僵尸 → 崩溃可恢复、多实例分摊。
- 事件:节点状态变更经 `event_service.append_event` 写 `events` 表(与业务变更**同事务**),带每 project 自增 `seq`。
- 外部 HTTP 调用(llm/video)套 `services/retry.py` 的 tenacity 退避(429/529/5xx/超时重试;create 类不重试避免重复建单)。

**前端状态获取**:进详情页先 `workflowApi.status` 拉一次(读 DB 投影,不反序列化整个图),再开 WebSocket(`/ws/{project_id}?last_seq=N`)。连上先 `backfill_events` 补拉遗漏事件、再收增量;断线重连带最新 `last_seq` 不丢事件。完整图状态走独立 `GET .../workflow/state`。

**DB 无迁移工具**:靠 `db/session.py:init_db()` 的 `create_all` 建表。新增表/字段加到 `db/models.py` 即自动建(仅新库;已有库不会自动 ALTER)。生产 Postgres(`postgresql+asyncpg`)启用多实例;本地/测试 SQLite 降级路径,方言差异只在 `db/dialect.py`。给已有库加列须手动执行一次 ALTER,例如 `custom_providers.builtin`:
- SQLite:`ALTER TABLE custom_providers ADD COLUMN builtin BOOLEAN NOT NULL DEFAULT 0;`
- Postgres:`ALTER TABLE custom_providers ADD COLUMN builtin BOOLEAN NOT NULL DEFAULT false;`

## 工程规范(本仓库约定,写代码时遵守)

1. **状态类型一律用枚举,禁止自由字符串**。凡是"状态""阶段""动作类型""provider 名"这类有限取值,定义为 `enum`(或等价的受约束类型)并在读写两端都用它;不要散落魔法字符串。发现现有自由字符串状态(如 `current_stage`/`Project.status`)时,优先收敛到枚举而非跟着写字符串。
2. **任务流转必须持久化,保证进程重启不丢**。任何跨请求、长时运行、可中断的任务状态都要落库(或 checkpointer),且要能在重启后被恢复或标记终态——不要只靠进程内 `BackgroundTasks`/内存字典维持"运行中"。设计新任务时考虑:崩溃后这条记录能不能被捡回来?
3. **接口做幂等**。写接口(尤其触发任务、执行动作、resume 类)要能安全重试/重复调用而不产生重复副作用或未定义行为。带状态守卫(参考 `start_workflow` 的 `if status != "created"`),`resume`/动作执行同理需校验前置状态。
4. **从架构层面解决问题,不打补丁**。遇到设计缺陷(如状态三处分裂),优先做结构性收敛;能在架构层根治的,不要用局部 if/特判/兜底掩盖症状。
   - **同一功能的多来源/多后端数据,必须在架构层磨平差异,严禁在分发处写 if/else 区分来源**。凡"一个能力有多个提供方"的场景(视频/LLM/图像 provider、知识库检索源、存储后端、动作提供方……):① 定义**统一接口**(Protocol / 抽象基类),调用方只依赖接口、对具体来源零感知;② 用**声明式注册表**收拢所有来源(`{id/type/config, 负责的 key}` 声明 → 启动期合成 → 按 key 路由),接入一个新来源 = **config 里加一条声明**(已有类型零代码;全新协议再写一个实现类 + 注册表登记一行);③ 选哪个来源、来源间的降级/兜底,都由**注册表/编排层**统一决定,不散落到各调用点或某个 `_default_xxx()` 的 `if base_url: A else B`。范例:`provider/registry.py`(video/llm/image 三层合成 + 三跳解析)、`knowledge/registry.py`(多知识后端按 kind 路由 + 全局兜底)。**发现某处用 `if 来源A: … elif 来源B: …` 分发同一功能,就是该收敛成注册表的信号**——见规范 5。
   - **同一功能/业务规则的判断,收口到后端唯一权威,前端只消费、不自算**。凡"一条规则被前后端各实现一遍"的场景(默认值选取、可用性/能力判定、状态流转、权限/可见性、校验口径……):把规则做成后端的单一函数/接口作为唯一真相,经 API 把**结果**(而非重算所需的原料)下发给前端,前端直接用;严禁前端照抄一份同样的 if/择优逻辑与后端"手动保持一致"——两份实现迟早分叉。范例:模型默认选取——后端 `provider/registry.py:effective_default(kind)`(is_default 优先、否则首个可用)为唯一真相,`/config/*-models` 回传 `default` 字段,前端各页直接读 `default`(已删除前端自算的 `pickDefault`)。**发现前端在重算一条后端也算的规则(尤其"择优/挑默认/判能不能"),就是该把规则收口后端、前端只取结果的信号。**
5. **一切设计考虑扩展性**。新增能力走既有扩展点(provider 工厂、动作注册表、config 列表、schema 驱动表单);加一个新 provider/动作/模型应当是"加一条声明",而非改多处硬编码分支。
6. **异常处理讲粒度,符合语义**。想清楚 catch 的范围:单元素失败(如单个分镜)与整批失败要能区分,不要一个顶层 `try/except` 把整个流程标 failed;非关键旁路(如产物树写入)失败不应阻断主流程,但要有意识地选择吞掉还是上报,而不是无脑 `except: pass`。
7. **复用已有工具,不重复造轮子**。判空、参数校验、HTTP 调用、DB 会话、provider 解析等已有封装的,直接用;写新工具函数前先找现有的。
8. **前端一律用 Semi 原生,不写任何自定义样式**。前端是 Semi Design(`@douyinfe/semi-ui`)。结构、布局、排版、间距全部用 Semi 组件承载:布局/间距用 `Layout`/`Space`(`vertical`/`spacing`/`align`/`wrap`)/`Row`/`Col`,排版用 `Typography`(`Title heading=N`/`Text`/`Paragraph` + `type`/`size` prop),容器用 `Card`,列表用 `List`,表单用 `Form`(`Form.Input`/`Form.Select`/… + `rules` 校验,别手写 label+错误提示),键值展示用 `Descriptions`,空/错误态用 `Empty`,导航用 `Nav`,分页/表格用 `Table` 自带,弹窗用 `Modal`(原生 `footer`/`onOk`/`okText`)。
   - **不写内联 `style={{...}}`——包括纯布局的**(flex/gap/width/margin/maxWidth/grid/padding)。要间距/方向/对齐,用 `Space` 的 prop,不用 style。也不写 `bodyStyle`、`className`、自定义 class、组件尺寸/外观干预(如 Button `size`/`minWidth`、Card `bodyStyle`、`fontSize`/`letterSpacing`)。让 Semi 用默认。
   - **不写颜色**:语义色用组件的 `type` prop(`Text type="tertiary/danger"`、`Button type="danger"`、`Tag color=…`),不在 style 里写颜色(含 `var(--semi-color-*)` 也不写进 style)。
   - **`index.css` 只保留最小 reset**(`box-sizing` + `body{margin:0}`),页面底色交给 Semi `Layout` 默认;不放任何组件级样式、不做 `.semi-*` 全局覆盖、不定义自定义 class、不定义颜色/主题变量。历史上的自定义 class(`glass-card`/`page-title-*`/`review-bar`/`--app-bg` 等)已全部废弃——发现残留删掉,不要跟着扩写。
   - 只有 Semi 确实无对应组件的场景(如自绘视频播放器 `<video>`、代码/剧本块 `<pre>`)才用最小 `<div>`/`<pre>`,且其上也不写自定义颜色/尺寸 style,交给浏览器/Semi 默认。
   - **尽可能组件化,公共功能抽成公共组件,优先复用已有组件**。页面/功能里重复出现的结构(页面外壳、页头、空/加载/错误态、列表项、卡片布局、表单片段……)抽到 `frontend/src/components/` 复用,不在各页各写一遍。写新页/新功能前先翻 `components/` 有没有可复用的;有就用、不够就扩它,而不是另起一套。已有的公共组件:`components/PageShell.tsx`——`PageShell`(全宽页面外壳 + 统一页头 `title`/`description`/`headerExtra`)、`PageEmpty`(带插画的居中空/错误态,`variant="empty"|"error"`)、`PageLoading`(居中加载)。**所有列表/详情页的顶层容器统一用 `PageShell`**(详情页自带标题行时不传 `title`,只借外层容器统一全宽/间距);空/加载/错误态统一用 `PageEmpty`/`PageLoading`,不再各页手写 `div+flex` 或裸 `Empty`/`Spin`。公共组件本身也严格遵守本规范(全 Semi 原生、零内联 style)。
   - Semi 组件 API **一律以官方站 https://semi.design/zh-CN 为准**(对应组件页如 Modal→`/show/modal`、Table→`/show/table`、Space→`/spacing/space`、Form→`/input/form`),不确定的先查官方文档再用,别猜 prop。**不要依赖 context7 返回的 Semi 文档**(可能过时/不准)。

## 单测规范(本仓库约定)

**判据:一个测试若删掉,某类真实 bug 会不会就此无人拦截?** 答不上来就不该写。

- **禁止同义反复**。不要断言"字面量等于我刚写的字面量":枚举值 == 定义、`dataclass/__init__` 属性 == 传入值、纯 getter 回读 —— 这些测的是定义或语言/框架本身,拦不住任何逻辑 bug,不要写。
- **禁止测第三方库**。SQLAlchemy 能存能取、pydantic 能校验、tenacity 会重试 —— 这些是库的保证。要测就测**我们对它的配置/用法**(如"我们的重试条件是 429/5xx 而非 4xx"、"我们的唯一约束真的建在这三列上")。
- **测真实行为与边界**:幂等(重复调用不产生重复副作用)、原子领取、超时回收、游标过滤、状态守卫(非法前置 → 409)、异常分层(单元素失败不拖垮整体)、错误映射。这些删了就放走回归,必须有。
- **重构类改动**:抽函数/改内部实现时,对外行为不变的证明 = 现有测试继续通过。新增的测试只覆盖新暴露的接口(如 `build_prompt` 纯函数验证 prompt 含必要字段),不重复测已被覆盖的行为。

**技术约定:**
- 框架 `pytest` + `asyncio_mode=auto`;异步测试沿用 `@pytest.mark.asyncio` + `unittest.mock`(AsyncMock/MagicMock/patch)。
- DB 测试用 SQLite 内存库 fixture:`create_async_engine("sqlite+aiosqlite:///:memory:")` + `Base.metadata.create_all`;API 测试再 monkey-patch `db_session.engine`/`AsyncSessionLocal` 并 override `get_db`(见 `tests/api/test_projects.py`)。
- **模块内引用 `AsyncSessionLocal` 必须动态查**:业务模块写 `from drama_agent.db import session as db_session` 后用 `db_session.AsyncSessionLocal()`,**不要** `from ...session import AsyncSessionLocal`(import 时就绑定,测试 patch 不生效,且违背可重绑定)。
- **禁止真调外部服务**:LLM / 视频 API / 真实网络一律 mock。会真跑 LangGraph 图的路径(`get_graph().astream`)在单测里必须 mock 掉 `astream`/`aget_state`,否则会真调 LLM 并卡住;跑测试若卡死,先查是不是漏 mock 或有残留 pytest 进程占着 checkpointer 的 sqlite 锁(`pkill -9 -f pytest` 后重跑)。
- **评测 ≠ 单测**:`src/drama_agent/evals/`(节点质量评测)不进 pytest 默认收集,经 `python -m drama_agent.evals.harness <node>` 独立跑;evals 的编排逻辑可用 mock-LLM 写单测,但"LLM 真实输出质量"不写成 pytest 断言。

## 提交约定

commit 信息用 `feat(scope):` / `fix(scope):` 前缀 + 简短描述。仅在用户明确要求时才提交。
