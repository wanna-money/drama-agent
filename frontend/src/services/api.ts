import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface Project {
  id: string
  title: string
  genre: string
  visual_style: string
  status: string            // 聚合派生态:empty/running/paused/completed/partial_failed
  episodes?: Episode[]
  cost_total?: number       // 估算花费(人民币)
  cost_unpriced?: boolean   // 存在未定价用量,金额不可信
  created_at: string
  updated_at: string
}

export interface Episode {
  id: string
  project_id: string
  episode_number: number
  title: string
  /** 本集拍的那段原文 —— 集的锚点。原文/分析/阵容都经它取。 */
  story_id?: string | null
  /** 起始剧本方案(从故事开跑时为空)。**只作溯源** —— 本集实际用的正文在
   *  screenplay_versions(建集时快照进版本 0),改源剧本不影响在制作中的集。 */
  script_id?: string | null
  /** 集级目标时长(秒),驱动剧本篇幅与分镜总时长 */
  target_seconds?: number
  /** 画面比例(短剧多为竖屏 9:16) */
  aspect_ratio?: string
  status: string
  llm_model: string
  video_provider: string
  video_model: string
  resolution: string
  state_snapshot?: Record<string, any>
  error_message?: string
  cost_total?: number
  cost_unpriced?: boolean
  created_at?: string
  updated_at?: string
}

export interface CreateProjectData {
  title: string
  genre?: string
  visual_style: string
  source_text?: string                    // 小说正文(小说模式)
  target_episodes?: number                // 切分依据二选一
  target_seconds_per_episode?: number
}

export interface CreateEpisodeData {
  title: string
  /** 二选一表达"拍什么":
   *  · story_id  → 拍这段原文(从故事开跑,剧本由流水线产出)
   *  · script_id → 拍这个改编方案(原文由方案的 story_id 在后端解析) */
  story_id?: string
  script_id?: string
  target_seconds?: number   // 集级目标时长(秒)
  aspect_ratio?: string     // 画面比例;选项来自后端下发的 aspect_ratios
  llm_model?: string
  video_provider?: string
  video_model?: string
  resolution?: string
  episode_number?: number
  use_keyframes?: boolean
  keyframe_image_model?: string
}

/** 开拍前可改的字段(只传要改的那些)。正文改剧本(PATCH /scripts/{id}),不在集上。 */
export interface UpdateEpisodeData {
  title?: string
  target_seconds?: number
}

export interface WorkflowStatus {
  /** 事件水位:作 WebSocket 的 last_seq 起点。从 0 起会把全部历史事件当增量补拉,
   *  早已修掉的旧 error 会被重新弹成 toast。 */
  last_seq?: number
  episode_id: string
  project_id: string
  db_status: string
  current_stage: string
  paused_at?: string | null
  /** 投影说暂停、图里已无状态 —— 该集无法继续,只能重置重跑。后端判定,前端只提示。 */
  state_lost?: boolean
  screenplay?: string
  shots?: Shot[]
  total_duration_seconds?: number   // 真实成片时长(各镜头之和),后端算好下发,前端不自算
  prompts?: Prompt[]
  videos?: Video[]
  assembled_video_path?: string
  story_analysis?: StoryAnalysis
  look_assignments?: Record<string, Record<string, string>>
  /** 本集阵容:角色名 → Character.id(cast_review 确认后写入) */
  cast?: Record<string, string>
  /** 待确认身份的剧本人物;非空即表示停在"确认角色"步 */
  cast_pending?: CastPending[]
  screenplay_versions?: ScreenplayVersion[]     // 剧本版本树(后端 Episode 列下发,审核面板据此渲染)
  screenplay_version_current?: number
  duration_over_target?: boolean    // 分镜压到每镜下限仍超集级目标 → 提示退回重做(后端唯一真相)
  pipeline?: { steps: { key: string; label: string; cost?: number }[]; current: string | null }
  cost_total?: number
  cost_unpriced?: boolean
  cost_tokens_total?: number
  cost_by_kind?: Record<string, number>
  error_message?: string
}

export interface Shot {
  shot_id: string
  scene_number: number
  shot_number: number
  shot_type: string
  camera_movement: string
  /** 光照方案与色温:分镜逐镜声明,同场景内一致(后端收敛) */
  lighting?: string
  color_temp?: string
  duration_seconds: number
  description: string
  characters: string[]
  dialogue: string
  action: string
  location: string
}

export interface Prompt {
  shot_id: string
  prompt_text: string
  negative_prompt: string
  reference_image_url?: string
  reference_role?: string
  approved: boolean
  edited_prompt?: string
  edited_negative_prompt?: string
  keyframe_url?: string | null
}

export interface Video {
  shot_id: string
  task_id: string
  status: string
  video_url?: string
  last_frame_url?: string
  local_path?: string
  error?: string
}

