import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import './mocks'
import PageShell from '../components/PageShell'

describe('PageShell', () => {
  it('renders title, headerExtra (as header action), and children', () => {
    render(
      <MemoryRouter>
        <PageShell title="作品列表" description="管理项目" headerExtra={<button>新建项目</button>}>
          <div>body</div>
        </PageShell>
      </MemoryRouter>
    )
    expect(screen.getByText('作品列表')).toBeInTheDocument()
    expect(screen.getByText('新建项目')).toBeInTheDocument()
    expect(screen.getByText('body')).toBeInTheDocument()
  })
})
