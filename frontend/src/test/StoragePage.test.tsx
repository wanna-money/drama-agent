/**
 * 存储管理页。
 *
 * 判据:凭证若被明文回显在列表里就是泄露;protocol 若能自由填,
 * 打错会静默变成"配了但没有任何后端认领"。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import './mocks'
import StoragePage from '../pages/StoragePage'
import { providersApi } from '../services/api'

const renderPage = () => render(<MemoryRouter><StoragePage /></MemoryRouter>)

vi.mock('../services/api', async () => {
  const actual = await vi.importActual<any>('../services/api')
  return {
    ...actual,
    providersApi: {
      list: vi.fn(),
      get: vi.fn(),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
      protocols: vi.fn(),
    },
  }
})

const COS_ROW = {
  provider_id: 'cos', label: '腾讯云 COS', kind: 'storage', protocol: 'cos',
  base_url: null, api_key: '***-key', models: [], paths: {}, response_map: {},
  config: { bucket: 'b-123', region: 'ap-beijing', secret_id: 'sid' },
  builtin: false, enabled: true,
}

beforeEach(() => {
  vi.mocked(providersApi.list).mockResolvedValue([
    COS_ROW,
    { ...COS_ROW, provider_id: 'kimi', kind: 'llm', protocol: 'openai-compat' },
  ] as any)
  vi.mocked(providersApi.protocols).mockResolvedValue({
    llm: ['openai-compat'], video: ['seedance'], image: [], storage: ['cos'],
    ops: {}, response_fields: {},
  } as any)
})

describe('StoragePage', () => {
  it('只列 kind=storage 的条目', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('腾讯云 COS')).toBeInTheDocument())
    expect(screen.queryByText('kimi')).not.toBeInTheDocument()
  })

  it('列表展示掩码后的凭证,不出现明文', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('***-key')).toBeInTheDocument())
    expect(screen.queryByText('secret-key')).not.toBeInTheDocument()
  })

  it('必填字段为空时不提交', async () => {
    renderPage()
    await waitFor(() => expect(screen.getByText('腾讯云 COS')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /新建/ }))

    await userEvent.type(screen.getByTestId('field-provider_id'), 'cos3')
    await userEvent.type(screen.getByTestId('field-label'), '备用桶3')
    // bucket/region/secret_id/api_key 留空
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))

    await waitFor(() => expect(screen.getByText('请输入 Bucket')).toBeInTheDocument())
    expect(providersApi.create).not.toHaveBeenCalled()
  })

  it('新建时提交 kind=storage 且 config 装 bucket 与 region', async () => {
    vi.mocked(providersApi.create).mockResolvedValue(COS_ROW as any)
    renderPage()
    await waitFor(() => expect(screen.getByText('腾讯云 COS')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: /新建/ }))

    await userEvent.type(screen.getByTestId('field-provider_id'), 'cos2')
    await userEvent.type(screen.getByTestId('field-label'), '备用桶')
    await userEvent.type(screen.getByTestId('field-bucket'), 'b-456')
    await userEvent.type(screen.getByTestId('field-region'), 'ap-shanghai')
    await userEvent.type(screen.getByTestId('field-secret_id'), 'sid2')
    await userEvent.type(screen.getByTestId('field-api_key'), 'skey2')
    await userEvent.click(screen.getByRole('button', { name: /保存/ }))

    await waitFor(() => expect(providersApi.create).toHaveBeenCalled())
    const body = vi.mocked(providersApi.create).mock.calls[0][0] as any
    expect(body.kind).toBe('storage')
    expect(body.protocol).toBe('cos')
    expect(body.models).toEqual([])
    expect(body.config).toMatchObject({
      bucket: 'b-456', region: 'ap-shanghai', secret_id: 'sid2',
    })
    // SecretKey 走 api_key 列(与 provider 凭证同一套 $ENV 解析与掩码)
    expect(body.api_key).toBe('skey2')
  })
})
