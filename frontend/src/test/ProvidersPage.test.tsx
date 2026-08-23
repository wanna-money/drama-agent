import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  providersApi: {
    list: vi.fn(),
    get: vi.fn(),
    protocols: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}))

import ProvidersPage from '../pages/ProvidersPage'
import { providersApi } from '../services/api'
import { Toast } from '@douyinfe/semi-ui'

const builtinKimi = {
  provider_id: 'kimi', label: 'Kimi', kind: 'llm', protocol: 'openai-compat',
  base_url: 'https://api.moonshot.cn/v1', api_key: null,
  models: [{ id: 'kimi-k2-0711-preview', label: 'Kimi K2', kind: 'llm' }],
  builtin: true, enabled: true,
}
const customCorp = {
  provider_id: 'mycorp', label: '私有部署', kind: 'llm', protocol: 'openai-compat',
  base_url: 'https://x/v1', api_key: '***1234',
  models: [{ id: 'qwen-max', label: 'Qwen Max', kind: 'llm' }],
  builtin: false, enabled: true,
}
const builtinSeed = {
  provider_id: 'seedance-video', label: '字节跳动', kind: 'video', protocol: 'seedance',
  base_url: null, api_key: null,
  models: [{ id: 'seedance', label: 'Seedance 2.0', kind: 'video', resolutions: ['720p', '1080p'] }],
  builtin: true, enabled: true,
}
const builtinGptImage = {
  provider_id: 'gpt-image', label: 'OpenAI 图片', kind: 'image', protocol: 'openai-image',
  base_url: null, api_key: null,
  models: [{ id: 'gpt-image-2', label: 'GPT Image 2', kind: 'image' }],
  builtin: true, enabled: false,
}

const renderPage = () => render(<MemoryRouter><ProvidersPage /></MemoryRouter>)

