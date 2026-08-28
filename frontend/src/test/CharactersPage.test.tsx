import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import './mocks'

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'p-1' }),
  useNavigate: () => vi.fn(),
}))

vi.mock('../services/api', () => ({
  projectsApi: {
    get: vi.fn(),
  },
  charactersApi: {
    list: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    listLooks: vi.fn(),
    createLook: vi.fn(),
    removeLook: vi.fn(),
    uploadView: vi.fn(),
    generateSheet: vi.fn(),
    saveGeneratedViews: vi.fn(),
    importFromAsset: vi.fn(),
    uploadVoice: vi.fn(),
    deleteVoice: vi.fn(),
  },
  configApi: {
    listImageModels: vi.fn(),
  },
  assetsApi: {
    list: vi.fn(),
  },
}))

import CharactersPage from '../pages/CharactersPage'
import { charactersApi, configApi, assetsApi, projectsApi } from '../services/api'
import { Toast, Modal } from '@douyinfe/semi-ui'

const character = { id: 'c-1', project_id: 'p-1', name: '林夏', description: '女主,短发' }
const look = {
  id: 'l-1', character_id: 'c-1', name: '日常装', is_default: true,
  front_key: 'k-front', side_key: null, back_key: null,
}

describe('CharactersPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(projectsApi.get).mockResolvedValue({ id: 'p-1', title: '测试作品' } as any)
    vi.mocked(configApi.listImageModels).mockResolvedValue({
      models: [
        { value: 'img-other', label: 'Other', provider: 'volcengine' },
        { value: 'seedream-4-0', label: 'Seedream 4.0', provider: 'volcengine' },
      ],
      default: 'seedream-4-0',
    })
  })

  it('lists the project characters and their looks on mount', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    render(<CharactersPage />)
    await waitFor(() => expect(screen.getByText('林夏')).toBeInTheDocument())
    expect(charactersApi.list).toHaveBeenCalledWith('p-1')
    await waitFor(() => expect(screen.getByText('日常装')).toBeInTheDocument())
    expect(charactersApi.listLooks).toHaveBeenCalledWith('p-1', 'c-1')
  })

  it('shows an empty state when the project has no characters', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([])
    render(<CharactersPage />)
    await waitFor(() => expect(screen.getByText('还没有角色')).toBeInTheDocument())
    expect(charactersApi.listLooks).not.toHaveBeenCalled()
  })

  it('creates a character with the project id from the route', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([])
    vi.mocked(charactersApi.create).mockResolvedValue(character)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('还没有角色'))

    fireEvent.click(screen.getByText('新建角色'))
    fireEvent.change(screen.getByPlaceholderText('如 林夏'), { target: { value: '陆沉' } })
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => expect(charactersApi.create).toHaveBeenCalledWith(
      'p-1', expect.objectContaining({ name: '陆沉' })
    ))
  })

  it('blocks character creation when the name is blank', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([])
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('还没有角色'))

    fireEvent.click(screen.getByText('新建角色'))
    fireEvent.click(screen.getByText('保存'))

    await waitFor(() => expect(Toast.error).toHaveBeenCalled())
    expect(charactersApi.create).not.toHaveBeenCalled()
  })

  it('generates the four views, previews them, then persists them', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(charactersApi.generateSheet).mockResolvedValue({
      sheet_b64: 'U0hFRVQ=',
      views: { front: 'RkZG', side: 'U1NT', back: 'QkJC', face: 'Q0ND' },
    })
    vi.mocked(charactersApi.saveGeneratedViews).mockResolvedValue(look)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))

    fireEvent.click(screen.getByText('AI 生成四视图'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())

    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(charactersApi.generateSheet).toHaveBeenCalledWith(
      'p-1', 'c-1', 'l-1', expect.objectContaining({ model_id: 'seedream-4-0' })
    ))

    await waitFor(() => expect(screen.getByAltText('正面预览')).toBeInTheDocument())
    expect(screen.getByAltText('侧面预览')).toBeInTheDocument()
    expect(screen.getByAltText('背面预览')).toBeInTheDocument()
    expect(screen.getByAltText('面部特写预览')).toBeInTheDocument()

    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(charactersApi.saveGeneratedViews).toHaveBeenCalledWith(
      'p-1', 'c-1', 'l-1',
      { front_b64: 'RkZG', side_b64: 'U1NT', back_b64: 'QkJC', face_b64: 'Q0ND' }
    ))
  })

  it('saves four views including face', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(charactersApi.generateSheet).mockResolvedValue({
      sheet_b64: 'U0hFRVQ=',
      views: { front: 'F', side: 'S', back: 'B', face: 'C' },
    })
    vi.mocked(charactersApi.saveGeneratedViews).mockResolvedValue(look)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))

    fireEvent.click(screen.getByText('AI 生成四视图'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())

    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(charactersApi.generateSheet).toHaveBeenCalled())

    fireEvent.click(screen.getByText('保存'))
    await waitFor(() => expect(charactersApi.saveGeneratedViews).toHaveBeenCalledWith(
      expect.anything(), expect.anything(), expect.anything(),
      expect.objectContaining({ face_b64: 'C' })
    ))
  })

  it('surfaces the backend detail when generation fails', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(charactersApi.generateSheet).mockRejectedValue({
      response: { data: { detail: '当前图片模型不支持生成' } },
    })
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))

    fireEvent.click(screen.getByText('AI 生成四视图'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('生成'))

    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith('生成失败: 当前图片模型不支持生成'))
    expect(screen.queryByAltText('正面预览')).not.toBeInTheDocument()
  })

  it('confirms before deleting a character and reloads after success', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([])
    vi.mocked(charactersApi.remove).mockResolvedValue(undefined)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('林夏'))

    fireEvent.click(screen.getAllByText('×')[0])
    expect(Modal.confirm).toHaveBeenCalledOnce()
    const opts = (Modal as any)._lastConfirm.current
    expect(opts.content).toContain('林夏')
    await opts.onOk()
    expect(charactersApi.remove).toHaveBeenCalledWith('p-1', 'c-1')
    expect(Toast.success).toHaveBeenCalledWith('已删除')
  })

  it('imports a character asset into a look', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(assetsApi.list).mockResolvedValue([
      { id: 'as-1', category: 'character', name: '林夏预设', description: '', url: '/x', size_bytes: 1 },
    ] as any)
    vi.mocked(charactersApi.importFromAsset).mockResolvedValue({
      id: 'l-1', character_id: 'c-1', name: '日常装', is_default: true,
      front_key: 'f', side_key: 's', back_key: 'b', face_key: 'c',
    } as any)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))

    fireEvent.click(screen.getByText('从素材库导入'))
    await waitFor(() => expect(assetsApi.list).toHaveBeenCalledWith('character'))
    await waitFor(() => expect(screen.getByText('林夏预设')).toBeInTheDocument())

    fireEvent.click(screen.getByText('选它'))
    await waitFor(() => expect(charactersApi.importFromAsset).toHaveBeenCalledWith(
      expect.anything(), expect.anything(), expect.anything(), 'as-1'
    ))
  })

  // ── 人工裁切(自动识别留白分界失败时的出口) ────────────────────────────────

  it('生成后自动裁切失败(views=null)转人工裁切,不让用户重烧一次生成', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(charactersApi.generateSheet).mockResolvedValue({
      sheet_b64: 'U0hFRVQ=', views: null,
    })
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))

    fireEvent.click(screen.getByText('AI 生成四视图'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('生成'))

    // 裁切器打开、底图是后端回传的 sheet 原图(而不是报错把生成结果丢掉)
    await waitFor(() => expect(screen.getByTestId('cropper')).toBeInTheDocument())
    expect(screen.getByTestId('cropper')).toHaveAttribute(
      'data-src', 'data:image/png;base64,U0hFRVQ=')
    expect(Toast.warning).toHaveBeenCalled()
  })

  it('人工裁切四张后落库,复用 views-from-generated 端点', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(charactersApi.generateSheet).mockResolvedValue({
      sheet_b64: 'U0hFRVQ=', views: null,
    })
    vi.mocked(charactersApi.saveGeneratedViews).mockResolvedValue(look)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))
    fireEvent.click(screen.getByText('AI 生成四视图'))
    await waitFor(() => expect(configApi.listImageModels).toHaveBeenCalled())
    fireEvent.click(screen.getByText('生成'))
    await waitFor(() => expect(screen.getByTestId('cropper')).toBeInTheDocument())

    // 逐张确认:正面 → 侧面 → 背面 → 面部特写(最后一步才提交)
    fireEvent.click(screen.getByText('确认正面，下一张'))
    fireEvent.click(screen.getByText('确认侧面，下一张'))
    fireEvent.click(screen.getByText('确认背面，下一张'))
    expect(charactersApi.saveGeneratedViews).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('完成并保存'))

    const expected = 'CROP(data:image/png;base64,U0hFRVQ=)'
    await waitFor(() => expect(charactersApi.saveGeneratedViews).toHaveBeenCalledWith(
      'p-1', 'c-1', 'l-1',
      { front_b64: expected, side_b64: expected, back_b64: expected, face_b64: expected }
    ))
    expect(Toast.success).toHaveBeenCalledWith('已保存四视图')
  })

  it('从素材库导入收到 422(切不开)转人工裁切,用素材原图当底图', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(assetsApi.list).mockResolvedValue([
      { id: 'as-1', category: 'character', name: '林夏预设', description: '', url: '/assets/x.png', size_bytes: 1 },
    ] as any)
    vi.mocked(charactersApi.importFromAsset).mockRejectedValue({
      response: { status: 422, data: { detail: '未能自动识别四视图分界' } },
    })
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))

    fireEvent.click(screen.getByText('从素材库导入'))
    await waitFor(() => expect(screen.getByText('林夏预设')).toBeInTheDocument())
    fireEvent.click(screen.getByText('选它'))

    await waitFor(() => expect(screen.getByTestId('cropper')).toBeInTheDocument())
    expect(screen.getByTestId('cropper')).toHaveAttribute('data-src', '/assets/x.png')
  })

  it('从素材库导入的 404(素材不存在)只报错,不弹裁切器', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([character])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([look])
    vi.mocked(assetsApi.list).mockResolvedValue([
      { id: 'as-1', category: 'character', name: '林夏预设', description: '', url: '/x', size_bytes: 1 },
    ] as any)
    vi.mocked(charactersApi.importFromAsset).mockRejectedValue({
      response: { status: 404, data: { detail: '素材不存在' } },
    })
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('日常装'))
    fireEvent.click(screen.getByText('从素材库导入'))
    await waitFor(() => expect(screen.getByText('林夏预设')).toBeInTheDocument())
    fireEvent.click(screen.getByText('选它'))

    await waitFor(() => expect(Toast.error).toHaveBeenCalledWith('导入失败: 素材不存在'))
    expect(screen.queryByTestId('cropper')).not.toBeInTheDocument()
  })

  it('shows breadcrumb 作品列表 › 项目名 › 角色', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([])
    vi.mocked(projectsApi.get).mockResolvedValue({ id: 'p-1', title: '测试作品' } as any)
    render(<CharactersPage />)
    await waitFor(() => expect(screen.getByText('作品列表')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('测试作品')).toBeInTheDocument())
    expect(projectsApi.get).toHaveBeenCalledWith('p-1')
  })

  it('uploads a voice sample for a character', async () => {
    vi.mocked(charactersApi.list).mockResolvedValue([
      { id: 'c-1', project_id: 'p-1', name: '林夏', voice_key: null } as any,
    ])
    vi.mocked(charactersApi.listLooks).mockResolvedValue([])
    vi.mocked(charactersApi.uploadVoice).mockResolvedValue(
      { id: 'c-1', project_id: 'p-1', name: '林夏', voice_key: 'v.wav' } as any)
    render(<CharactersPage />)
    await waitFor(() => screen.getByText('林夏'))
    const file = new File([new Uint8Array([1, 2, 3])], 'v.wav', { type: 'audio/wav' })
    const input = document.querySelector('input[type="file"][accept="audio/*"]') as HTMLInputElement
    fireEvent.change(input, { target: { files: [file] } })
    await waitFor(() => expect(charactersApi.uploadVoice).toHaveBeenCalledWith('p-1', 'c-1', file))
  })
})
