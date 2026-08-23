import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface Project {
  id: string
  title: string
  genre: string
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
  script_id: string
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
}

export interface CreateEpisodeData {
  title: string
  script_id: string
  llm_model?: string
  video_provider?: string
  video_model?: string
  resolution?: string
  episode_number?: number
  use_keyframes?: boolean
  keyframe_image_model?: string
}

export interface WorkflowStatus {
  episode_id: string
  project_id: string
  db_status: string
  current_stage: string
  paused_at?: string | null
  screenplay?: string
  shots?: Shot[]
  prompts?: Prompt[]
  videos?: Video[]
  assembled_video_path?: string
  story_analysis?: StoryAnalysis
  look_assignments?: Record<string, Record<string, string>>
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
}

export interface LLMModelOption {
  value: string
  label: string
  provider: string
  is_default?: boolean
}

export interface VideoModelOption {
  value: string
  label: string
  provider: string
  resolutions?: string[]
  default_resolution?: string
  is_default?: boolean
}

export interface ImageModelOption {
  value: string
  label: string
  provider: string
  resolutions?: string[]
  default_resolution?: string
  is_default?: boolean
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
  generate: (body: { model_id: string; prompt: string; size?: string; n?: number }) =>
    api.post<{ images: string[] }>('/assets/generate', body).then(r => r.data),
  edit: (body: { asset_id: string; model_id: string; prompt: string; size?: string; n?: number }) =>
    api.post<{ images: string[] }>('/assets/edit', body).then(r => r.data),
  saveGenerated: (body: { category: AssetCategory; name: string; description?: string; image_b64: string }) =>
    api.post<Asset>('/assets/from-generated', body).then(r => r.data),
}

export const promptApi = {
  optimize: (body: { raw_prompt: string; kind?: string; target_model?: string; subject?: string }) =>
    api.post<{ optimized: string }>('/prompt/optimize', body).then(r => r.data),
}

export interface Look {
  id: string; character_id: string; name: string; is_default: boolean
  front_key?: string | null; side_key?: string | null; back_key?: string | null; face_key?: string | null
}
export interface Character { id: string; project_id: string; name: string; description?: string | null; voice_key?: string | null }
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
  generateSheet: (pid: string, cid: string, lid: string,
    body: { model_id: string; character_desc?: string; look_desc?: string }) =>
    api.post<{ views: Record<CharacterViewName, string> }>(
      `/projects/${pid}/characters/${cid}/looks/${lid}/generate-sheet`, body).then(r => r.data),
  saveGeneratedViews: (pid: string, cid: string, lid: string,
    body: { front_b64: string; side_b64?: string; back_b64?: string; face_b64?: string }) =>
    api.post<Look>(`/projects/${pid}/characters/${cid}/looks/${lid}/views-from-generated`, body).then(r => r.data),
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
}

export const projectsApi = {
  list: () => api.get<Project[]>('/projects').then(r => r.data),
  get: (id: string) => api.get<Project>(`/projects/${id}`).then(r => r.data),
  create: (data: CreateProjectData) => api.post<Project>('/projects', data).then(r => r.data),
  delete: (id: string) => api.delete(`/projects/${id}`).then(r => r.data),
}

export const episodesApi = {
  list: (projectId: string) =>
    api.get<Episode[]>(`/projects/${projectId}/episodes`).then(r => r.data),
  get: (projectId: string, episodeId: string) =>
    api.get<Episode>(`/projects/${projectId}/episodes/${episodeId}`).then(r => r.data),
  create: (projectId: string, data: CreateEpisodeData) =>
    api.post<Episode>(`/projects/${projectId}/episodes`, data).then(r => r.data),
  delete: (projectId: string, episodeId: string) =>
    api.delete(`/projects/${projectId}/episodes/${episodeId}`).then(r => r.data),
}

export interface Script {
  id: string
  project_id?: string | null
  episode_index?: number | null
  title: string
  genre: string
  source_text?: string | null
  story_analysis?: StoryAnalysis | null
  content?: string | null
  status: string                 // 生命周期:created(草稿)/queued/running/paused/completed/failed
  error_message?: string | null
  created_at?: string
  updated_at?: string
}

export interface ScreenplayVersion {
  screenplay: string
  label: string
  created_at: string | null
}

