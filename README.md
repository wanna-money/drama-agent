# Drama Agent — AI 短剧制作平台

基于 LangGraph 多 Agent 模式的全自动短剧制作平台。输入故事文本，自动完成故事分析 → 剧本创作 → 分镜处理 → 视频 Prompt 生成 → 人工审核 → 视频生成 → 视频合成的完整流程。

## 架构概览

```
用户输入故事
      │
      ▼
┌─────────────────────────────────────────────────────┐
│              LangGraph StateGraph                    │
│                                                     │
│  story_analyzer → screenplay_writer                 │
│       → [interrupt: 人工审核剧本]                    │
│       → storyboard_director → prompt_engineer       │
│       → [interrupt: 人工审核/编辑 Prompt]            │
│       → video_generator → video_assembler           │
└─────────────────────────────────────────────────────┘
      │
      ▼
  最终视频 (分段 + 合成)
```

- **Harness 模式**：StateGraph 作为 Orchestrator，每个节点为单职责 Skill Agent
- **人工介入**：LangGraph `interrupt()` 在剧本和 Prompt 两个阶段暂停等待审核
- **视频连贯性**：帧链接（Frame Chaining）— 每个镜头的末帧作为下一镜头的首帧参考
- **RAG 增强**：ChromaDB 存储 Prompt 模板、摄影规则、角色外貌，用于生成一致性 Prompt
- **多模型支持**：Seedance 2.0（火山引擎）、万相 2.7（阿里 DashScope）

## 技术栈

| 层次 | 技术 |
|------|------|
| 后端框架 | FastAPI + Python 3.13 |
| 工作流引擎 | LangGraph (StateGraph + interrupt) |
| 文本模型 | 统一 OpenAI 兼容接口，支持 DeepSeek / Kimi / GLM / MiniMax |
| 视频模型 | Seedance 2.0 / 万相 2.7 |
| 知识库 | ChromaDB (RAG) |
| 数据库 | SQLite + SQLAlchemy 2.0 async |
| 前端 | React + TypeScript + Semi Design |
| 包管理 | uv |

## 快速开始

### 1. 安装依赖

```bash
# 后端
uv sync

# 前端
cd frontend && pnpm install
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入必要的 API Key：

```env
# 统一 LLM 接入端点（必填）
DRAMA_BASE_URL=https://your-llm-endpoint/v1
DRAMA_API_KEY=sk-xxx
DRAMA_TEXT_MODEL=deepseek-v3   # 默认使用的模型名

# 若需要直连各厂商，可单独配置（可选）
KIMI_API_KEY=sk-xxx
GLM_API_KEY=xxx
MINIMAX_API_KEY=xxx

# 视频模型（至少配置一个）

# Seedance 2.0（火山引擎）
ARK_API_KEY=xxx
SEEDANCE_ENDPOINT_ID=ep-xxx

# 万相 2.7（阿里 DashScope）
DASHSCOPE_API_KEY=sk-xxx
```

### 3. 启动服务

```bash
# 方式一：使用启动脚本（同时启动前后端）
bash start.sh

# 方式二：分别启动
# 后端
uv run uvicorn drama_agent.main:app --reload --port 8888

# 前端（开发模式）
cd frontend && pnpm dev
```

访问 http://localhost:5173

### 4. 生产构建

```bash
cd frontend && pnpm build
# 静态文件输出到 frontend/dist/，可由 Nginx/FastAPI 静态托管
```

## 使用流程

1. **新建项目**：输入故事标题、原始文本，选择 LLM 和视频生成模型
2. **开始制作**：点击「开始制作」，系统自动进行故事分析 → 剧本创作
3. **审核剧本**：AI 生成剧本后暂停，人工确认或提交修改意见
4. **确认 Prompt**：分镜 + Prompt 生成完成后暂停，可逐镜头编辑 Prompt
5. **生成视频**：确认后自动调用视频 API 生成各分镜视频
6. **下载成片**：所有分镜视频合成为完整短剧，支持在线预览和下载

## 项目结构

```
drama-agent/
├── src/drama_agent/
│   ├── api/              # FastAPI 路由（projects, workflow, files, websocket）
│   ├── db/               # SQLAlchemy 模型与会话
│   ├── services/         # LLM, RAG(ChromaDB), Video, Storage
│   └── workflow/
│       ├── graph.py      # LangGraph StateGraph 定义
│       ├── state.py      # DramaState TypedDict
│       └── nodes/        # 各 Skill Agent 节点
│           ├── story_analyzer.py
│           ├── screenplay_writer.py
│           ├── storyboard_director.py
│           ├── prompt_engineer.py
│           ├── video_generator.py
│           └── video_assembler.py
├── frontend/             # React + Semi Design UI
├── tests/                # pytest 测试套件
├── data/                 # 运行时数据（gitignore）
├── pyproject.toml        # uv 项目配置
└── start.sh              # 一键启动脚本
```

## 运行测试

```bash
# 后端
uv run pytest tests/ -v

# 前端
cd frontend && pnpm test
```

## 支持的 LLM 模型

通过统一 drama 端点路由，UI 中可选模型：

| 模型 ID | 显示名 | 厂商 |
|---------|--------|------|
| deepseek-v3 | DeepSeek V3 | DeepSeek |
| deepseek-r1 | DeepSeek R1 | DeepSeek |
| kimi-k2-0711-preview | Kimi K2 | Kimi |
| glm-4-plus-0111 | GLM 4 Plus | GLM |
| MiniMax-Text-01 | MiniMax Text-01 | MiniMax |

直连厂商：Kimi / GLM / MiniMax 走对应 `xxx_API_KEY` + `xxx_BASE_URL`；其余模型走 `DRAMA_*` 端点 fallback。

如需新增模型，在 `config.py` 的 `llm_models` 列表追加条目即可。

## 支持的视频模型

| 提供商 | 模型 | 配置 Key |
|--------|------|---------|
| 火山引擎 Seedance | Seedance 2.0 | `ARK_API_KEY` + `SEEDANCE_ENDPOINT_ID` |
| 阿里百炼万象 | 万相 2.7 | `DASHSCOPE_API_KEY` |

新增模型：在 `src/drama_agent/services/video_service.py` 中继承 `BaseVideoService` 并注册到工厂即可。

## 视频生成说明

- 每个镜头最长 15 秒（由 Seedance / 万相 API 限制）
- 帧链接：前一镜头末帧自动作为下一镜头首帧，保持场景连贯
- 角色一致性：RAG 存储角色外貌描述，每次生成都附加参考图像
- 失败重试：视频 Generator 跳过已成功的镜头，支持断点续传
