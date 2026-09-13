import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  projectsApi: { get: vi.fn(), update: vi.fn() },
  episodesApi: { delete: vi.fn() },
  adaptationApi: { start: vi.fn(), get: vi.fn(), commit: vi.fn() },
  clipsApi: { list: vi.fn(), delete: vi.fn() },
}))

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import ProjectEpisodesPage from '../pages/ProjectEpisodesPage'
import { projectsApi, adaptationApi, clipsApi } from '../services/api'

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
  id: PROJECT_ID, title: '我的短剧', genre: 'drama', visual_style: 'realistic',
  status: episodes.length ? 'running' : 'empty',
  episodes, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
})

describe('ProjectEpisodesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // 默认非小说作品:改编面板自行判定后不渲染,不影响既有断言。
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', scripts: [], source_text: '',
    })
    vi.mocked(clipsApi.list).mockResolvedValue([])
  })

  it('shows empty state + 新建一集 when no episodes', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    renderPage()
    await waitFor(() => expect(screen.getByText('还没有剧集')).toBeInTheDocument())
  })

  it('lists episodes with number/title/status', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([
      { id: 'e1', project_id: PROJECT_ID, episode_number: 1, title: '第一集', status: 'completed',
        llm_model: '', video_provider: 'seedance', video_model: '', resolution: '768P' },
      { id: 'e2', project_id: PROJECT_ID, episode_number: 2, title: '第二集', status: 'running',
        llm_model: '', video_provider: 'minimax', video_model: '', resolution: '2K' },
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
        llm_model: '', video_provider: 'seedance', video_model: '', resolution: '768P' },
    ]))
    renderPage()
    await waitFor(() => screen.getByText('第一集'))
    fireEvent.click(screen.getByText('第一集'))
    expect(mockNavigate).toHaveBeenCalledWith('/episodes/e1')
  })

  it('小说作品挂载改编面板', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'none', scripts: [], source_text: '小说正文',
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('开始改编')).toBeInTheDocument())
  })

  // 面板建集后必须刷新剧集列表,否则新建的 N 集要手动刷新页面才看得见。
  it('建集完成后刷新剧集列表', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', source_text: '小说正文',
      scripts: [{ id: 'sc1', title: '第 1 集', genre: 'drama', content: '正文' }],
    })
    vi.mocked(adaptationApi.commit).mockResolvedValue({
      episodes: [], adaptation_status: 'done',
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('建出 1 集')).toBeInTheDocument())
    expect(projectsApi.get).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByText('建出 1 集'))
    await waitFor(() => expect(projectsApi.get).toHaveBeenCalledTimes(2))
  })

  // 已切出剧本、还没建集时,空态必须指向「建出 N 集」而不是「新建一集」。
  // 指错动作会让用户以为改编白做了(实测:面板列着 2 个剧本,下方却写"点右上角新建一集")。
  it('已切出剧本但未建集时,空态指向「建出 N 集」', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', source_text: '小说正文',
      scripts: [
        { id: 'sc1', title: '第 1 集 · 启程', genre: 'drama', content: '正文一' },
        { id: 'sc2', title: '第 2 集 · 遇险', genre: 'drama', content: '正文二' },
      ],
    } as any)
    renderPage()
    await waitFor(() => expect(
      screen.getByText('已切出 2 个剧本，点上方「建出 2 集」即可生成剧集')).toBeInTheDocument())
    expect(screen.queryByText('点击右上角「新建一集」开始创作第 1 集')).not.toBeInTheDocument()
  })

  it('没有待建集的剧本时,空态仍指向「新建一集」', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(adaptationApi.get).mockResolvedValue({
      adaptation_status: 'done', source_text: '小说正文', scripts: [],
    } as any)
    renderPage()
    await waitFor(() => expect(
      screen.getByText('点击右上角「新建创作」开始')).toBeInTheDocument())
  })

  it('按钮文案是「新建创作」并跳到 /create', async () => {
    // 简单模式不产出集,入口若仍叫「新建一集」就是在骗人
    renderPage()
    await waitFor(() => expect(screen.getByText('新建创作')).toBeInTheDocument())
    fireEvent.click(screen.getByText('新建创作'))
    expect(mockNavigate).toHaveBeenCalledWith(`/projects/${PROJECT_ID}/create`)
  })

  it('展示当前视觉风格标签', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    renderPage()
    await waitFor(() => expect(screen.getByText('写实风')).toBeInTheDocument())
  })

  it('点击风格标签可编辑并保存', async () => {
    vi.mocked(projectsApi.get).mockResolvedValue(projectWith([]))
    vi.mocked(projectsApi.update).mockResolvedValue({
      id: PROJECT_ID, title: '我的短剧', source_text: '', visual_style: 'cyberpunk',
      adaptation_status: 'none',
    } as any)
    renderPage()
    await waitFor(() => screen.getByText('写实风'))
    fireEvent.click(screen.getByText('写实风'))
    fireEvent.change(screen.getByLabelText('视觉风格'), { target: { value: 'cyberpunk' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(projectsApi.update).toHaveBeenCalledWith(
      PROJECT_ID, { visual_style: 'cyberpunk' }))
  })

  it('有散片时列出来', async () => {
    vi.mocked(clipsApi.list).mockResolvedValue([{
      id: 'c-1', project_id: PROJECT_ID, prompt: '一只猫跳上桌子', duration: 5,
      resolution: '1080p', aspect_ratio: '9:16', video_provider: 'seedance',
      video_model: 'seedance', status: 'completed', task_id: 't',
      video_url: 'http://v/1.mp4', local_path: '/out/1.mp4',
    } as any])
    renderPage()
    await waitFor(() => expect(screen.getByText('一只猫跳上桌子')).toBeInTheDocument())
  })
})
