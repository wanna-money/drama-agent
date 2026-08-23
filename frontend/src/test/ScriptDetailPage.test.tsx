import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  scriptsApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    start: vi.fn(),
    retry: vi.fn(),
    resume: vi.fn(),
    status: vi.fn(),
    revise: vi.fn(),
    editScreenplay: vi.fn(),
    revert: vi.fn(),
  },
}))

import ScriptDetailPage from '../pages/ScriptDetailPage'
import { scriptsApi } from '../services/api'

const SCRIPT_ID = 's-1'

const baseStatus = {
  id: SCRIPT_ID,
  status: 'completed',
  paused_at: null as string | null,
  title: '夏日重逢',
  content: '第一场 海边',
  story_analysis: null,
  error_message: null,
}

const renderPage = () =>
  render(
    <MemoryRouter initialEntries={[`/scripts/${SCRIPT_ID}`]}>
      <Routes>
        <Route path="/scripts/:id" element={<ScriptDetailPage />} />
      </Routes>
    </MemoryRouter>
  )

describe('ScriptDetailPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('approves the screenplay when paused at screenplay_review', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue({
      ...baseStatus, status: 'paused', paused_at: 'screenplay_review',
    })
    vi.mocked(scriptsApi.resume).mockResolvedValue(undefined)
    renderPage()

    await waitFor(() => expect(screen.getByText('通过')).toBeInTheDocument())
    fireEvent.click(screen.getByText('通过'))

    await waitFor(() => expect(scriptsApi.resume).toHaveBeenCalledWith(
      SCRIPT_ID, expect.objectContaining({ approved: true })
    ))
  })

  it('hides review controls when the script is not awaiting review', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(baseStatus)
    renderPage()

    await waitFor(() => expect(screen.getByText('第一场 海边')).toBeInTheDocument())
    expect(screen.queryByText('通过')).not.toBeInTheDocument()
    // completed 态可编辑
    expect(screen.getByText('编辑')).toBeInTheDocument()
  })

  it('shows breadcrumb 剧本库 › {script title}', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(baseStatus)
    renderPage()

    await waitFor(() => expect(screen.getByText('剧本库')).toBeInTheDocument())
  })

  it('enqueues content generation for a draft', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue({
      ...baseStatus, status: 'created', content: null,
    })
    vi.mocked(scriptsApi.start).mockResolvedValue(undefined)
    renderPage()

    await waitFor(() => expect(screen.getByText('生成正文')).toBeInTheDocument())
    fireEvent.click(screen.getByText('生成正文'))

    await waitFor(() => expect(scriptsApi.start).toHaveBeenCalledWith(SCRIPT_ID))
  })
})

