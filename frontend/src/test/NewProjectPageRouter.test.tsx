import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import './mocks'

// 只 mock API，不 mock react-router：用真实 Data Router 驱动，
// 复现 useBlocker 在非 Data Router 下渲染即抛错的白屏 bug（回归守卫）。
vi.mock('../services/api', () => ({
  projectsApi: { create: vi.fn() },
}))

import NewProjectPage from '../pages/NewProjectPage'

describe('NewProjectPage under a data router', () => {
  beforeEach(() => vi.clearAllMocks())

  // 白屏根因：useBlocker 要求 Data Router。用 <BrowserRouter>/<MemoryRouter>
  // 这类非 Data Router 时，useBlocker 首行 useDataRouterContext 会 invariant 抛错，
  // 组件渲染即崩 → 整页白屏。createMemoryRouter 与生产的 createBrowserRouter 同一套
  // context 契约，能真实覆盖这条路径（现有 NewProjectPage.test.tsx 把 useBlocker mock 掉了，测不到）。
  it('renders without crashing (useBlocker resolves)', async () => {
    const router = createMemoryRouter(
      [{ path: '/new', element: <NewProjectPage /> }],
      { initialEntries: ['/new'] },
    )
    render(<RouterProvider router={router} />)
    await waitFor(() =>
      expect(screen.getByPlaceholderText('为你的短剧起一个名字')).toBeInTheDocument(),
    )
  })
})
