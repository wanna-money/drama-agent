import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

// 真实 @douyinfe/semi-ui 的 barrel 会拉进 lottie-web,在 jsdom 下 getContext 缺失即崩,
// 全仓测试统一 mock Semi(见 src/test/mocks.tsx)。此处只 mock PageHeader 用到的组件,
// 并让 Breadcrumb 渲染带 semi-breadcrumb class 的容器,以保留「不传 breadcrumb 就没有面包屑节点」的语义。
vi.mock('@douyinfe/semi-ui', () => ({
  Row: ({ children }: any) => <div>{children}</div>,
  Col: ({ children }: any) => <div>{children}</div>,
  Space: ({ children }: any) => <div>{children}</div>,
  Typography: {
    Title: ({ children }: any) => <h1>{children}</h1>,
    Text: ({ children }: any) => <span>{children}</span>,
  },
  Breadcrumb: Object.assign(
    ({ children }: any) => <nav className="semi-breadcrumb">{children}</nav>,
    {
      Item: ({ children, onClick }: any) => (
        <span className="semi-breadcrumb-item" onClick={onClick}>{children}</span>
      ),
    }
  ),
}))

import PageHeader from '../components/PageHeader'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const renderH = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('PageHeader', () => {
  it('renders breadcrumb items, title, and extra; breadcrumb link navigates', () => {
    renderH(
      <PageHeader
        breadcrumb={[{ label: '作品列表', href: '/' }, { label: '测试' }]}
        title="测试"
        description="共 0 集"
        extra={<button>新建一集</button>}
      />
    )
    expect(screen.getByText('作品列表')).toBeInTheDocument()
    expect(screen.getAllByText('测试').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('新建一集')).toBeInTheDocument()
    fireEvent.click(screen.getByText('作品列表'))
    expect(mockNavigate).toHaveBeenCalledWith('/')
  })

  it('does not navigate for breadcrumb items without href', () => {
    renderH(<PageHeader breadcrumb={[{ label: '当前页' }]} title="详情标题" />)
    mockNavigate.mockClear()
    fireEvent.click(screen.getByText('当前页'))
    expect(mockNavigate).not.toHaveBeenCalled()
  })

  it('omits breadcrumb when not provided', () => {
    const { container } = renderH(<PageHeader title="剧本库" />)
    expect(container.querySelector('.semi-breadcrumb')).toBeNull()
  })
})
