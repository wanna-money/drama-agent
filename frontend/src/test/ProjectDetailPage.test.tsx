import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import React from 'react'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn() },
  workflowApi: { start: vi.fn(), resume: vi.fn(), status: vi.fn() },
  filesApi: {
    uploadImage: vi.fn(),
    updateReferences: vi.fn(),
    exportUrl: (id: string) => `/api/projects/${id}/export`,
    downloadUrl: (id: string, f: string) => `/api/projects/${id}/files/${f}`,
  },
  createWebSocket: vi.fn(),
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectDetailPage from '../pages/ProjectDetailPage'
import { projectsApi, workflowApi, createWebSocket } from '../services/api'
import { Toast } from '@douyinfe/semi-ui'

const PROJECT_ID = 'proj-123'

const baseProject = {
  id: PROJECT_ID,
  title: '测试短剧',
  status: 'created',
  genre: 'drama',
  llm_model: 'kimi-k2-0711-preview',
  video_provider: 'seedance',
  raw_input: '一个测试故事',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const baseStatus = {
  project_id: PROJECT_ID,
  db_status: 'created',
  current_stage: 'created',
  next: [],
}

function makeWsMock() {
  const ws: any = { onmessage: null, onclose: null, close: vi.fn() }
  return ws
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}`]}>
      <Routes>
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
      </Routes>
    </MemoryRouter>
  )

describe('ProjectDetailPage', () => {
  let wsMock: ReturnType<typeof makeWsMock>

  beforeEach(() => {
    vi.clearAllMocks()
    wsMock = makeWsMock()
    vi.mocked(createWebSocket).mockReturnValue(wsMock)
    vi.mocked(projectsApi.get).mockResolvedValue(baseProject)
    vi.mocked(workflowApi.status).mockResolvedValue(baseStatus)
  })

  // ── Loading & not-found ───────────────────────────────────────────────────

  it('shows loading spinner on initial load', () => {
    vi.mocked(projectsApi.get).mockReturnValue(new Promise(() => {}))
    vi.mocked(workflowApi.status).mockReturnValue(new Promise(() => {}))
    renderPage()
    expect(screen.getByTestId('spin')).toBeInTheDocument()
  })

  it('shows not-found state when project returns null', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(null as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('项目未找到')).toBeInTheDocument())
    expect(screen.getByText('返回列表')).toBeInTheDocument()
  })

  it('navigates home when "返回列表" clicked on not-found', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(null as any)
    renderPage()
    await waitFor(() => screen.getByText('返回列表'))
    fireEvent.click(screen.getByText('返回列表'))
    expect(mockNavigate).toHaveBeenCalledWith('/')
  })

  // ── Created state ─────────────────────────────────────────────────────────

  it('renders project title and genre tags', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('测试短剧')).toBeInTheDocument())
    expect(screen.getByText('drama')).toBeInTheDocument()
    expect(screen.getByText('Seedance 2.0')).toBeInTheDocument()
  })

  it('maps bailian video_provider to display label', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, video_provider: 'bailian' })
    renderPage()
    await waitFor(() => expect(screen.getByText('万相 2.7')).toBeInTheDocument())
  })

  it('shows 开始制作 CTA in created state', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('开始制作')).toBeInTheDocument())
  })

  it('renders progress steps', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByTestId('steps')).toBeInTheDocument())
    expect(screen.getByText('故事分析')).toBeInTheDocument()
    expect(screen.getByText('生成剧本')).toBeInTheDocument()
    expect(screen.getByText('完成')).toBeInTheDocument()
  })

  it('raw_input section is collapsed by default and expands on click', async () => {
    renderPage()
    await waitFor(() => screen.getByText('故事内容'))
    expect(screen.queryByText('一个测试故事')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('故事内容').closest('div')!)
    await waitFor(() => expect(screen.getByText('一个测试故事')).toBeInTheDocument())
  })

  it('navigates back on ← 返回列表 click', async () => {
    renderPage()
    await waitFor(() => screen.getByText('← 返回列表'))
    fireEvent.click(screen.getByText('← 返回列表'))
    expect(mockNavigate).toHaveBeenCalledWith('/')
  })

  // ── Start workflow ────────────────────────────────────────────────────────

  it('calls workflowApi.start and shows toast on success', async () => {
    vi.mocked(workflowApi.start).mockResolvedValue({})
    // first call: created (shows 开始制作), second: after start
    vi.mocked(projectsApi.get)
      .mockResolvedValueOnce(baseProject)
      .mockResolvedValue({ ...baseProject, status: 'analyzing' })
    vi.mocked(workflowApi.status)
      .mockResolvedValueOnce(baseStatus)
      .mockResolvedValue({ ...baseStatus, current_stage: 'analyzing' })
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(workflowApi.start).toHaveBeenCalledWith(PROJECT_ID))
    expect(Toast.info).toHaveBeenCalledWith('制作流程已启动')
  })

  it('shows error toast when start fails', async () => {
    vi.mocked(workflowApi.start).mockRejectedValue({ message: 'network error' })
    renderPage()
    await waitFor(() => screen.getByText('开始制作'))
    fireEvent.click(screen.getByText('开始制作'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
  })

  // ── Story analysis ────────────────────────────────────────────────────────

  it('renders story analysis section when available', async () => {
    const storyStatus = {
      ...baseStatus,
      current_stage: 'story_analyzed',
      story_analysis: {
        title: '测试', genre: '现代剧', tone: '轻松', themes: ['友情', '成长'],
        plot_summary: '这是一个故事梗概',
        characters: [{ name: '小明', appearance: '高个子', personality: '开朗' }],
        setting: '都市',
      },
    }
    vi.mocked(workflowApi.status).mockResolvedValue(storyStatus)
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'story_analyzed' })
    renderPage()
    await waitFor(() => expect(screen.getByText('这是一个故事梗概')).toBeInTheDocument())
    expect(screen.getAllByText('小明').length).toBeGreaterThan(0)
    expect(screen.getAllByText('故事分析').length).toBeGreaterThan(0)
  })

  it('story analysis: 查看原文 toggle shows raw_input', async () => {
    const storyStatus = {
      ...baseStatus,
      current_stage: 'story_analyzed',
      story_analysis: { title: 't', genre: 'g', tone: 'n', themes: [], plot_summary: '梗概', characters: [], setting: '' },
    }
    vi.mocked(workflowApi.status).mockResolvedValue(storyStatus)
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'story_analyzed' })
    renderPage()
    await waitFor(() => screen.getByText('查看原文 ▼'))
    expect(screen.queryByText('原始故事')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('查看原文 ▼'))
    await waitFor(() => expect(screen.getByText('原始故事')).toBeInTheDocument())
  })

  // ── Screenplay review ─────────────────────────────────────────────────────

  it('shows screenplay and review buttons when at screenplay_review stage', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'screenplay_review',
      next: ['screenplay_review'],
      screenplay: '第一幕\n故事开始...',
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'screenplay_review' })
    renderPage()
    await waitFor(() => expect(screen.getByText('通过')).toBeInTheDocument())
    expect(screen.getByText('修改')).toBeInTheDocument()
    expect(screen.getByText('等待您审核剧本，确认内容后点击「通过」，或提交修改意见')).toBeInTheDocument()
    // screenplay content rendered inside <pre>
    expect(screen.getByText(/第一幕/)).toBeInTheDocument()
  })

  it('calls workflowApi.resume with approved=true on 通过 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'screenplay_review',
      next: ['screenplay_review'],
      screenplay: '剧本内容',
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'screenplay_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await waitFor(() => screen.getByText('通过'))
    fireEvent.click(screen.getByText('通过'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(PROJECT_ID, expect.objectContaining({ approved: true })))
    expect(Toast.success).toHaveBeenCalledWith('剧本已通过')
  })

  // ── Storyboard ────────────────────────────────────────────────────────────

  it('renders storyboard table when shots are available', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'storyboard_ready',
      shots: [{
        shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景',
        camera_movement: '固定', duration_seconds: 5,
        description: '第一个镜头描述', characters: ['小明'], dialogue: '', action: '', location: '室内',
      }],
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'storyboard_ready' })
    renderPage()
    await waitFor(() => expect(screen.getByText('分镜脚本 · 1 个镜头')).toBeInTheDocument())
    expect(screen.getByText('第一个镜头描述')).toBeInTheDocument()
    expect(screen.getByText('5s')).toBeInTheDocument()
  })

  // ── Prompts review ────────────────────────────────────────────────────────

  it('renders prompts section and confirm button at prompts_review stage', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_review',
      next: ['prompts_review'],
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'a cinematic shot', negative_prompt: '', approved: false }],
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'prompts_review' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频 Prompt · 1 个')).toBeInTheDocument())
    expect(screen.getByText('全部确认，开始生成视频')).toBeInTheDocument()
    expect(screen.getByDisplayValue('a cinematic shot')).toBeInTheDocument()
  })

  it('calls resume with edited prompts on 全部确认 click', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'prompts_review',
      next: ['prompts_review'],
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '固定', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      prompts: [{ shot_id: 's1', prompt_text: 'original prompt', negative_prompt: '', approved: false }],
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'prompts_review' })
    vi.mocked(workflowApi.resume).mockResolvedValue({})
    renderPage()
    await waitFor(() => screen.getByDisplayValue('original prompt'))
    fireEvent.change(screen.getByDisplayValue('original prompt'), { target: { value: 'edited prompt' } })
    fireEvent.click(screen.getByText('全部确认，开始生成视频'))
    await waitFor(() => expect(workflowApi.resume).toHaveBeenCalledWith(
      PROJECT_ID,
      expect.objectContaining({ approved: true, edited_prompts: { s1: 'edited prompt' } })
    ))
  })

  // ── Video generation ──────────────────────────────────────────────────────

  it('shows video generation progress section', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'running' }],
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'videos_generated' })
    renderPage()
    await waitFor(() => expect(screen.getByText('视频生成进度')).toBeInTheDocument())
    expect(screen.getByText('生成中')).toBeInTheDocument()
  })

  it('shows completed video status', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '全景', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'succeeded', local_path: '/some/path.mp4' }],
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'videos_generated' })
    renderPage()
    // "完成" tag — distinguish from "完成" step by checking for the videos section
    await waitFor(() => expect(screen.getByText('视频生成进度')).toBeInTheDocument())
    expect(screen.getAllByText('完成').length).toBeGreaterThan(0)
  })

  it('shows failed video status with error', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'videos_generated',
      shots: [{ shot_id: 's1', scene_number: 1, shot_number: 1, shot_type: '', camera_movement: '', duration_seconds: 5, description: '', characters: [], dialogue: '', action: '', location: '' }],
      videos: [{ shot_id: 's1', task_id: 't1', status: 'failed', error: '生成超时' }],
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'videos_generated' })
    renderPage()
    await waitFor(() => expect(screen.getByText('错误: 生成超时')).toBeInTheDocument())
  })

  // ── Completed / final video ───────────────────────────────────────────────

  it('shows final video section and download button when completed', async () => {
    vi.mocked(workflowApi.status).mockResolvedValue({
      ...baseStatus,
      current_stage: 'completed',
      assembled_video_path: '/data/outputs/final.mp4',
    })
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'completed' })
    renderPage()
    await waitFor(() => expect(screen.getByText('✦ 最终成片')).toBeInTheDocument())
    expect(screen.getByText('下载完整视频')).toBeInTheDocument()
  })

  // ── Error state ───────────────────────────────────────────────────────────

  it('shows error message section when project has error_message', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'failed', error_message: '工作流执行失败' })
    renderPage()
    await waitFor(() => expect(screen.getByText('工作流执行失败')).toBeInTheDocument())
  })

  // ── WebSocket events ──────────────────────────────────────────────────────

  it('creates websocket on mount and closes on unmount', async () => {
    const { unmount } = renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalledWith(PROJECT_ID, expect.any(Function)))
    unmount()
    expect(wsMock.close).toHaveBeenCalled()
  })

  it('refreshes status on stage_change WebSocket event', async () => {
    vi.mocked(workflowApi.status)
      .mockResolvedValueOnce(baseStatus)
      .mockResolvedValue({ ...baseStatus, current_stage: 'story_analyzed' })
    vi.mocked(projectsApi.get)
      .mockResolvedValueOnce(baseProject)
      .mockResolvedValue({ ...baseProject, status: 'story_analyzed' })
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    // Trigger stage_change event
    const [[, onMessage]] = vi.mocked(createWebSocket).mock.calls
    onMessage({ type: 'stage_change', data: { stage: 'story_analyzed' } })
    await waitFor(() => expect(workflowApi.status).toHaveBeenCalledTimes(2))
  })

  it('shows error toast on WebSocket error event', async () => {
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    const [[, onMessage]] = vi.mocked(createWebSocket).mock.calls
    onMessage({ type: 'error', data: { message: 'node failed' } })
    expect(Toast.error).toHaveBeenCalledWith('工作流错误: node failed')
  })

  it('shows disconnect warning toast for active project on dirty close', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue({ ...baseProject, status: 'analyzing' })
    vi.mocked(workflowApi.status).mockResolvedValue({ ...baseStatus, current_stage: 'analyzing' })
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    wsMock.onclose?.({ wasClean: false })
    expect(Toast.warning).toHaveBeenCalled()
  })

  it('does NOT show disconnect warning for inactive project on dirty close', async () => {
    renderPage()
    await waitFor(() => expect(createWebSocket).toHaveBeenCalled())
    wsMock.onclose?.({ wasClean: false })
    expect(Toast.warning).not.toHaveBeenCalled()
  })
})