describe('ScriptDetailPage · 对话式改写 + 版本 + 编辑', () => {
  beforeEach(() => vi.clearAllMocks())

  const reviewStatus = {
    id: SCRIPT_ID,
    status: 'paused',
    paused_at: 'screenplay_review' as string | null,
    title: '夏日重逢',
    content: '第一场 海边',
    story_analysis: null,
    error_message: null,
    screenplay_versions: [
      { screenplay: '第一场 海边', label: '初稿', created_at: null },
    ],
    screenplay_version_current: 0,
  }

  it('sends chat message with full history and refreshes on apply', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(reviewStatus)
    vi.mocked(scriptsApi.revise).mockResolvedValue({
      action: 'apply', reply: '改好了', screenplay: '第一场 海边(改)',
      version_index: 1, versions_len: 2,
    })
    renderPage()

    await waitFor(() => expect(screen.getByTestId('chat')).toBeInTheDocument())
    const input = screen.getByPlaceholderText('和编剧助手说说想怎么改…')
    fireEvent.change(input, { target: { value: '把基调改轻松一点' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(scriptsApi.revise).toHaveBeenCalledWith(
      SCRIPT_ID, [{ role: 'user', content: '把基调改轻松一点' }]
    ))
    // apply 触发 refresh:第二次 status 调用
    await waitFor(() => expect(scriptsApi.status).toHaveBeenCalledTimes(2))
  })

  it('does not refresh when agent replies with ask', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(reviewStatus)
    vi.mocked(scriptsApi.revise).mockResolvedValue({ action: 'ask', reply: '你想具体改哪一场?' })
    renderPage()

    await waitFor(() => expect(screen.getByTestId('chat')).toBeInTheDocument())
    const input = screen.getByPlaceholderText('和编剧助手说说想怎么改…')
    fireEvent.change(input, { target: { value: '改一下' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => expect(screen.getByText(/你想具体改哪一场/)).toBeInTheDocument())
    expect(scriptsApi.status).toHaveBeenCalledTimes(1)
  })

  it('switches to edit mode, saves manual edit, and refreshes', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(reviewStatus)
    vi.mocked(scriptsApi.editScreenplay).mockResolvedValue({ screenplay: '手改后的正文', version_index: 1 })
    renderPage()

    await waitFor(() => expect(screen.getByText('编辑')).toBeInTheDocument())
    fireEvent.click(screen.getByText('编辑'))

    const textarea = await screen.findByDisplayValue('第一场 海边')
    fireEvent.change(textarea, { target: { value: '手改后的正文' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => expect(scriptsApi.editScreenplay).toHaveBeenCalledWith(SCRIPT_ID, '手改后的正文'))
    await waitFor(() => expect(scriptsApi.status).toHaveBeenCalledTimes(2))
  })

  it('previews a historical version and reverts to it', async () => {
    const twoVersionStatus = {
      ...reviewStatus,
      content: '第二版正文',
      screenplay_versions: [
        { screenplay: '第一场 海边', label: '初稿', created_at: null },
        { screenplay: '第二版正文', label: 'AI 改写', created_at: null },
      ],
      screenplay_version_current: 1,
    }
    vi.mocked(scriptsApi.status).mockResolvedValue(twoVersionStatus)
    vi.mocked(scriptsApi.revert).mockResolvedValue({ screenplay: '第一场 海边', version_index: 0 })
    renderPage()

    await waitFor(() => expect(screen.getByText('第二版正文')).toBeInTheDocument())
    const versionSelect = screen.getByRole('combobox') as HTMLSelectElement
    fireEvent.change(versionSelect, { target: { value: '0' } })

    await waitFor(() => expect(screen.getByText('第一场 海边')).toBeInTheDocument())
    expect(screen.getByText('恢复到此版本')).toBeInTheDocument()
    fireEvent.click(screen.getByText('恢复到此版本'))

    await waitFor(() => expect(scriptsApi.revert).toHaveBeenCalledWith(SCRIPT_ID, 0))
    await waitFor(() => expect(scriptsApi.status).toHaveBeenCalledTimes(2))
  })

  it('shows 通过 button only when viewing the current version', async () => {
    const twoVersionStatus = {
      ...reviewStatus,
      content: '第二版正文',
      screenplay_versions: [
        { screenplay: '第一场 海边', label: '初稿', created_at: null },
        { screenplay: '第二版正文', label: 'AI 改写', created_at: null },
      ],
      screenplay_version_current: 1,
    }
    vi.mocked(scriptsApi.status).mockResolvedValue(twoVersionStatus)
    renderPage()

    await waitFor(() => expect(screen.getByText('通过')).toBeInTheDocument())
    const versionSelect = screen.getByRole('combobox') as HTMLSelectElement
    fireEvent.change(versionSelect, { target: { value: '0' } })

    await waitFor(() => expect(screen.queryByText('通过')).not.toBeInTheDocument())
  })

  it('carries prior turns in the messages payload on a follow-up send', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(reviewStatus)
    vi.mocked(scriptsApi.revise).mockResolvedValue({
      action: 'apply', reply: '改好了', screenplay: '第一场 海边(改)',
      version_index: 1, versions_len: 2,
    })
    renderPage()

    await waitFor(() => expect(screen.getByTestId('chat')).toBeInTheDocument())
    const send = (text: string) => {
      const input = screen.getByPlaceholderText('和编剧助手说说想怎么改…')
      fireEvent.change(input, { target: { value: text } })
      fireEvent.keyDown(input, { key: 'Enter' })
    }

    send('第一轮')
    await waitFor(() => expect(screen.getByText(/改好了/)).toBeInTheDocument())

    send('第二轮')
    // 第二次调用必须带上第一轮的用户消息 + 助手回复,而不只是当前这一条
    await waitFor(() => expect(vi.mocked(scriptsApi.revise).mock.calls[1][1]).toEqual([
      { role: 'user', content: '第一轮' },
      { role: 'assistant', content: '改好了' },
      { role: 'user', content: '第二轮' },
    ]))
  })

  it('locks the version selector while editing so the buffer cannot outlive its source', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(reviewStatus)
    renderPage()

    await waitFor(() => expect(screen.getByText('编辑')).toBeInTheDocument())
    expect(screen.getByRole('combobox')).not.toBeDisabled()

    fireEvent.click(screen.getByText('编辑'))

    await waitFor(() => expect(screen.getByRole('combobox')).toBeDisabled())
  })

  it('leaves edit mode when an AI rewrite is applied', async () => {
    vi.mocked(scriptsApi.status).mockResolvedValue(reviewStatus)
    vi.mocked(scriptsApi.revise).mockResolvedValue({
      action: 'apply', reply: '改好了', screenplay: '第一场 海边(改)',
      version_index: 1, versions_len: 2,
    })
    renderPage()

    await waitFor(() => expect(screen.getByText('编辑')).toBeInTheDocument())
    fireEvent.click(screen.getByText('编辑'))
    await screen.findByDisplayValue('第一场 海边')

    const input = screen.getByPlaceholderText('和编剧助手说说想怎么改…')
    fireEvent.change(input, { target: { value: '改活泼一点' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    // apply 后必须退出编辑态,否则「保存」会用改写前的旧缓冲覆盖 AI 刚产出的版本
    await waitFor(() => expect(screen.queryByText('保存')).not.toBeInTheDocument())
    expect(screen.getByText('编辑')).toBeInTheDocument()
  })
})
