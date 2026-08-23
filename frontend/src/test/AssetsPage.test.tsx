import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import './mocks'

vi.mock('../services/api', () => ({
  assetsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    generate: vi.fn(),
    edit: vi.fn(),
    saveGenerated: vi.fn(),
  },
  configApi: {
    listImageModels: vi.fn(),
  },
  promptApi: {
    optimize: vi.fn(),
  },
}))

import AssetsPage from '../pages/AssetsPage'
import { assetsApi, configApi, promptApi } from '../services/api'
import { Toast, Modal } from '@douyinfe/semi-ui'

const asset = {
  id: 'a-1',
  category: 'character' as const,
  name: '女主-林夏',
  description: '短发,白衬衫',
  url: '/api/assets/file/abc',
  size_bytes: 1024,
}

describe('AssetsPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads all categories on mount (no category filter)', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([asset])
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('女主-林夏')).toBeInTheDocument())
    expect(assetsApi.list).toHaveBeenCalledWith(undefined)
    expect(screen.getByText('上传素材')).toBeInTheDocument()
  })

  it('refetches with the picked category when switching tabs', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([asset])
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('女主-林夏'))
    fireEvent.click(screen.getByText('道具'))
    await waitFor(() => expect(assetsApi.list).toHaveBeenLastCalledWith('prop'))
  })

  it('shows empty state when the category has no assets', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('还没有素材')).toBeInTheDocument())
  })

  it('confirms before deleting and reloads after success', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([asset])
    vi.mocked(assetsApi.delete).mockResolvedValue(undefined)
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('女主-林夏'))
    fireEvent.click(screen.getByText('×'))
    expect(Modal.confirm).toHaveBeenCalledOnce()
    const opts = (Modal as any)._lastConfirm.current
    expect(opts.content).toContain('女主-林夏')
    await opts.onOk()
    expect(assetsApi.delete).toHaveBeenCalledWith('a-1')
    expect(Toast.success).toHaveBeenCalledWith('已删除')
  })

  it('blocks create when no file is selected', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))
    fireEvent.click(screen.getByText('上传素材'))
    // category + name filled, but no file picked
    fireEvent.change(screen.getByPlaceholderText('如 女主-林夏'), { target: { value: '道具-手机' } })
    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
    expect(assetsApi.create).not.toHaveBeenCalled()
  })

  it('generates an image from a prompt and shows the preview', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    vi.mocked(assetsApi.generate).mockResolvedValue({ images: ['QUJD'] })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))

    fireEvent.click(screen.getByText('AI 生成'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())

    fireEvent.change(screen.getByPlaceholderText(/预填推荐描述/), { target: { value: '青衫侠客' } })
    fireEvent.click(screen.getByText('生成'))

    await waitFor(() => expect(assetsApi.generate).toHaveBeenCalledWith(
      expect.objectContaining({ model_id: 'seedream-4-0', prompt: '青衫侠客' })
    ))
    await waitFor(() => expect(screen.getByAltText('预览')).toBeInTheDocument())
  })

  it('preselects the default image model when opening AI generate', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [
        { value: 'img-a', label: 'A', provider: 'P' },
        { value: 'img-b', label: 'B', provider: 'P' },
      ],
      default: 'img-b',
    })
    vi.mocked(assetsApi.generate).mockResolvedValue({ images: ['QUJD'] })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))
    fireEvent.click(screen.getByText('AI 生成'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.change(screen.getByPlaceholderText(/预填推荐描述/), { target: { value: 'x' } })
    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(assetsApi.generate).toHaveBeenCalledWith(
      expect.objectContaining({ model_id: 'img-b' })
    ))
  })

  it('preselects the model default resolution as size and submits the composite model id', async () => {
    // 选中模型即带出其 default_resolution 作为尺寸;value 为 provider/id 复合值,原样透传为 model_id。
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{
        value: 'doubao-image/seedream', label: 'Seedream', provider: '豆包',
        resolutions: ['1024x1024', '1280x720'], default_resolution: '1024x1024',
      }],
      default: 'doubao-image/seedream',
    })
    vi.mocked(assetsApi.generate).mockResolvedValue({ images: ['QUJD'] })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))
    fireEvent.click(screen.getByText('AI 生成'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.change(screen.getByPlaceholderText(/预填推荐描述/), { target: { value: 'x' } })
    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(assetsApi.generate).toHaveBeenCalledWith(
      expect.objectContaining({ model_id: 'doubao-image/seedream', size: '1024x1024' })
    ))
  })

  it('blocks generation when the prompt is empty', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))

    fireEvent.click(screen.getByText('AI 生成'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('生成'))

    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
    expect(assetsApi.generate).not.toHaveBeenCalled()
  })

  it('surfaces the backend detail when edit is unsupported (501)', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([asset])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    vi.mocked(assetsApi.edit).mockRejectedValue({
      response: { data: { detail: '当前启用的图片模型均不支持编辑' } },
    })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('女主-林夏'))

    fireEvent.click(screen.getByText('编辑'))
    fireEvent.change(screen.getByPlaceholderText(/改成夜晚场景/), { target: { value: '改成夜晚' } })
    fireEvent.click(screen.getByText('AI 生成改图'))

    await waitFor(() => expect(assetsApi.edit).toHaveBeenCalledWith(
      expect.objectContaining({ asset_id: 'a-1', prompt: '改成夜晚' })
    ))
    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith('当前启用的图片模型均不支持编辑'))
    expect(screen.queryByAltText('改图预览')).not.toBeInTheDocument()
  })

  it('optimizes the generation prompt and generates with the expanded text', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    vi.mocked(promptApi.optimize).mockResolvedValue({ optimized: 'DETAILED' })
    vi.mocked(assetsApi.generate).mockResolvedValue({ images: ['QUJD'] })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))

    fireEvent.click(screen.getByText('AI 生成'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())

    fireEvent.change(screen.getByPlaceholderText(/预填推荐描述/), { target: { value: '青衫侠客' } })
    fireEvent.click(screen.getByText('✨ 优化描述'))

    await waitFor(() => expect(promptApi.optimize).toHaveBeenCalledWith(
      expect.objectContaining({ raw_prompt: '青衫侠客', kind: 'image' })
    ))
    // 写回后再点生成,用的是扩写后的文本
    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(assetsApi.generate).toHaveBeenCalledWith(
      expect.objectContaining({ prompt: 'DETAILED' })
    ))
  })

  it('does not call optimize when the prompt is empty', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('还没有素材'))

    fireEvent.click(screen.getByText('AI 生成'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('✨ 优化描述'))

    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
    expect(promptApi.optimize).not.toHaveBeenCalled()
  })

  it('keeps the raw prompt when optimize fails, so editing is not blocked', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([asset])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    vi.mocked(promptApi.optimize).mockRejectedValue(new Error('boom'))
    vi.mocked(assetsApi.edit).mockResolvedValue({ images: ['QUJD'] })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('女主-林夏'))

    fireEvent.click(screen.getByText('编辑'))
    fireEvent.change(screen.getByPlaceholderText(/改成夜晚场景/), { target: { value: '改成夜晚' } })
    fireEvent.click(screen.getByText('✨ 优化描述'))

    await waitFor(() => expect(promptApi.optimize).toHaveBeenCalledWith(
      expect.objectContaining({ raw_prompt: '改成夜晚', kind: 'image' })
    ))
    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith('优化失败'))

    fireEvent.click(screen.getByText('AI 生成改图'))
    await waitFor(() => expect(assetsApi.edit).toHaveBeenCalledWith(
      expect.objectContaining({ asset_id: 'a-1', prompt: '改成夜晚' })
    ))
  })

  it('optimizing a character asset passes subject=character', async () => {
    vi.mocked(assetsApi.list).mockResolvedValue([asset])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    vi.mocked(promptApi.optimize).mockResolvedValue({ optimized: 'OUT' })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('女主-林夏'))

    fireEvent.click(screen.getByText('编辑'))
    fireEvent.change(screen.getByPlaceholderText(/改成夜晚场景/), { target: { value: '优化我' } })
    fireEvent.click(screen.getByText('✨ 优化描述'))

    await waitFor(() => expect(promptApi.optimize).toHaveBeenCalledWith(
      expect.objectContaining({ raw_prompt: '优化我', subject: 'character' })
    ))
  })

  it('optimizing a non-character asset omits subject', async () => {
    const propAsset = { ...asset, id: 'a-2', category: 'prop' as const, name: '道具-手机' }
    vi.mocked(assetsApi.list).mockResolvedValue([propAsset])
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [{ value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' }],
      default: 'seedream-4-0',
    })
    vi.mocked(promptApi.optimize).mockResolvedValue({ optimized: 'OUT' })
    render(<MemoryRouter><AssetsPage /></MemoryRouter>)
    await waitFor(() => screen.getByText('道具-手机'))

    fireEvent.click(screen.getByText('编辑'))
    fireEvent.change(screen.getByPlaceholderText(/改成夜晚场景/), { target: { value: '优化我' } })
    fireEvent.click(screen.getByText('✨ 优化描述'))

    await waitFor(() => expect(promptApi.optimize).toHaveBeenCalled())
    expect(vi.mocked(promptApi.optimize).mock.calls[0][0].subject).toBeUndefined()
  })
})
