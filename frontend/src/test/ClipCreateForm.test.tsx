/**
 * 直接生成表单。
 *
 * 判据集中在"界面说的与实际发生的是否一致":
 * - 模式选项若不随模型能力变,用户会选到平台不支持的组合
 * - edit 的比例/时长若可选,选了也不生效
 * - @ 里若列出没有 storage_key 的散片,点了才报错
 * - protocol/model 若拆错,开拍报 "Unknown video provider"(已踩过)
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import './mocks'
import ClipCreateForm from '../components/ClipCreateForm'
import { clipsApi, configApi, filesApi, assetsApi } from '../services/api'

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<any>('../services/api')
  return {
    ...actual,
    clipsApi: { create: vi.fn(), list: vi.fn() },
    configApi: { storageStatus: vi.fn() },
    filesApi: { listImages: vi.fn(), copyFromAsset: vi.fn(), uploadVideo: vi.fn() },
    assetsApi: { list: vi.fn() },
  }
})

const MODELS = [
  {
    value: 'seedance-2.5', label: 'Seedance 2.5', provider: '字节跳动',
    provider_id: 'seedance', model_id: 'seedance-2.5',
    resolutions: ['720p', '1080p'], default_resolution: '1080p',
    aspect_ratios: ['9:16', '16:9'], default_aspect_ratio: '9:16',
    min_duration: 4, max_duration: 30,
    max_reference_images: 30, max_reference_audios: 10,
    max_reference_videos: 10, supports_omni_task_type: true,
    forces_adaptive_ratio: true, supports_seed: true,
    supports_audio_reference: true, supports_timestamp_prompt: true,
    supports_standalone_audio: true, is_default: true,
  },
  {
    value: 'minimax', label: 'MiniMax H3', provider: 'MiniMax',
    provider_id: 'minimax', model_id: 'minimax',
    resolutions: ['768P'], default_resolution: '768P',
    aspect_ratios: ['9:16'], default_aspect_ratio: '9:16',
    min_duration: 4, max_duration: 15,
    max_reference_images: 9, max_reference_audios: 3,
    max_reference_videos: 0, supports_omni_task_type: false,
    forces_adaptive_ratio: false, supports_seed: false,
    supports_audio_reference: true, supports_timestamp_prompt: false,
    supports_standalone_audio: false, is_default: false,
  },
]

const CLIPS = [
  { id: 'c1', prompt: '第一支', status: 'completed', storage_key: 'clips/c1.mp4' },
  { id: 'c2', prompt: '没同步的', status: 'completed', storage_key: null },
]

function setup(props: any = {}) {
  return render(
    <ClipCreateForm
      projectId="p1"
      onCreated={props.onCreated || vi.fn()}
      models={MODELS as any}
      videoDefault="seedance-2.5"
      clips={props.clips || (CLIPS as any)}
      {...props}
    />
  )
}

beforeEach(() => {
  // mock.calls 会跨用例累积:上一条用例提交过 clipsApi.create 的话,不清空这里
  // 断言的就是上一条的调用记录而非本条的 —— 那类"看似断言了、实际断言错对象"
  // 的假阳性最难自查。
  vi.clearAllMocks()
  vi.mocked(configApi.storageStatus).mockResolvedValue({ available: true })
  vi.mocked(assetsApi.list).mockResolvedValue([
    { id: 'a1', name: '素材图', category: 'character', url: '/api/assets/file/a1.png' },
  ] as any)
  vi.mocked(filesApi.listImages).mockResolvedValue([
    { name: 'ref1.png', url: '/api/projects/p1/images/reference/ref1.png' },
  ] as any)
  vi.mocked(clipsApi.create).mockResolvedValue({ id: 'new', prompt: 'x' } as any)
})

describe('ClipCreateForm 模式联动', () => {
  it('模型支持参考视频时,模式下拉含编辑与延长', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    const modeSelect = screen.getByTestId('configure-task_type')
    expect(modeSelect).toHaveTextContent('参考生成')
    await userEvent.click(modeSelect)
    expect(await screen.findByText('视频编辑')).toBeInTheDocument()
    expect(screen.getByText('视频延长')).toBeInTheDocument()
  })

  it('max_reference_videos=0 的模型不渲染编辑与延长', async () => {
    setup({ videoDefault: 'minimax' })
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('configure-task_type'))
    expect(screen.queryByText('视频编辑')).not.toBeInTheDocument()
    expect(screen.queryByText('视频延长')).not.toBeInTheDocument()
  })

  it('存储不可用时禁用编辑与延长并说明原因', async () => {
    vi.mocked(configApi.storageStatus).mockResolvedValue({ available: false })
    setup()
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    expect(screen.getByText(/需先配置对象存储/)).toBeInTheDocument()
  })

  it('存储状态接口失败时,按不可用处理:禁用编辑与延长并说明原因', async () => {
    vi.mocked(configApi.storageStatus).mockRejectedValue(new Error('network error'))
    setup()
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    expect(screen.getByText(/需先配置对象存储/)).toBeInTheDocument()
  })

  it('存储不可用时,编辑与延长选项不可点击', async () => {
    // 判据:仅有提示文案不够 —— 文案在、选项却能点中并选上,
    // 用户仍会提交一个不可能工作的模式。
    vi.mocked(configApi.storageStatus).mockResolvedValue({ available: false })
    setup()
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('configure-task_type'))
    expect(await screen.findByText('视频编辑')).toBeDisabled()
    expect(screen.getByText('视频延长')).toBeDisabled()
  })

  it('未配凭证的视频模型在下拉里禁用,并提示未配置凭证', async () => {
    // 选中一个没凭证的模型会一路跑到流水线全失败才报一条与
    // "没配 key" 无关的 "Connection error."。禁用该选项,而不是等报错才发现。
    setup({
      models: [
        ...MODELS.map(m => ({ ...m, credential_configured: true })),
        { ...MODELS[0], value: 'no-cred', label: '无凭证模型', credential_configured: false },
      ] as any,
    })
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('configure-video_provider'))
    const opt = await screen.findByText(/无凭证模型.*未配置凭证/)
    expect(opt).toBeDisabled()
  })
})

describe('ClipCreateForm @ 引用', () => {
  it('只列有 storage_key 的散片', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    expect(screen.getByText(/第一支/)).toBeInTheDocument()
    expect(screen.queryByText(/没同步的/)).not.toBeInTheDocument()
  })

  it('素材库的项选中后走 copyFromAsset,不直接用素材 url', async () => {
    vi.mocked(filesApi.copyFromAsset).mockResolvedValue(
      { url: '/api/projects/p1/images/reference/copied.png' } as any)
    setup()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    await userEvent.click(screen.getByText(/素材图/))
    await waitFor(() => expect(filesApi.copyFromAsset).toHaveBeenCalled())
  })
})

describe('ClipCreateForm 提交', () => {
  it('提交体带 task_type、video_refs 与正确拆分的 provider/model', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    // 选一支散片作参考视频
    await userEvent.click(screen.getByText(/第一支/))
    // 切到延长
    await userEvent.click(screen.getByTestId('configure-task_type'))
    await userEvent.click(await screen.findByText('视频延长'))

    const input = screen.getByPlaceholderText(/描述/)
    await userEvent.type(input, '向后延长 @video1{Enter}')

    await waitFor(() => expect(clipsApi.create).toHaveBeenCalled())
    const [, body] = vi.mocked(clipsApi.create).mock.calls[0] as any
    expect(body.task_type).toBe('extend')
    expect(body.video_refs).toEqual([{ url: 'clips/c1.mp4', subject_name: null }])
    // protocol 与 model 分开下发:填错会让开拍报 Unknown video provider
    expect(body.video_provider).toBe('seedance')
    expect(body.video_model).toBe('seedance-2.5')
  })

  it('选编辑时提交 duration=-1', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    await userEvent.click(screen.getByText(/第一支/))
    await userEvent.click(screen.getByTestId('configure-task_type'))
    await userEvent.click(await screen.findByText('视频编辑'))

    await userEvent.type(screen.getByPlaceholderText(/描述/), '把 @video1 的天空换成夜空{Enter}')
    await waitFor(() => expect(clipsApi.create).toHaveBeenCalled())
    const [, body] = vi.mocked(clipsApi.create).mock.calls[0] as any
    expect(body.duration).toBe(-1)
  })

  it('prompt 为空不提交', async () => {
    setup()
    await waitFor(() => expect(screen.getByTestId('skill-panel')).toBeInTheDocument())
    await userEvent.type(screen.getByPlaceholderText(/描述/), '{Enter}')
    expect(clipsApi.create).not.toHaveBeenCalled()
  })

  it('选视频编辑时,比例与时长两项都禁用', async () => {
    // 判据:界面让用户选、而实际由平台决定 —— 选了不生效正是
    // "界面说的与实际发生的不一致"。
    setup()
    await waitFor(() => expect(screen.getByTestId('configure-area')).toBeInTheDocument())
    await userEvent.click(screen.getByTestId('configure-task_type'))
    await userEvent.click(await screen.findByText('视频编辑'))
    expect(screen.getByTestId('configure-aspect_ratio')).toBeDisabled()
    expect(screen.getByTestId('configure-duration')).toBeDisabled()
  })
})
