import React from 'react'
import { vi } from 'vitest'

// Minimal Semi UI mocks — enough for rendering and interaction tests
vi.mock('@douyinfe/semi-ui', () => ({
  Button: ({ children, onClick, disabled, icon, ...p }: any) => (
    <button onClick={onClick} disabled={disabled} data-testid={p['data-testid']}>{icon}{children}</button>
  ),
  Input: ({ value, onChange, placeholder, ...p }: any) => (
    <input value={value ?? ''} onChange={e => onChange?.(e.target.value)} placeholder={placeholder} aria-invalid={p['validateStatus'] === 'error'} />
  ),
  TextArea: ({ value, onChange, placeholder, ...p }: any) => (
    <textarea value={value ?? ''} onChange={e => onChange?.(e.target.value)} placeholder={placeholder} aria-invalid={p['validateStatus'] === 'error'} />
  ),
  Select: Object.assign(
    ({ value, onChange, optionList, placeholder, children }: any) => (
      <select value={value ?? ''} onChange={e => onChange?.(e.target.value)}>
        {optionList?.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
        {children}
      </select>
    ),
    {
      Option: ({ value, children }: any) => <option value={value}>{children}</option>,
      OptGroup: ({ label, children }: any) => <optgroup label={label}>{children}</optgroup>,
    }
  ),
  Spin: () => <div data-testid="spin" />,
  Tag: ({ children, color }: any) => <span data-color={color}>{children}</span>,
  Toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  Modal: (() => {
    const lastConfirmHolder: { current: any } = { current: null }
    const modalMock = {
      _lastConfirm: lastConfirmHolder,
      confirm: vi.fn((opts: any) => { lastConfirmHolder.current = opts }),
    }
    return modalMock
  })(),
  Table: ({ columns, dataSource }: any) => (
    <table>
      <thead>
        <tr>{columns?.map((c: any, i: number) => <th key={i}>{c.title}</th>)}</tr>
      </thead>
      <tbody>
        {dataSource?.map((row: any, ri: number) => (
          <tr key={ri}>
            {columns?.map((c: any, ci: number) => (
              <td key={ci}>{c.render ? c.render(row[c.dataIndex], row) : row[c.dataIndex]}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  ),
  Steps: Object.assign(
    ({ children }: any) => <div data-testid="steps">{children}</div>,
    { Step: ({ title }: any) => <div data-testid="step">{title}</div> }
  ),
  Typography: { Text: ({ children }: any) => <span>{children}</span> },
  Upload: ({ children }: any) => <div>{children}</div>,
  Progress: ({ percent }: any) => <div data-testid="progress" data-percent={percent} />,
}))

vi.mock('@douyinfe/semi-icons', () => ({
  IconPlus: () => <span>+</span>,
  IconDownload: () => <span>↓</span>,
  IconDelete: () => <span>×</span>,
  IconUser: () => <span>U</span>,
  IconHome: () => <span>H</span>,
  IconUpload: () => <span>↑</span>,
  IconPlay: () => <span>▶</span>,
  IconPause: () => <span>⏸</span>,
  IconPlayCircle: () => <span>▶</span>,
  IconPauseCircle: () => <span>⏸</span>,
  IconRefresh: () => <span>↺</span>,
  IconEdit: () => <span>✎</span>,
  IconClose: () => <span>✕</span>,
  IconSave: () => <span>💾</span>,
  IconChevronDown: () => <span>▼</span>,
  IconChevronUp: () => <span>▲</span>,
  IconImage: () => <span>🖼</span>,
}))

// Export for test access
export { vi }