export interface StoryAnalysis {
  title: string
  genre: string
  setting: string
  themes: string[]
  characters: Array<{ name: string; appearance: string; personality: string }>
  plot_summary: string
  tone: string
}

export interface ResumeData {
  approved: boolean
  notes?: string
  edited_prompts?: Record<string, string>
  edited_negative_prompts?: Record<string, string>
  assignments?: Record<string, Record<string, string>>
  regenerate_shot_ids?: string[]
  /** cast_review:角色名 → {action: 'link'|'create', character_id?} */
  cast?: Record<string, { action: string; character_id?: string }>
}

export interface LLMModelOption {
  value: string
  label: string
  provider: string
  is_default?: boolean
  /** 该模型所属 provider 是否已配凭证(后端唯一权威,不下发 key 本身)。
   *  未配时前端应禁用该选项,而非等调用失败才发现。 */
  credential_configured?: boolean
}

export interface VideoModelOption {
  value: string
  label: string
  /** provider 的**展示名**(如「字节跳动」),只用于分组标题 —— 不是协议名 */
  provider: string
  /** 协议名:开拍时要传给后端的 video_provider(video_service.get_provider 认它) */
  provider_id?: string
  /** 该 provider 下的模型 id:开拍时传给 video_model */
  model_id?: string
  resolutions?: string[]
  default_resolution?: string
  /** 合法画面比例与默认值(后端下发,前端不自带写死的列表) */
  aspect_ratios?: string[]
  default_aspect_ratio?: string
  /** 该模型能否复现同一支视频;false 时「重跑」只是再抽一次 */
  supports_seed?: boolean
  is_default?: boolean
  /** 参考图上限(后端 Model 声明下发);前端据此拦住超限提交,不自算 */
  max_reference_images?: number
  /** 单支时长的合法**闭区间**(秒,直接生成模式用);前端不自带写死的清单。
   *  是区间而非档位 —— 平台按区间收(Seedance 2.5 是 4-30,2.0 与 H3 是 4-15) */
  min_duration?: number
  max_duration?: number
  max_reference_audios?: number
  supports_audio_reference?: boolean
  /** 参考视频上限。0 表示该模型没有视频参考 → 界面不渲染编辑/延长模式 */
  max_reference_videos?: number
  /** 是否支持 omni_reference_task_type(参考生成/编辑/延长三态);
   *  false 的模型只有参考生成一种任务,不是禁用了另外两种。 */
  supports_omni_task_type?: boolean
  /** 画面比例是否被平台强制收敛为自适应(不接受用户指定比例)。
   *  edit/extend 任务与部分模型即便在参考生成模式下也可能要求它。 */
  forces_adaptive_ratio?: boolean
  /** 该模型所属 provider 是否已配凭证(后端唯一权威,不下发 key 本身)。
   *  未配时选中会以空 key 发请求,报一条与"没配 key"无关的 "Connection error.",
   *  且要等整条流水线跑完才看到 —— 前端据此禁用该选项。 */
  credential_configured?: boolean
}

export interface ImageModelOption {
  value: string
  label: string
  provider: string
  resolutions?: string[]
  default_resolution?: string
  is_default?: boolean
  /** 该模型所属 provider 是否已配凭证(后端唯一权威,不下发 key 本身)。 */
  credential_configured?: boolean
}

export interface VideoArtifact {
  id: string
  project_id: string
  shot_id: string
  parent_id: string | null
  provider: string
  model: string
  resolution: string
  duration: number
  action: string
  task_id: string
  video_url?: string | null
  local_path?: string | null
  prompt_text?: string | null
  created_at: string
}

export interface ParamField {
  name: string
  type: 'enum' | 'int' | 'text' | 'file' | 'audio'
  label: string
  options?: string[]
  default?: string | number
  min?: number
  max?: number
}

export interface ActionOption {
  id: string
  label: string
  param_schema: ParamField[]
}

export type AssetCategory = 'character' | 'background' | 'prop' | 'costume'

export interface Asset {
  id: string
  category: AssetCategory
  name: string
  description?: string | null
  url: string
  mime?: string | null
  size_bytes: number
  created_at?: string
}

