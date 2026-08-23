import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn() },
  episodesApi: { delete: vi.fn() },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectEpisodesPage from '../pages/ProjectEpisodesPage'
import { projectsApi } from '../services/api'

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
  beforeEach(() => vi.clearAllMocks())

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
})