export interface ScriptStatus {
  id: string
  status: string
  paused_at?: string | null
  title: string
  content?: string | null
  story_analysis?: StoryAnalysis | null
  error_message?: string | null
  screenplay_versions?: ScreenplayVersion[]
  screenplay_version_current?: number
}

export interface CreateScriptData {
  title: string
  genre?: string
  source_text: string
  project_id?: string | null
  llm_model?: string
}

export const scriptsApi = {
  list: (projectId?: string) =>
    api.get<Script[]>('/scripts', { params: { project_id: projectId } }).then(r => r.data),
  get: (id: string) => api.get<Script>(`/scripts/${id}`).then(r => r.data),
  create: (data: CreateScriptData) => api.post<Script>('/scripts', data).then(r => r.data),
  update: (id: string, data: { title?: string; content?: string }) =>
    api.put<Script>(`/scripts/${id}`, data).then(r => r.data),
  delete: (id: string) => api.delete(`/scripts/${id}`).then(r => r.data),
  start: (id: string) => api.post(`/scripts/${id}/start`).then(r => r.data),
  retry: (id: string) => api.post(`/scripts/${id}/retry`).then(r => r.data),
  resume: (id: string, data: { approved: boolean; notes?: string; edited_prompts?: Record<string, string> }) =>
    api.post(`/scripts/${id}/resume`, data).then(r => r.data),
  status: (id: string) => api.get<ScriptStatus>(`/scripts/${id}/status`).then(r => r.data),
  revise: (id: string, messages: { role: string; content: string }[]) =>
    api.post<{
      action: 'ask' | 'apply'
      reply: string
      screenplay?: string
      version_index?: number
      versions_len?: number
    }>(`/scripts/${id}/revise`, { messages }).then(r => r.data),
  editScreenplay: (id: string, screenplay: string) =>
    api.post<{ screenplay: string; version_index: number }>(
      `/scripts/${id}/edit_screenplay`, { screenplay }
    ).then(r => r.data),
  revert: (id: string, versionIndex: number) =>
    api.post<{ screenplay: string; version_index: number }>(
      `/scripts/${id}/revert`, { version_index: versionIndex }
    ).then(r => r.data),
}

export const workflowApi = {
  start: (episodeId: string) => api.post(`/episodes/${episodeId}/workflow/start`).then(r => r.data),
  resume: (episodeId: string, data: ResumeData) => api.post(`/episodes/${episodeId}/workflow/resume`, data).then(r => r.data),
  status: (episodeId: string) => api.get<WorkflowStatus>(`/episodes/${episodeId}/workflow/status`).then(r => r.data),
  events: (episodeId: string, afterSeq = 0) =>
    api.get<{ events: Array<{ seq: number; type: string; payload_json: Record<string, any> }> }>(
      `/episodes/${episodeId}/workflow/events`, { params: { after_seq: afterSeq } }
    ).then(r => r.data.events),
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
    api.get<{ character_references: Record<string, string> }>(`/episodes/${episodeId}/references`)
      .then(r => r.data.character_references).catch(() => ({} as Record<string, string>)),
  updateReferences: (episodeId: string, references: Array<{ key: string; ref_type: string; image_url: string }>) =>
    api.put<{ ok: boolean; character_references: Record<string, string> }>(
      `/episodes/${episodeId}/references`, { references }
    ).then(r => r.data),
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

export interface ProviderInfo {
  provider_id: string
  label: string
  kind: 'llm' | 'video' | 'image'
  protocol: string
  base_url?: string | null
  api_key?: string | null       // 列表/详情列表为掩码;单个详情为真值
  models: ProviderModel[]
  builtin: boolean              // 内置(seed 种入):可改凭证/模型,不可删
  enabled: boolean              // 未启用的 provider 不参与可选模型列表
}

export interface ProviderInput {
  provider_id: string
  label: string
  kind: 'llm' | 'video' | 'image'
  protocol: string
  base_url?: string | null
  api_key?: string | null
  models: ProviderModel[]
  enabled?: boolean
}

export const providersApi = {
  list: () => api.get<ProviderInfo[]>('/providers').then(r => r.data),
  get: (providerId: string) => api.get<ProviderInfo>(`/providers/${providerId}`).then(r => r.data),
  protocols: () => api.get<{ llm: string[]; video: string[]; image: string[] }>('/providers/protocols').then(r => r.data),
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
