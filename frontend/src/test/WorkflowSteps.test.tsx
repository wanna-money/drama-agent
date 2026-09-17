import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@douyinfe/semi-ui', () => ({
  Typography: {
    Text: ({ children, type }: any) => <span data-type={type}>{children}</span>,
  },
}))
vi.mock('@douyinfe/semi-icons', () => ({
  IconTickCircle: () => <i data-icon="finish" />,
  IconAlertTriangle: () => <i data-icon="warning" />,
  IconClose: () => <i data-icon="error" />,
}))

import WorkflowSteps from '../components/WorkflowSteps'

describe('WorkflowSteps', () => {
  it('renders finish/process/warning/error/wait states with distinct markers', () => {
    render(
      <WorkflowSteps
        items={[
          { key: 'a', label: '故事分析', status: 'finish' },
          { key: 'b', label: '分镜', status: 'warning', onClick: () => {} },
          { key: 'c', label: '造型指派', status: 'process', onClick: () => {} },
          { key: 'd', label: '视频生成', status: 'error' },
          { key: 'e', label: '完成', status: undefined },
        ]}
      />
    )
    const items = screen.getAllByRole('listitem')
    expect(items).toHaveLength(5)
    expect(items[0]).toHaveAttribute('data-status', 'finish')
    expect(items[1]).toHaveAttribute('data-status', 'warning')
    expect(items[2]).toHaveAttribute('data-status', 'process')
    expect(items[3]).toHaveAttribute('data-status', 'error')
    expect(items[4]).toHaveAttribute('data-status', 'wait')
    expect(screen.getByText('待审核')).toBeInTheDocument()
    expect(screen.getByText('失败')).toBeInTheDocument()
  })

  it('does not attach onClick and marks data-clickable=false when onClick is absent', () => {
    const onClick = vi.fn()
    render(<WorkflowSteps items={[{ key: 'a', label: '未到达步骤', status: undefined }]} />)
    const item = screen.getByRole('listitem')
    expect(item).toHaveAttribute('data-clickable', 'false')
    fireEvent.click(item)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('invokes onClick when the step is clickable', () => {
    const onClick = vi.fn()
    render(<WorkflowSteps items={[{ key: 'a', label: '分镜', status: 'process', onClick }]} />)
    fireEvent.click(screen.getByRole('listitem'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('shows cost description when provided', () => {
    render(<WorkflowSteps items={[{ key: 'a', label: '剧本', description: '¥8.40', status: 'finish' }]} />)
    expect(screen.getByText('¥8.40')).toBeInTheDocument()
  })
})
