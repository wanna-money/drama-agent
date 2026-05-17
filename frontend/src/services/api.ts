import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export interface Project {
  id: string
  title: string
  status: string
  genre: string
  llm_model: string
  video_provider: string
  created_at: string
  updated_at: string
  raw_input?: string
  state_snapshot?: Record<string, any>
  error_message?: string
}

export interface CreateProjectData {
  title: string
  raw_input: string
  genre?: string
  llm_model?: string
  video_provider?: string
  video_model?: string
}

export interface WorkflowStatus {
  project_id: string
  db_status: string
  current_stage: string
  screenplay?: string
  shots?: Shot[]
  prompts?: Prompt[]
  videos?: Video[]
  assembled_video_path?: string
  story_analysis?: StoryAnalysis
  character_references?: Record<string, string>
  next?: string[]
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
}

export interface LLMModelOption {
  value: string
  label: string
  provider: string
}

export interface VideoModelOption {
  value: string
  label: string
  provider: string
}

export const configApi = {
  listModels: () =>
    api.get<{ models: LLMModelOption[] }>('/config/models').then(r => r.data.models),
  listVideoModels: () =>
    api.get<{ models: VideoModelOption[] }>('/config/video-models').then(r => r.data.models),
}

export const projectsApi = {
  list: () => api.get<Project[]>('/projects').then(r => r.data),
  get: (id: string) => api.get<Project>(`/projects/${id}`).then(r => r.data),
  create: (data: CreateProjectData) => api.post<Project>('/projects', data).then(r => r.data),
  delete: (id: string) => api.delete(`/projects/${id}`).then(r => r.data),
}

export const workflowApi = {
  start: (id: string) => api.post(`/projects/${id}/workflow/start`).then(r => r.data),
  resume: (id: string, data: ResumeData) => api.post(`/projects/${id}/workflow/resume`, data).then(r => r.data),
  status: (id: string) => api.get<WorkflowStatus>(`/projects/${id}/workflow/status`).then(r => r.data),
}

export const filesApi = {
  uploadImage: (projectId: string, file: File, type?: string) => {
    const form = new FormData()
    form.append('file', file)
    if (type) form.append('type', type)
    return api.post<{ path: string; filename: string; url: string; type: string }>(
      `/projects/${projectId}/files/upload`, form,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    ).then(r => r.data)
  },
  listImages: (projectId: string) =>
    api.get<Array<{ filename: string; url: string; size_bytes: number; type?: string }>>(`/projects/${projectId}/images`)
      .then(r => r.data).catch(() => [] as Array<{ filename: string; url: string; size_bytes: number; type?: string }>),
  listVideos: (projectId: string) => api.get(`/projects/${projectId}/videos`).then(r => r.data),
  exportUrl: (projectId: string) => `/api/projects/${projectId}/export`,
  downloadUrl: (projectId: string, filename: string) => `/api/projects/${projectId}/files/${filename}`,
  imageUrl: (path: string) => path.startsWith('/') ? path : `/api/uploads/${path}`,
  getReferences: (projectId: string) =>
    api.get<{ character_references: Record<string, string> }>(`/projects/${projectId}/references`)
      .then(r => r.data.character_references).catch(() => ({} as Record<string, string>)),
  updateReferences: (projectId: string, references: Array<{ key: string; ref_type: string; image_url: string }>) =>
    api.put<{ ok: boolean; character_references: Record<string, string> }>(
      `/projects/${projectId}/references`, { references }
    ).then(r => r.data),
}

export function createWebSocket(projectId: string, onMessage: (event: { type: string; data: any }) => void) {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const ws = new WebSocket(`${protocol}//${host}/ws/${projectId}`)
  ws.onmessage = (e) => {
    try { onMessage(JSON.parse(e.data)) } catch {}
  }
  return ws
}