describe('ProvidersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(providersApi.list).mockResolvedValue([builtinKimi, customCorp, builtinSeed, builtinGptImage] as any)
    vi.mocked(providersApi.protocols).mockResolvedValue({
      llm: ['openai-compat'], video: ['seedance', 'minimax'], image: ['openai-image', 'doubao-image'],
    })
  })

  it('groups by kind; all rows editable, builtin marked and not deletable', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('文本模型 (LLM)')).toBeInTheDocument())
    expect(screen.getByText('视频模型 (Video)')).toBeInTheDocument()
    expect(screen.getByText('图片模型 (Image)')).toBeInTheDocument()
    // 内置有「内置」标(kimi + seedance + gpt-image = 3 个),不再是「只读」
    expect(screen.getAllByText('内置').length).toBeGreaterThanOrEqual(3)
    expect(screen.queryByText('内置 · 只读')).not.toBeInTheDocument()
    // 所有 provider(含内置)都有「编辑」按钮(4 个)
    expect(screen.getAllByText('编辑').length).toBe(4)
    // key 掩码显示
    expect(screen.getByText('私有部署')).toBeInTheDocument()
  })

  it('marks disabled provider with 未启用 tag; enabled ones unmarked', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('图片模型 (Image)')).toBeInTheDocument())
    expect(screen.getAllByText('未启用').length).toBe(1)
  })

  it('opens create modal and validates empty provider_id', async () => {
    renderPage()
    await waitFor(() => screen.getByText('新增 Provider'))
    fireEvent.click(screen.getByText('新增 Provider'))
    await waitFor(() => expect(screen.getByPlaceholderText('如 mycorp')).toBeInTheDocument())
    // 直接保存(空 id)→ 校验拦截
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
    expect(providersApi.create).not.toHaveBeenCalled()
  })

  it('creates a provider with filled fields', async () => {
    vi.mocked(providersApi.create).mockResolvedValue(customCorp as any)
    renderPage()
    await waitFor(() => screen.getByText('新增 Provider'))
    fireEvent.click(screen.getByText('新增 Provider'))
    await waitFor(() => screen.getByPlaceholderText('如 mycorp'))
    fireEvent.change(screen.getByPlaceholderText('如 mycorp'), { target: { value: 'newcorp' } })
    fireEvent.change(screen.getByPlaceholderText('如 私有部署'), { target: { value: '新私有' } })
    fireEvent.change(screen.getByPlaceholderText('模型 ID (如 qwen-max)'), { target: { value: 'm1' } })
    fireEvent.change(screen.getByPlaceholderText('显示名'), { target: { value: 'M1' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(providersApi.create).toHaveBeenCalledOnce())
    const arg = vi.mocked(providersApi.create).mock.calls[0][0]
    expect(arg.provider_id).toBe('newcorp')
    expect(arg.models[0].id).toBe('m1')
    // 未填单价 → cost 不落值(未定价)
    expect(arg.models[0].cost ?? null).toBeNull()
  })

  it('submits per-model cost when 单价 filled; unpriced model keeps cost null', async () => {
    vi.mocked(providersApi.create).mockResolvedValue(customCorp as any)
    renderPage()
    await waitFor(() => screen.getByText('新增 Provider'))
    fireEvent.click(screen.getByText('新增 Provider'))
    await waitFor(() => screen.getByPlaceholderText('如 mycorp'))
    fireEvent.change(screen.getByPlaceholderText('如 mycorp'), { target: { value: 'pricecorp' } })
    fireEvent.change(screen.getByPlaceholderText('如 私有部署'), { target: { value: '定价' } })
    fireEvent.change(screen.getByPlaceholderText('模型 ID (如 qwen-max)'), { target: { value: 'm1' } })
    fireEvent.change(screen.getByPlaceholderText('显示名'), { target: { value: 'M1' } })
    // LLM kind 下有 输入/输出/每次调用 三个单价输入(InputNumber,min=0)
    const costInputs = Array.from(
      document.querySelectorAll<HTMLInputElement>('input[type="number"][min="0"]')
    )
    expect(costInputs.length).toBe(3)
    fireEvent.change(costInputs[0], { target: { value: '4' } })
    fireEvent.change(costInputs[1], { target: { value: '16' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(providersApi.create).toHaveBeenCalledOnce())
    const arg = vi.mocked(providersApi.create).mock.calls[0][0]
    expect(arg.models[0].cost).toMatchObject({ input: 4, output: 16 })
  })

  it('prefills existing model cost when editing', async () => {
    vi.mocked(providersApi.get).mockResolvedValue({
      ...customCorp,
      api_key: 'sk-real',
      models: [{ id: 'qwen-max', label: 'Qwen Max', kind: 'llm', cost: { input: 2.4, output: 9.6 } }],
    } as any)
    vi.mocked(providersApi.update).mockResolvedValue(customCorp as any)
    renderPage()
    await waitFor(() => expect(screen.getAllByText('编辑').length).toBe(4))
    fireEvent.click(screen.getAllByText('编辑')[1])
    await waitFor(() => expect(screen.getByDisplayValue('qwen-max')).toBeInTheDocument())
    expect(screen.getByDisplayValue('2.4')).toBeInTheDocument()
    expect(screen.getByDisplayValue('9.6')).toBeInTheDocument()
    // 回填的单价随更新原样提交
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(providersApi.update).toHaveBeenCalledOnce())
    const arg = vi.mocked(providersApi.update).mock.calls[0][1]
    expect(arg.models[0].cost).toMatchObject({ input: 2.4, output: 9.6 })
  })

  it('marking a model default unmarks others in the same provider', async () => {
    vi.mocked(providersApi.list).mockResolvedValue([])
    renderPage()
    await waitFor(() => screen.getByText('新增 Provider'))
    fireEvent.click(screen.getByText('新增 Provider'))
    await waitFor(() => screen.getByText('加一个模型'))
    fireEvent.click(screen.getByText('加一个模型'))
    const checks = screen.getAllByText('设为默认')
    expect(checks.length).toBe(2)
    fireEvent.click(checks[0])
    fireEvent.click(checks[1])
    const boxes = screen.getAllByText('设为默认')
      .map(el => el.closest('label')?.querySelector('input[type="checkbox"]') as HTMLInputElement)
    expect(boxes.every(Boolean)).toBe(true)
    expect(boxes.filter(b => b.checked).length).toBe(1)
    expect(boxes[1].checked).toBe(true)
  })

  it('shows a 默认 tag for the default model in the list', async () => {
    vi.mocked(providersApi.list).mockResolvedValue([{
      provider_id: 'acme', label: 'Acme', kind: 'llm', protocol: 'openai-compat',
      base_url: 'https://x/v1', api_key: null,
      models: [
        { id: 'm1', label: 'M1', kind: 'llm' },
        { id: 'm2', label: 'M2', kind: 'llm', is_default: true },
      ],
      builtin: false, enabled: true,
    }] as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('默认')).toBeInTheDocument())
  })
})
