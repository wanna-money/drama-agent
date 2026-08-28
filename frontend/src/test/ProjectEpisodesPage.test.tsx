import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn() },
  episodesApi: { delete: vi.fn() },
  adaptationApi: { start: vi.fn(), get: vi.fn(), saveDraft: vi.fn(), commit: vi.fn() },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectEpisodesPage from '../pages/ProjectEpisodesPage'
import { projectsApi, adaptationApi } from '../services/api'

const PROJECT_ID = 'proj-1'
const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT_ID}`]}>
      <Routes>
        <Route path="/projects/:id" element={<ProjectEpisodesPage />} />
      </Routes>
    </MemoryRouter>
  )

const projectWith = (episodes: any[]) => ({
  id: PROJECT_ID, title: '我的短剧', genre: 'drama', status: episodes.length ? 'running' : 'empty',
  episodes, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
})

describe('ProjectEpisodesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认非小说作品:改编面板自行判定后不渲染,不影响既有断言。
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', adapted_draft: [], source_text: '',
    })
  })

  it('shows empty state + 新建一集 when no episodes', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    renderPage()
    await waitFor(() => expect(screen.getByText('还没有剧集')).toBeInTheDocument())
  })

  it('lists episodes with number/title/status', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([
      { id: 'e1', project_id: PROJECT_ID, episode_number: 1, title: '第一集', status: 'completed',
        raw_input: '', llm_model: '', video_provider: 'seedance', video_model: '', resolution: '768P' },
      { id: 'e2', project_id: PROJECT_ID, episode_number: 2, title: '第二集', status: 'running',
        raw_input: '', llm_model: '', video_provider: 'minimax', video_model: '', resolution: '2K' },
    ]))
    renderPage()
    await waitFor(() => expect(screen.getByText('第一集')).toBeInTheDocument())
    expect(screen.getByText('第二集')).toBeInTheDocument()
    expect(screen.getByText('EP 01')).toBeInTheDocument()
    expect(screen.getByText('EP 02')).toBeInTheDocument()
  })

  it('shows breadcrumb 作品列表 › {project title}', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    renderPage()
    await waitFor(() => expect(screen.getByText('作品列表')).toBeInTheDocument())
    expect(screen.getAllByText('我的短剧').length).toBeGreaterThan(0)
  })

  it('navigates to episode creation page on row click', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([
      { id: 'e1', project_id: PROJECT_ID, episode_number: 1, title: '第一集', status: 'created',
        raw_input: '', llm_model: '', video_provider: 'seedance', video_model: '', resolution: '768P' },
    ]))
    renderPage()
    await waitFor(() => screen.getByText('第一集'))
    fireEvent.click(screen.getByText('第一集'))
    expect(mockNavigate).toHaveBeenCalledWith('/episodes/e1')
  })

  it('小说作品挂载改编面板', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', adapted_draft: [], source_text: '小说正文',
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('开始改编')).toBeInTheDocument())
  })

  // 面板建集后必须刷新剧集列表,否则新建的 N 集要手动刷新页面才看得见。
  it('建集完成后刷新剧集列表', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'draft_ready', source_text: '小说正文',
      adapted_draft: [{ index: 1, title: '第 1 集', screenplay: '正文' }],
    })
    vi.mocked(adaptationApi.commit).mockResolvedValue({
      episodes: [], adaptation_status: 'committed',
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('确认,建出 1 集')).toBeInTheDocument())
    expect(projectsApi.get).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByText('确认,建出 1 集'))
    await waitFor(() => expect(projectsApi.get).toHaveBeenCalledTimes(2))
  })
})