export const assetsApi = {
  list: (category?: AssetCategory) =>
    api.get<Asset[]>('/assets', { params: { category } }).then(r => r.data),
  create: (form: FormData) =>
    api.post<Asset>('/assets', form, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data),
  update: (id: string, form: FormData) =>
    api.put<Asset>(`/assets/${id}`, form, { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data),
  delete: (id: string) => api.delete(`/assets/${id}`).then(r => r.data),
  generate: (body: { model_id: string; prompt: string; size?: string; n?: number; project_id?: string }) =>
    api.post<{ images: string[] }>('/assets/generate', body).then(r => r.data),
  edit: (body: { asset_id: string; model_id: string; prompt: string; size?: string; n?: number }) =>
    api.post<{ images: string[] }>('/assets/edit', body).then(r => r.data),
  saveGenerated: (body: { category: AssetCategory; name: string; description?: string; image_b64: string }) =>
    api.post<Asset>('/assets/from-generated', body).then(r => r.data),
}

/** 可改写的文本类型。取值权威在后端 text_revise_service.TextKind。 */
export type TextKind = 'story' | 'screenplay'

/** 改写 agent 的一轮决策。ask 只回复;apply 带完整改写结果(由前端预览后落库)。 */
export interface ReviseTurn {
  action: 'ask' | 'apply'
  reply: string
  text: string | null
  summary: string | null
}

/** 一份已解析的对话附件。图片带 data_url(多模态给模型看),文档带 text(已抽好的正文);
 *  两者不会同时非空 —— 分流的权威在后端 attachment_service。 */
export interface ParsedAttachment {
  filename: string
  text: string | null
  data_url: string | null
}

export const storyTextApi = {
  /** 对话式改写原文/剧本(不落库)。落库仍走 scriptsApi.update / projectsApi.update ——
   *  结果要先给用户预览,确认后才覆盖他手写的内容。
   *  与剧集页的剧本审核用同一个 agent,差别只在落库出口(那边有版本树)。 */
  revise: (body: {
    kind: TextKind; text: string
    messages: { role: string; content: string }[]
    attachments?: ParsedAttachment[]
    model?: string
  }) => api.post<ReviseTurn>('/story-text/revise', body).then(r => r.data),
  /** 解析一份附件:图片回 data_url,文档回抽好的 text。解析结果可在多轮对话里复用,
   *  不必每轮重传原文件(附件不落盘,故也没有生命周期要管)。 */
  parseAttachment: (file: File) => {
    const form = new FormData(); form.append('file', file)
    return api.post<ParsedAttachment>('/story-text/attachments', form,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
}

export const promptApi = {
  optimize: (body: { raw_prompt: string; kind?: string; target_model?: string; subject?: string }) =>
    api.post<{ optimized: string }>('/prompt/optimize', body).then(r => r.data),
  /** 从作品内容提炼 prompt(用户没写描述时)。原料由后端按 episode_id/project_id 自取,
   *  前端不搬运剧本正文与分镜(规范 4)。subject 仅支持 character / background。 */
  extract: (body: {
    subject: 'character' | 'background'; key: string
    episode_id?: string; project_id?: string; model?: string
  }) => api.post<{ prompt: string }>('/prompt/extract', body).then(r => r.data),
}

export interface Look {
  id: string; character_id: string; name: string; is_default: boolean
  front_key?: string | null; side_key?: string | null; back_key?: string | null; face_key?: string | null
}
export interface Character {
  id: string
  project_id: string
  name: string
  /** 人手写的备注(可空) */
  description?: string | null
  /** AI 从剧本抽出的外貌 —— 展示与「生成形象」的提示词都以它为主 */
  appearance?: string | null
  voice_key?: string | null
}
export type CharacterViewName = 'front' | 'side' | 'back' | 'face'

export const charactersApi = {
  list: (pid: string) => api.get<Character[]>(`/projects/${pid}/characters`).then(r => r.data),
  create: (pid: string, body: { name: string; description?: string }) =>
    api.post<Character>(`/projects/${pid}/characters`, body).then(r => r.data),
  update: (pid: string, cid: string, body: { name?: string; description?: string }) =>
    api.put<Character>(`/projects/${pid}/characters/${cid}`, body).then(r => r.data),
  remove: (pid: string, cid: string) => api.delete(`/projects/${pid}/characters/${cid}`).then(r => r.data),
  listLooks: (pid: string, cid: string) =>
    api.get<Look[]>(`/projects/${pid}/characters/${cid}/looks`).then(r => r.data),
  createLook: (pid: string, cid: string, body: { name: string; is_default?: boolean }) =>
    api.post<Look>(`/projects/${pid}/characters/${cid}/looks`, body).then(r => r.data),
  updateLook: (pid: string, cid: string, lid: string, body: { name?: string; is_default?: boolean }) =>
    api.put<Look>(`/projects/${pid}/characters/${cid}/looks/${lid}`, body).then(r => r.data),
  removeLook: (pid: string, cid: string, lid: string) =>
    api.delete(`/projects/${pid}/characters/${cid}/looks/${lid}`).then(r => r.data),
  uploadView: (pid: string, cid: string, lid: string, view: CharacterViewName, file: File) => {
    const form = new FormData(); form.append('file', file)
    return api.post<Look>(`/projects/${pid}/characters/${cid}/looks/${lid}/views/${view}`, form,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  // views 为 null = 后端自动裁切失败(生成本身成功),前端拿 sheet_b64 转人工裁切
  // prompt 直给时后端不再拼模板(用户改过的措辞原样进模型)
  generateSheet: (pid: string, cid: string, lid: string,
    body: { model_id: string; character_desc?: string; look_desc?: string; prompt?: string }) =>
    api.post<{ sheet_b64: string; views: Record<CharacterViewName, string> | null }>(
      `/projects/${pid}/characters/${cid}/looks/${lid}/generate-sheet`, body).then(r => r.data),
  saveGeneratedViews: (pid: string, cid: string, lid: string,
    body: { front_b64: string; side_b64?: string; back_b64?: string; face_b64?: string }) =>
    api.post<Look>(`/projects/${pid}/characters/${cid}/looks/${lid}/views-from-generated`, body).then(r => r.data),
  /** 把一张四视图 sheet 切开填入 Look。views 为 null = 切不开(生成本身成功),
   *  前端据此引导人工裁切,不把图丢掉。 */
  cropSheetToViews: (pid: string, cid: string, lid: string, body: { sheet_b64: string }) =>
    api.post<{ views: Look | null; detail?: string }>(
      `/projects/${pid}/characters/${cid}/looks/${lid}/crop-sheet`, body).then(r => r.data),
  importFromAsset: (pid: string, cid: string, lid: string, assetId: string) =>
    api.post<Look>(`/projects/${pid}/characters/${cid}/looks/${lid}/import-from-asset`,
      { asset_id: assetId }).then(r => r.data),
  uploadVoice: (pid: string, cid: string, file: File) => {
    const form = new FormData(); form.append('file', file)
    return api.post<Character>(`/projects/${pid}/characters/${cid}/voice`, form,
      { headers: { 'Content-Type': 'multipart/form-data' } }).then(r => r.data)
  },
  deleteVoice: (pid: string, cid: string) =>
    api.delete<Character>(`/projects/${pid}/characters/${cid}/voice`).then(r => r.data),
}

export const configApi = {
  listModels: () =>
    api.get<{ models: LLMModelOption[]; default: string | null }>('/config/models').then(r => r.data),
  listVideoModels: () =>
    api.get<{ models: VideoModelOption[]; default: string | null }>('/config/video-models').then(r => r.data),
  listImageModels: () =>
    api.get<{ models: ImageModelOption[]; default: string | null }>('/config/image-models').then(r => r.data),
  /** 公网存储是否可用。**结论来自后端**(规范 4)—— 前端不去猜"配了没有"。 */
  storageStatus: () => api.get<{ available: boolean }>('/config/storage').then(r => r.data),
}

export const projectsApi = {
  list: () => api.get<Project[]>('/projects').then(r => r.data),
  get: (id: string) => api.get<Project>(`/projects/${id}`).then(r => r.data),
  create: (data: CreateProjectData) => api.post<Project>('/projects', data).then(r => r.data),
  /** 改作品。小说正文只在改编开跑前可改(开跑后后端回 409)。 */
  update: (id: string, body: { title?: string; source_text?: string; visual_style?: string }) =>
    api.patch<{
      id: string; title: string; source_text: string; visual_style: string
      adaptation_status: string
    }>(`/projects/${id}`, body).then(r => r.data),
  delete: (id: string) => api.delete(`/projects/${id}`).then(r => r.data),
}

/** 切分产出直接进剧本库,没有"草稿待确认"这个中间态。 */
export type AdaptationStatus =
  | 'none' | 'analyzing' | 'cast_review' | 'adapting' | 'done' | 'failed'

export interface AdaptationState {
  adaptation_status: AdaptationStatus
  source_text: string
  target_episodes?: number | null
  target_seconds_per_episode?: number | null
  /** 切分产出的剧本(内容的实际去处) */
  scripts: Script[]
  /** 非空即表示停在角色确认卡点(切分前的唯一卡点) */
  cast_pending?: CastPending[]
}

/** 作品级「小说改编 → 分集切分」。状态与守卫的唯一权威在后端,前端只消费。 */
export const adaptationApi = {
  start: (projectId: string) =>
    api.post<{ job_id: string; adaptation_status: AdaptationStatus }>(
      `/projects/${projectId}/adapt`).then(r => r.data),
  get: (projectId: string) =>
    api.get<AdaptationState>(`/projects/${projectId}/adaptation`).then(r => r.data),
  /** 确认整本小说的角色身份,随后自动继续切分。 */
  confirmCast: (projectId: string, cast: Record<string, { action: string; character_id?: string }>) =>
    api.post<{ adaptation_status: AdaptationStatus; cast: Record<string, string>; job_id: string }>(
      `/projects/${projectId}/adaptation/confirm-cast`, { cast }).then(r => r.data),
  commit: (projectId: string, body: {
    llm_model?: string; video_provider?: string; video_model?: string
    resolution?: string; use_keyframes?: boolean
  } = {}) =>
    api.post<{ episodes: Episode[]; adaptation_status: AdaptationStatus }>(
      `/projects/${projectId}/adaptation/commit`, body).then(r => r.data),
}

export const episodesApi = {
  list: (projectId: string) =>
    api.get<Episode[]>(`/projects/${projectId}/episodes`).then(r => r.data),
  get: (projectId: string, episodeId: string) =>
    api.get<Episode>(`/projects/${projectId}/episodes/${episodeId}`).then(r => r.data),
  create: (projectId: string, data: CreateEpisodeData) =>
    api.post<Episode>(`/projects/${projectId}/episodes`, data).then(r => r.data),
  /** 开拍前修改本集(标题/故事内容/目标时长)。已开拍时后端返回 409。 */
  update: (projectId: string, episodeId: string, data: UpdateEpisodeData) =>
    api.patch<Episode>(`/projects/${projectId}/episodes/${episodeId}`, data).then(r => r.data),
  delete: (projectId: string, episodeId: string) =>
    api.delete(`/projects/${projectId}/episodes/${episodeId}`).then(r => r.data),
}

/** 故事原文 —— 内容的源头。与 Script 是 1:N(同一段原文可有多个改编方案)。
 *
 * 正文 / story_analysis / cast 的权威在这里,不在 Script 上。切分产出子 Story
 * (parent_id 自指),改编产出 Script(story_id)—— 两种关系各走一条边。 */
export interface Story {
  id: string
  project_id?: string | null
  parent_id?: string | null      // 切分来源(null = 顶层原文)
  order_index?: number           // 在父原文里的次序(第几段)
  title: string
  genre: string
  content?: string | null        // 原文正文
  story_analysis?: StoryAnalysis | null
  /** 角色名 → Character.id。原文只存名单,形象在角色的造型(Look)里。 */
  cast?: Record<string, string>
  project_title?: string | null  // 所属作品名(后端一次查好;散稿为 null)
  script_count?: number          // 已有几个改编方案
  segment_count?: number         // 已切出几段(子 Story)
  created_at?: string
}

export interface Script {
  id: string
  project_id?: string | null
  /** 改编自哪段原文。剧本总是某段原文的方案,没有孤立的剧本。 */
  story_id?: string | null
  title: string
  genre: string
  content?: string | null        // 成稿剧本正文(本表唯一持有的内容)
  /** ↓ 原文侧字段,值来自 story_id 指向的 Story(后端一次查好,前端不用再拉一次)。
   *  只读 —— 要改去 storiesApi.update,权威在 Story。 */
  source_text?: string | null
  story_analysis?: StoryAnalysis | null
  cast?: Record<string, string>
  story_title?: string | null
  project_title?: string | null  // 所属作品名(散稿为 null)
  created_at?: string
}

export interface ScreenplayVersion {
  screenplay: string
  label: string
  created_at: string | null
}

/** 故事库:文本入库产出的是**原文**,不是剧本 —— 故新建/分析/改原文都在这里。
 *
 * 建出来的东西该去哪个列表找,由它是什么决定:原文进 storiesApi.list,
 * 剧本(某集成稿存入的方案)进 scriptsApi.list。 */
export const storiesApi = {
  /** 原文列表。topLevelOnly 只列顶层 —— 切出来的片段属于其父原文的内部结构,
   *  平铺在总览里会把一本小说的 N 段和别的故事混在一起。 */
  list: (params?: { projectId?: string; parentId?: string; topLevelOnly?: boolean }) =>
    api.get<Story[]>('/stories', {
      params: {
        project_id: params?.projectId, parent_id: params?.parentId,
        top_level_only: params?.topLevelOnly,
      },
    }).then(r => r.data),
  get: (id: string) => api.get<Story>(`/stories/${id}`).then(r => r.data),
  /** 分析一段文本并对齐角色(不落库);pending 非空表示需人工确认身份。 */
  analyze: (projectId: string | null | undefined, content: string, llmModel?: string) =>
    api.post<{ story_analysis: Record<string, any>; cast: Record<string, string>; pending: CastPending[] }>(
      '/stories/analyze',
      { project_id: projectId, content, llm_model: llmModel },
    ).then(r => r.data),
  /** 从一段文本建原文。project_id 可省(散稿);cast 是 analyze 的 pending 经确认后的决策。
   *  额外回 script_id:content 非空时顺带建的那个方案(没建则为 null)。 */
  create: (data: {
    project_id?: string | null; title: string; content: string
    story_analysis?: Record<string, any> | null
    cast?: Record<string, { action: string; character_id?: string }>
    parent_id?: string | null; order_index?: number
  }) => api.post<Story & { script_id: string | null }>('/stories', data).then(r => r.data),
  /** 改原文。project_id: 作品 id = 移过去;空串 = 解绑成散稿;不传 = 不动归属。
   *  改原文**不会**自动更新已有的改编方案 —— 那些剧本要重新改编才会跟上。 */
  update: (id: string, data: {
    title?: string; content?: string
    story_analysis?: Record<string, any> | null
    cast?: Record<string, string>
    project_id?: string
  }) => api.patch<Story>(`/stories/${id}`, data).then(r => r.data),
  /** 删原文,连同它切出的片段。仍有改编方案挂在下面时后端回 409。 */
  delete: (id: string) => api.delete(`/stories/${id}`).then(r => r.data),
}

/** 剧本 = 一段原文的一个改编方案。只由「某集剧本通过后存入」产生 ——
 * 从文本新建走 storiesApi.create(那产出的是原文)。
 * 审核类端点(revise/edit/revert/resume)在 workflowApi 的剧集维度。 */
export const scriptsApi = {
  list: (params?: { projectId?: string; storyId?: string }) =>
    api.get<Script[]>('/scripts', {
      params: { project_id: params?.projectId, story_id: params?.storyId },
    }).then(r => r.data),
  get: (id: string) => api.get<Script>(`/scripts/${id}`).then(r => r.data),
  saveFromEpisode: (episodeId: string) =>
    api.post<Script>('/scripts', { episode_id: episodeId }).then(r => r.data),
  /** 改剧本。只改**剧本正文** —— 原文/分析/阵容要改去 storiesApi.update(权威在 Story)。
   *  project_id: 作品 id = 移过去;空串 = 解绑成散稿;不传 = 不动归属。 */
  update: (id: string, data: {
    title?: string; content?: string; project_id?: string
  }) =>
    api.patch<Script>(`/scripts/${id}`, data).then(r => r.data),
  delete: (id: string) => api.delete(`/scripts/${id}`).then(r => r.data),
  /** 整组删除(如一本小说切出的全部分集)。有集在用时后端回 409。 */
  deleteMany: (scriptIds: string[]) =>
    api.post<{ deleted: number }>('/scripts/batch-delete',
      { script_ids: scriptIds }).then(r => r.data),
}

export const workflowApi = {
  start: (episodeId: string) => api.post(`/episodes/${episodeId}/workflow/start`).then(r => r.data),
  resume: (episodeId: string, data: ResumeData) => api.post(`/episodes/${episodeId}/workflow/resume`, data).then(r => r.data),
  status: (episodeId: string) => api.get<WorkflowStatus>(`/episodes/${episodeId}/workflow/status`).then(r => r.data),
  events: (episodeId: string, afterSeq = 0) =>
    api.get<{ events: Array<{ seq: number; type: string; payload_json: Record<string, any> }> }>(
      `/episodes/${episodeId}/workflow/events`, { params: { after_seq: afterSeq } }
    ).then(r => r.data.events),
  // 剧本审核(剧集页):AI 对话式改写 / 手动编辑 / 版本回退。守卫在后端(须暂停在 screenplay_review)。
  reviseEpisode: (episodeId: string, messages: { role: string; content: string }[]) =>
    api.post<{
      action: 'ask' | 'apply'
      reply: string
      screenplay?: string
      version_index?: number
      versions_len?: number
    }>(`/episodes/${episodeId}/screenplay/revise`, { messages }).then(r => r.data),
  editEpisode: (episodeId: string, screenplay: string) =>
    api.post<{ screenplay: string; version_index: number }>(
      `/episodes/${episodeId}/screenplay/edit`, { screenplay }
    ).then(r => r.data),
  revertEpisode: (episodeId: string, versionIndex: number) =>
    api.post<{ screenplay: string; version_index: number }>(
      `/episodes/${episodeId}/screenplay/revert`, { version_index: versionIndex }
    ).then(r => r.data),
}

/** 参考图用途分类。取值与后端 ReferenceType 枚举一一对应。 */
export type ReferenceType = 'character' | 'background'

/**
 * 一条参考图。ref_type 与 removable 都由后端判定下发,前端只消费、**不得**自行推断
 * (按名字反猜类型会把素材库选的图判进错误的组;自行判断可删性会与后端的探测规则分叉)。
 * image_url 为空串 = 已列出但未上传。见规范 4。
 */
export interface ReferenceEntry {
  key: string
  ref_type: ReferenceType
  image_url: string
  /** 生成该图所用的 prompt(提炼后可人工改);重生成时改它,不重新提炼 */
  prompt?: string
  removable?: boolean
}

/** 一个待确认身份的剧本人物。候选角色由后端算好下发,前端不自己拉角色列表(规范 4)。 */
export interface CastPending {
  name: string
  appearance?: string
  suggestions: { character_id: string; name: string }[]
}

export const filesApi = {
  // 图片:项目级(角色/背景跨集共享)
  uploadImage: (projectId: string, file: File, type?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (type) form.append('type', type)
    return api.post<{ path: string; filename: string; url: string; type: string }>(
      `/projects/${projectId}/files/upload`, form,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    ).then(r => r.data)
  },
  /** AI 生成的图落进项目参考目录(生成结果是 base64,没有 File 可 multipart) */
  uploadFromBase64: (projectId: string,
    body: { image_b64: string; type?: string; filename?: string }) =>
    api.post<{ path: string; filename: string; url: string; type: string }>(
      `/projects/${projectId}/files/from-base64`, body).then(r => r.data),
  // 从全局素材库拷贝一份进剧集参考(返回与 uploadImage 同形状)
  copyFromAsset: (projectId: string, assetId: string, type: string) =>
    api.post<{ path: string; filename: string; url: string; type: string }>(
      `/projects/${projectId}/files/from-asset`, { asset_id: assetId, type }
    ).then(r => r.data),
  listImages: (projectId: string) =>
    api.get<Array<{ filename: string; url: string; size_bytes: number; type?: string }>>(`/projects/${projectId}/images`)
      .then(r => r.data).catch(() => [] as Array<{ filename: string; url: string; size_bytes: number; type?: string }>),
  imageUrl: (path: string) => path.startsWith('/') ? path : `/api/uploads/${path}`,
  // 视频产物 / 引用绑定:集级
  listVideos: (episodeId: string) => api.get(`/episodes/${episodeId}/videos`).then(r => r.data),
  exportUrl: (episodeId: string) => `/api/episodes/${episodeId}/export`,
  downloadUrl: (episodeId: string, filename: string) => `/api/episodes/${episodeId}/files/${filename}`,
  getReferences: (episodeId: string) =>
    api.get<{ references: ReferenceEntry[] }>(`/episodes/${episodeId}/references`)
      .then(r => r.data.references ?? []).catch(() => [] as ReferenceEntry[]),
  updateReferences: (episodeId: string, references: ReferenceEntry[]) =>
    api.put<{ ok: boolean; references: ReferenceEntry[] }>(
      `/episodes/${episodeId}/references`, { references }
    ).then(r => r.data.references ?? []),
  /** 参考视频:存本地(长期可播)+ 公网(视频参考只接受公网 URL,没有 base64 那条路)。
   *  preview_url 是后端下发的相对地址,可直接取用于预览;平台侧用的是 storage_key。 */
  uploadVideo: (projectId: string, file: File) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post<{
      storage_key: string; preview_url: string
      duration: number | null; warning: string | null
    }>(`/projects/${projectId}/videos/upload`, fd).then(r => r.data)
  },
}

/** 参考图语义。取值权威在后端 video_refs.RefKind —— 前端不自造第四种。 */
export type ClipRefKind = 'first_frame' | 'last_frame' | 'subject'

export interface ClipRefImage {
  url: string
  kind: ClipRefKind
  subject_name?: string | null
  view?: string | null
}

export interface ClipRefAudio {
  url: string
  subject_name?: string | null
}

/** 散片任务类型。与后端 db.enums.ClipTaskType 同源 —— 自由字符串会静默
 *  走成另一种任务(平台按提示词自行判定)。 */
export type ClipTaskType = 'reference' | 'edit' | 'extend'

/** 参考视频。url 装的是**公网存储的 storage key**(或已是公网 URL)——
 *  平台对视频只接受公网 URL / asset://ID,没有 base64 那条路。 */
export interface ClipRefVideo {
  url: string
  subject_name?: string | null
  /** 该支视频的时长(秒)。后端用它做总时长求和校验(2.5 上限 30s、2.0 上限 15s);
   *  拿不到(未装 ffprobe)时为 null,那一支不计入求和。 */
  duration?: number | null
}

/** 散片 —— 一次「直接生成」请求。status 是 LifecycleStatus(后端唯一权威)。 */
export interface Clip {
  id: string
  project_id: string
  prompt: string
  negative_prompt?: string | null
  duration: number
  resolution: string
  aspect_ratio: string
  video_provider: string
  video_model: string
  seed?: number | null
  references_json?: ClipRefImage[] | null
  audio_refs_json?: ClipRefAudio[] | null
  video_refs_json?: ClipRefVideo[] | null
  task_type?: ClipTaskType
  /** 有它才能被引用为编辑/延长的输入。没有 = 还没同步到对象存储。 */
  storage_key?: string | null
  status: 'created' | 'queued' | 'running' | 'paused' | 'completed' | 'failed'
  error_message?: string | null
  task_id: string
  video_url?: string | null
  local_path?: string | null
  revised_prompt?: string | null
  created_at?: string
  updated_at?: string
}

export interface CreateClipData {
  prompt: string
  negative_prompt?: string
  duration: number
  resolution: string
  aspect_ratio: string
  video_provider: string
  video_model: string
  references?: ClipRefImage[]
  audio_refs?: ClipRefAudio[]
  task_type?: ClipTaskType
  video_refs?: ClipRefVideo[]
}

export const clipsApi = {
  create: (projectId: string, data: CreateClipData) =>
    api.post<{ clip: Clip; job_id: string }>(`/projects/${projectId}/clips`, data)
      .then(r => r.data.clip),
  list: (projectId: string) =>
    api.get<{ clips: Clip[] }>(`/projects/${projectId}/clips`).then(r => r.data.clips),
  get: (projectId: string, clipId: string) =>
    api.get<{ clip: Clip }>(`/projects/${projectId}/clips/${clipId}`).then(r => r.data.clip),
  delete: (projectId: string, clipId: string) =>
    api.delete(`/projects/${projectId}/clips/${clipId}`).then(r => r.data),
}

export const artifactsApi = {
  listByShot: (episodeId: string, shotId: string) =>
    api.get<{ artifacts: VideoArtifact[] }>(`/episodes/${episodeId}/shots/${shotId}/artifacts`).then(r => r.data.artifacts),
  listActions: (episodeId: string, artifactId: string) =>
    api.get<{ actions: ActionOption[] }>(`/episodes/${episodeId}/artifacts/${artifactId}/actions`).then(r => r.data.actions),
  runAction: (episodeId: string, artifactId: string, actionId: string, params: Record<string, unknown>) =>
    api.post<{ artifact: VideoArtifact }>(`/episodes/${episodeId}/artifacts/${artifactId}/actions/${actionId}`, params).then(r => r.data.artifact),
}

export interface ModelCost {
  input?: number | null        // LLM 输入,每百万 token(¥)
  output?: number | null       // LLM 输出,每百万 token(¥)
  per_second?: number | null   // 视频,每秒(¥)
  per_call?: number | null     // 每次调用(¥)
}

export interface ProviderModel {
  id: string
  label: string
  kind: 'llm' | 'video' | 'image'
  input?: string[]
  context_window?: number | null
  resolutions?: string[]
  default_resolution?: string | null
  supported_actions?: string[]
  cost?: ModelCost | null
  is_default?: boolean
}

/** 存储 provider(与模型 provider 同表同 registry,kind="storage")。
 *  凭证里的 SecretKey 走 api_key 字段 —— 它已有 $ENV 解析与列表掩码。 */
export interface StorageProviderConfig {
  bucket?: string
  region?: string
  secret_id?: string
  prefix?: string
  expires_days?: string
}

export interface ProviderInfo {
  provider_id: string
  label: string
  kind: 'llm' | 'video' | 'image' | 'storage'
  protocol: string
  base_url?: string | null
  api_key?: string | null       // 列表/详情列表为掩码;单个详情为真值
  models: ProviderModel[]
  // 自定义接入路径 / 响应映射:同一 protocol 被不同网关代理时路径与响应形态各异。
  // 空 = 走协议官方默认(界面上「自定义接入路径」开关关闭)。
  paths: Record<string, string>
  response_map: Record<string, string>
  builtin: boolean              // 内置(seed 种入):可改凭证/模型,不可删
  enabled: boolean              // 未启用的 provider 不参与可选模型列表
  config?: StorageProviderConfig
}

export interface ProviderInput {
  provider_id: string
  label: string
  kind: 'llm' | 'video' | 'image' | 'storage'
  protocol: string
  base_url?: string | null
  api_key?: string | null
  models: ProviderModel[]
  enabled?: boolean
  paths?: Record<string, string>
  response_map?: Record<string, string>
  config?: StorageProviderConfig
}

/** 每个 protocol 认的功能键 → 官方默认路径。词表由后端下发,前端不另抄一份。 */
export interface ProtocolCatalog {
  llm: string[]
  video: string[]
  image: string[]
  storage: string[]
  ops: Record<string, Record<string, string>>
  response_fields: Record<string, string>
}

export const providersApi = {
  list: () => api.get<ProviderInfo[]>('/providers').then(r => r.data),
  get: (providerId: string) => api.get<ProviderInfo>(`/providers/${providerId}`).then(r => r.data),
  protocols: () => api.get<ProtocolCatalog>('/providers/protocols').then(r => r.data),
  create: (data: ProviderInput) => api.post<ProviderInfo>('/providers', data).then(r => r.data),
  update: (providerId: string, data: ProviderInput) =>
    api.put<ProviderInfo>(`/providers/${providerId}`, data).then(r => r.data),
  delete: (providerId: string) => api.delete(`/providers/${providerId}`).then(r => r.data),
}

export function createWebSocket(episodeId: string, onMessage: (event: { type: string; data: any; seq?: number }) => void, lastSeq = 0) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const ws = new WebSocket(`${protocol}//${host}/ws/episodes/${episodeId}?last_seq=${lastSeq}`)
  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data)) } catch {}
  }
  return ws
}
