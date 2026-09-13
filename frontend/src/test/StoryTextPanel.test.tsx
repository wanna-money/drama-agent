import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import './mocks'

vi.mock('../services/api', () => ({
  storyTextApi: { revise: vi.fn(), parseAttachment: vi.fn() },
}))

import StoryTextPanel from '../components/StoryTextPanel'
import { storyTextApi } from '../services/api'
import { Toast } from '@douyinfe/semi-ui'

const APPLY = { action: 'apply' as const, reply: '改好了', text: '改写后的故事', summary: '更紧凑' }
const ASK = { action: 'ask' as const, reply: '你想怎么改?', text: null, summary: null }

describe('StoryTextPanel', () => {
  beforeEach(() => vi.clearAllMocks())

  const setup = (props: Partial<Parameters<typeof StoryTextPanel>[0]> = {}) => {
    const onSave = vi.fn(() => Promise.resolve())
    render(<StoryTextPanel text="原来的故事" onSave={onSave} {...props} />)
    return { onSave }
  }

  /** 进编辑态(左编辑框 + 右助手)。 */
  const edit = () => fireEvent.click(screen.getByText('编辑'))

  const box = () => screen.getByPlaceholderText(/粘贴内容/) as HTMLTextAreaElement
  const chatInput = () => screen.getByPlaceholderText(/说说想怎么改/)

  const say = (text: string) => {
    const input = chatInput() as HTMLInputElement
    fireEvent.change(input, { target: { value: text } })
    fireEvent.keyDown(input, { key: 'Enter' })
  }

  it('未编辑时只展示内容，没有助手也没有 AI 按钮', () => {
    // 助手是编辑态的一部分:三个 AI 按钮摆在卡片头会让人以为"优化/扩写/聊天"是三件事
    setup()
    expect(screen.getByText('原来的故事')).toBeInTheDocument()
    expect(screen.queryByTestId('ai-input')).not.toBeInTheDocument()
    expect(screen.queryByText('AI 优化')).not.toBeInTheDocument()
  })

  it('编辑态是左右分栏：左编辑框 + 右助手', () => {
    setup()
    edit()
    expect(box()).toBeInTheDocument()
    expect(screen.getByTestId('ai-input')).toBeInTheDocument()
    expect(screen.getByTestId('ai-dialogue')).toBeInTheDocument()
  })

  it('apply 结果直接填进左侧编辑框 —— 编辑框本身就是预览', async () => {
    // 不再弹独立预览窗:那样"采纳"之后想再改一个字还得重新进编辑
    const { onSave } = setup()
    edit()
    vi.mocked(storyTextApi.revise).mockResolvedValue(APPLY)
    say('帮我优化')
    await waitFor(() => expect(box().value).toBe('改写后的故事'))
    expect(onSave).not.toHaveBeenCalled()      // 仍未落库,要点「保存」
  })

  it('点「保存」才落库', async () => {
    const { onSave } = setup()
    edit()
    vi.mocked(storyTextApi.revise).mockResolvedValue(APPLY)
    say('帮我优化')
    await waitFor(() => expect(box().value).toBe('改写后的故事'))
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('改写后的故事'))
  })

  it('ask 不动编辑框，即使它带了 text —— 只认 action，不猜', async () => {
    // LLM 输出不可信:后端已把"声称 ask 却带 text"降级处理,前端也不能反过来相信 text。
    // 用 text 非空的 ask 做探针 —— 若前端按 `if (r.text)` 判断,用户的正文会被一段
    // 助手还在商量中的草稿覆盖掉。
    setup()
    edit()
    vi.mocked(storyTextApi.revise).mockResolvedValue(
      { ...ASK, text: '助手自作主张的草稿' })
    say('改一下')
    await waitFor(() => expect(screen.getByText(/你想怎么改/)).toBeInTheDocument())
    expect(box().value).toBe('原来的故事')
  })

  it('建议气泡只是替用户说第一句，之后仍可继续对话', async () => {
    setup()
    edit()
    vi.mocked(storyTextApi.revise).mockResolvedValue(ASK)
    fireEvent.click(screen.getByText(/帮我优化这段文字/))
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledTimes(1))
    say('再紧凑一点')
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledTimes(2))
  })

  it('对话历史逐轮累积 —— 确认-执行 agent 靠它判断用户是否已同意', async () => {
    setup()
    edit()
    vi.mocked(storyTextApi.revise).mockResolvedValue(ASK)
    say('改一下')
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledTimes(1))
    say('确认')
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledTimes(2))
    expect(vi.mocked(storyTextApi.revise).mock.calls[1][0].messages.length).toBeGreaterThan(1)
  })

  it('助手看到的是草稿，不是已落库的旧文本', async () => {
    // 用旧文本会让用户刚打的字被无视,他会以为助手没读到修改
    setup()
    edit()
    fireEvent.change(box(), { target: { value: '我改过的' } })
    vi.mocked(storyTextApi.revise).mockResolvedValue(ASK)
    say('接着改')
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledWith(
      expect.objectContaining({ text: '我改过的' })))
  })

  it('kind 透传给后端 —— 决定按散文体还是剧本格式改', async () => {
    setup({ kind: 'screenplay' })
    edit()
    vi.mocked(storyTextApi.revise).mockResolvedValue(ASK)
    say('改')
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'screenplay' })))
  })

  it('文本为空也能进编辑并使用助手 —— 这正是"只有一个想法"的场景', () => {
    setup({ text: '' })
    edit()
    expect(screen.getByTestId('ai-input')).toBeInTheDocument()
  })

  it('清空后不提交 —— 空正文会让下游分析/分镜无从下手', async () => {
    const { onSave } = setup()
    edit()
    fireEvent.change(box(), { target: { value: '   ' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
    expect(onSave).not.toHaveBeenCalled()
  })

  it('不可编辑时没有任何写入入口，只给锁定说明', () => {
    setup({ editable: false, lockedHint: '已开拍，如需调整请在剧本审核阶段改写' })
    expect(screen.queryByText('编辑')).not.toBeInTheDocument()
    expect(screen.getByText('已开拍，如需调整请在剧本审核阶段改写')).toBeInTheDocument()
  })

  it('改写失败在对话里显示原因，且不动编辑框', async () => {
    setup()
    edit()
    vi.mocked(storyTextApi.revise).mockRejectedValue(
      { response: { data: { detail: '模型不可用' } } })
    say('改')
    await waitFor(() => expect(screen.getByText(/模型不可用/)).toBeInTheDocument())
    expect(box().value).toBe('原来的故事')
  })

  // ── 附件 ────────────────────────────────────────────────────────────────

  const upload = (name: string, type: string) => {
    const file = new File(['x'], name, { type })
    fireEvent.change(screen.getByLabelText('上传附件'), { target: { files: [file] } })
  }

  it('附件即传即解析，并在多轮对话里复用', async () => {
    // 解析结果留在前端:用户上传一份资料后每轮都该带着它,不必重传
    setup()
    edit()
    vi.mocked(storyTextApi.parseAttachment).mockResolvedValue(
      { filename: '参考.txt', text: '别人的故事', data_url: null })
    upload('参考.txt', 'text/plain')
    await waitFor(() => expect(screen.getByText('参考.txt')).toBeInTheDocument())
    vi.mocked(storyTextApi.revise).mockResolvedValue(ASK)
    say('参考它改')
    await waitFor(() => expect(storyTextApi.revise).toHaveBeenCalledWith(
      expect.objectContaining({
        attachments: [expect.objectContaining({ filename: '参考.txt' })],
      })))
  })

  it('解析失败展示后端 detail（如不支持视频），不静默丢掉', async () => {
    setup()
    edit()
    vi.mocked(storyTextApi.parseAttachment).mockRejectedValue(
      { response: { data: { detail: '暂不支持视频：可以先截图上传' } } })
    upload('a.mp4', 'video/mp4')
    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith(
      expect.stringContaining('暂不支持视频')))
    expect(screen.queryByText('a.mp4')).not.toBeInTheDocument()
  })

  it('重开编辑清空对话与附件 —— 上一轮的上下文不该渗进新一轮', async () => {
    setup()
    edit()
    vi.mocked(storyTextApi.parseAttachment).mockResolvedValue(
      { filename: 'a.txt', text: 'x', data_url: null })
    upload('a.txt', 'text/plain')
    await waitFor(() => expect(screen.getByText('a.txt')).toBeInTheDocument())
    fireEvent.click(screen.getByText('取消'))
    edit()
    expect(screen.queryByText('a.txt')).not.toBeInTheDocument()
  })
})
