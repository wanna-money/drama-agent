import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import './mocks'

vi.mock('../services/api', () => ({
  filesApi: { uploadImage: vi.fn(), copyFromAsset: vi.fn(), listImages: vi.fn() },
  assetsApi: { list: vi.fn() },
}))

import ImagePicker from '../components/ImagePicker'
import { filesApi, assetsApi } from '../services/api'

const PID = 'p1'
const RESULT = { path: 'a.png', filename: 'a.png', type: 'reference',
                 url: '/api/projects/p1/images/reference/a.png' }

describe('ImagePicker', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(assetsApi.list).mockResolvedValue([
      { id: 'as-1', category: 'background', name: '雪山', url: '/api/assets/f/x.png',
        size_bytes: 1 } as any,
    ])
    vi.mocked(filesApi.listImages).mockResolvedValue([
      { filename: 'old.png', url: '/api/projects/p1/images/reference/old.png',
        size_bytes: 2, type: 'reference' },
    ])
    vi.mocked(filesApi.uploadImage).mockResolvedValue(RESULT as any)
    vi.mocked(filesApi.copyFromAsset).mockResolvedValue(RESULT as any)
  })

  const open = (onPick = vi.fn()) => {
    render(<ImagePicker projectId={PID} visible onClose={vi.fn()} onPick={onPick} />)
    return onPick
  }

  it('上传后回传服务端 url', async () => {
    const onPick = open()
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    // Upload mock 渲染的是 <input type="file">,用 querySelector 取
    const fileInput = screen.getByTestId('tabpane-upload')
      .querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(fileInput, { target: { files: [file] } })
    await waitFor(() => expect(filesApi.uploadImage).toHaveBeenCalledWith(PID, file, 'reference'))
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(RESULT.url))
  })

  it('从素材库选:先拷贝进本项目,再回传拷贝后的 url', async () => {
    // 直接回素材库的 url 会让散片依赖素材库那张图 —— 之后它被改/删,重跑就复现不出原样
    const onPick = open()
    await waitFor(() => expect(assetsApi.list).toHaveBeenCalled())
    fireEvent.click(within(screen.getByTestId('tabpane-library')).getByText('使用'))
    await waitFor(() =>
      expect(filesApi.copyFromAsset).toHaveBeenCalledWith(PID, 'as-1', 'reference'))
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(RESULT.url))
  })

  it('本项目已有:直接回传该图 url,不再拷贝一次', async () => {
    const onPick = open()
    await waitFor(() => expect(filesApi.listImages).toHaveBeenCalledWith(PID))
    fireEvent.click(within(screen.getByTestId('tabpane-existing')).getByAltText('old.png'))
    await waitFor(() =>
      expect(onPick).toHaveBeenCalledWith('/api/projects/p1/images/reference/old.png'))
    expect(filesApi.copyFromAsset).not.toHaveBeenCalled()
    expect(filesApi.uploadImage).not.toHaveBeenCalled()
  })

  it('visible=false 时不渲染', () => {
    render(<ImagePicker projectId={PID} visible={false} onClose={vi.fn()} onPick={vi.fn()} />)
    expect(screen.queryByTestId('modal')).toBeNull()
  })
})
