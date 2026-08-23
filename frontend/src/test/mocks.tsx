import React from 'react'
import { vi } from 'vitest'

// Minimal Semi UI mocks — enough for rendering and interaction tests
vi.mock('@douyinfe/semi-ui', () => ({
  Button: ({ children, onClick, disabled, icon, htmlType, ...p }: any) => (
    <button type={htmlType || 'button'} onClick={onClick} disabled={disabled} data-testid={p['data-testid']}>{icon}{children}</button>
  ),
  Input: ({ value, onChange, placeholder, ...p }: any) => (
    <input value={value ?? ''} onChange={e => onChange?.(e.target.value)} placeholder={placeholder} aria-invalid={p['validateStatus'] === 'error'} />
  ),
  InputNumber: ({ value, onChange, min, max }: any) => (
    <input type="number" value={value ?? ''} min={min} max={max}
      onChange={e => onChange?.(e.target.value === '' ? undefined : Number(e.target.value))} />
  ),
  TextArea: ({ value, onChange, placeholder, onEnterPress, disabled, ...p }: any) => (
    <textarea
      value={value ?? ''} onChange={e => onChange?.(e.target.value)} placeholder={placeholder}
      disabled={disabled}
      onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) onEnterPress?.(e) }}
      aria-invalid={p['validateStatus'] === 'error'}
    />
  ),
  Select: Object.assign(
    ({ value, onChange, optionList, placeholder, children, disabled }: any) => (
      <select value={value ?? ''} disabled={!!disabled} onChange={e => onChange?.(e.target.value)}>
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
  Switch: ({ checked, onChange }: any) => (
    <input type="checkbox" checked={!!checked} onChange={e => onChange?.(e.target.checked)} />
  ),
  Checkbox: ({ checked, onChange, children }: any) => (
    <label>
      <input type="checkbox" checked={!!checked} onChange={e => onChange?.({ target: { checked: e.target.checked } })} />
      {children}
    </label>
  ),
  Divider: () => <hr />,
  Row: ({ children }: any) => <div data-testid="row">{children}</div>,
  Col: ({ children }: any) => <div data-testid="col">{children}</div>,
  Space: ({ children }: any) => <div data-testid="space">{children}</div>,
  Tag: ({ children, color }: any) => <span data-color={color}>{children}</span>,
  Toast: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  },
  Modal: (() => {
    const lastConfirmHolder: { current: any } = { current: null }
    // 可作为 JSX 组件渲染(add/edit 弹窗):visible 时渲染内容。
    // footer 传入时(含 null)用其替代默认按钮,与真实 Semi 行为一致。
    const ModalComponent = ({ visible, children, onOk, onCancel, okText, cancelText, title, footer }: any) => {
      if (!visible) return null
      const hasFooterProp = footer !== undefined
      return (
        <div data-testid="modal">
          {title && <div>{title}</div>}
          {children}
          {hasFooterProp
            ? footer
            : (
              <>
                <button onClick={onCancel}>{cancelText || '取消'}</button>
                <button onClick={onOk}>{okText || '确定'}</button>
              </>
            )}
        </div>
      )
    }
    return Object.assign(ModalComponent, {
      _lastConfirm: lastConfirmHolder,
      confirm: vi.fn((opts: any) => { lastConfirmHolder.current = opts }),
    })
  })(),
  Table: ({ columns, dataSource, expandedRowRender, expandRowByClick }: any) => {
    const [expandedKey, setExpandedKey] = React.useState<string | null>(null)
    return (
      <table>
        <thead>
          <tr>{columns?.map((c: any, i: number) => <th key={i}>{c.title}</th>)}</tr>
        </thead>
        <tbody>
          {dataSource?.map((row: any, ri: number) => {
            const rowKey = row.shot_id ?? String(ri)
            return (
              <React.Fragment key={ri}>
                <tr
                  onClick={expandRowByClick ? () => setExpandedKey(k => k === rowKey ? null : rowKey) : undefined}
                >
                  {columns?.map((c: any, ci: number) => (
                    <td key={ci}>{c.render ? c.render(row[c.dataIndex], row) : row[c.dataIndex]}</td>
                  ))}
                </tr>
                {expandedRowRender && expandedKey === rowKey && (
                  <tr><td colSpan={columns?.length}>{expandedRowRender(row)}</td></tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
    )
  },
  Steps: Object.assign(
    ({ children }: any) => <div data-testid="steps">{children}</div>,
    { Step: ({ title, status }: any) => <div data-testid="step" data-status={status || 'wait'}>{title}</div> }
  ),
  Typography: {
    Title: ({ children }: any) => <h1>{children}</h1>,
    Text: ({ children }: any) => <span>{children}</span>,
    Paragraph: ({ children }: any) => <p>{children}</p>,
    Numeral: ({ children }: any) => <span>{children}</span>,
  },
  Card: Object.assign(
    ({ children, title, headerExtraContent, footer, actions }: any) => (
      <div data-testid="card">
        {title && <div>{title}{headerExtraContent}</div>}
        {children}
        {actions}
        {footer}
      </div>
    ),
    { Meta: ({ title, description }: any) => <div>{title}{description}</div> }
  ),
  VideoPlayer: ({ src }: any) => <video src={src} />,
  Image: ({ src, alt }: any) => <img src={src} alt={alt} />,
  ImagePreview: ({ children }: any) => <div>{children}</div>,
  MarkdownRender: ({ raw }: any) => <div>{raw}</div>,
  List: Object.assign(
    ({ dataSource, renderItem, header, emptyContent }: any) => (
      <div data-testid="list">
        {header}
        {dataSource && dataSource.length
          ? dataSource.map((it: any, i: number) => <div key={i}>{renderItem?.(it, i)}</div>)
          : emptyContent}
      </div>
    ),
    { Item: ({ children, header, main, extra, onClick, style }: any) => (
      <div onClick={onClick} style={style}>{header}{main}{children}{extra}</div>
    ) }
  ),
  Descriptions: Object.assign(
    ({ data, children }: any) => (
      <dl data-testid="descriptions">
        {data?.map((d: any, i: number) => (
          <div key={i}><dt>{d.key}</dt><dd>{typeof d.value === 'function' ? d.value() : d.value}</dd></div>
        ))}
        {children}
      </dl>
    ),
    { Item: ({ itemKey, children }: any) => <div><dt>{itemKey}</dt><dd>{children}</dd></div> }
  ),
  Empty: ({ title, description, image, children }: any) => (
    <div data-testid="empty">
      {image}
      {title != null && <div>{title}</div>}
      {description != null && <div>{description}</div>}
      {children}
    </div>
  ),
  Form: (() => {
    const FormCtx = React.createContext<any>(null)
    // 简化 Form mock:字段值收集在闭包 store,submit 时跑 required 规则再回调
    const FormMock = ({ children, onSubmit, onSubmitFail, onValueChange, initValues, getFormApi }: any) => {
      const store = React.useRef<Record<string, any>>({ ...(initValues || {}) })
      const rulesStore = React.useRef<Record<string, any[]>>({})
      const [errs, setErrs] = React.useState<Record<string, string>>({})
      const runValidate = () => {
        const newErrs: Record<string, string> = {}
        for (const [f, rules] of Object.entries(rulesStore.current)) {
          const req = (rules as any[]).find(r => r.required)
          const val = store.current[f]
          if (req && (val === undefined || val === null || String(val).trim() === '')) {
            newErrs[f] = req.message || 'required'
          }
        }
        setErrs(newErrs)
        return newErrs
      }
      const doSubmit = () => {
        const newErrs = runValidate()
        if (Object.keys(newErrs).length === 0) onSubmit?.({ ...store.current })
        else onSubmitFail?.(newErrs)
      }
      const formApi = {
        getValue: (f: string) => store.current[f],
        getValues: () => ({ ...store.current }),
        setValue: (f: string, v: any) => { store.current[f] = v },
        submitForm: () => doSubmit(),
        validate: () => {
          const newErrs = runValidate()
          return Object.keys(newErrs).length === 0
            ? Promise.resolve({ ...store.current })
            : Promise.reject(newErrs)
        },
      }
      React.useEffect(() => { getFormApi?.(formApi) }, [])
      const register = (field: string, rules?: any[], initV?: any) => {
        if (rules) rulesStore.current[field] = rules
        if (initV !== undefined && store.current[field] === undefined) store.current[field] = initV
      }
      const change = (field: string, v: any) => {
        store.current[field] = v
        setErrs(e => ({ ...e, [field]: '' }))
        onValueChange?.({ ...store.current })
      }
      const submit = (e: React.FormEvent) => {
        e.preventDefault()
        doSubmit()
      }
      const ctx = { store, register, change, errs, formApi }
      const content = typeof children === 'function' ? children({ formApi, formState: { values: store.current } }) : children
      return (
        <form onSubmit={submit}>
          <FormCtx.Provider value={ctx}>{content}</FormCtx.Provider>
        </form>
      )
    }
    const useCtx = () => React.useContext(FormCtx)
    const Field = (tag: 'input' | 'textarea') => ({ field, label, placeholder, rules, initValue, onChange }: any) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules, initValue) }, [])
      const Tag: any = tag
      return (
        <div>
          {label && <label>{label}</label>}
          <Tag
            placeholder={placeholder}
            defaultValue={c?.store.current[field] ?? ''}
            onChange={(e: any) => { c?.change(field, e.target.value); onChange?.(e.target.value) }}
          />
          {c?.errs[field] && <div role="alert">{c.errs[field]}</div>}
        </div>
      )
    }
    const FormInput = Field('input')
    const FormTextArea = Field('textarea')
    const FormSelect: any = ({ field, label, children, rules, onChange }: any) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules) }, [])
      return (
        <div>
          {label && <label>{label}</label>}
          <select
            defaultValue={c?.store.current[field] ?? ''}
            onChange={(e) => { c?.change(field, e.target.value); onChange?.(e.target.value) }}
          >{children}</select>
          {c?.errs[field] && <div role="alert">{c.errs[field]}</div>}
        </div>
      )
    }
    FormSelect.Option = ({ value, children }: any) => <option value={value}>{children}</option>
    FormSelect.OptGroup = ({ label, children }: any) => <optgroup label={label}>{children}</optgroup>
    const FormSwitch: any = ({ field, label, rules, initValue, onChange }: any) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules, initValue) }, [])
      return (
        <div>
          {label && <label>{label}</label>}
          <input
            type="checkbox"
            defaultChecked={!!c?.store.current[field]}
            onChange={(e) => { c?.change(field, e.target.checked); onChange?.(e.target.checked) }}
          />
        </div>
      )
    }
    return Object.assign(FormMock, {
      Input: FormInput, TextArea: FormTextArea, Select: FormSelect, Switch: FormSwitch,
    })
  })(),
  Upload: ({ children, accept, beforeUpload }: any) => (
    <div>
      <input
        type="file"
        accept={accept}
        onChange={(e: any) => {
          const f = e.target.files?.[0]
          if (f) beforeUpload?.({ file: { fileInstance: f } })
        }}
      />
      {children}
    </div>
  ),
  Tabs: Object.assign(
    ({ tabList, activeKey, onChange, children }: any) => (
      <div data-testid="tabs">
        {tabList?.map((t: any) => (
          <button key={t.itemKey} data-active={t.itemKey === activeKey} onClick={() => onChange?.(t.itemKey)}>
            {t.tab}
          </button>
        ))}
        {children}
      </div>
    ),
    { TabPane: ({ tab, children }: any) => <div>{tab}{children}</div> }
  ),
  Breadcrumb: Object.assign(
    ({ children }: any) => <nav className="semi-breadcrumb">{children}</nav>,
    { Item: ({ children, onClick }: any) => <span onClick={onClick}>{children}</span> },
  ),
  Progress: ({ percent }: any) => <div data-testid="progress" data-percent={percent} />,
  Banner: ({ title, description, type }: any) => (
    <div data-testid="banner" role="alert" data-type={type}>
      {title != null && <div>{title}</div>}
      {description != null && <div>{description}</div>}
    </div>
  ),
  Slider: ({ value, onChange, min, max }: any) => (
    <input type="range" data-testid="slider" value={value ?? 0} min={min} max={max}
      onChange={e => onChange?.(Number(e.target.value))} />
  ),
  Chat: ({ chats, onMessageSend, roleConfig, placeholder, renderInputArea }: any) => {
    const send = (value: string) => {
      if (!value) return
      onMessageSend?.(value, [])
    }
    const defaultInput = (
      <input
        placeholder={placeholder}
        onKeyDown={(e: any) => {
          if (e.key === 'Enter' && e.target.value) {
            send(e.target.value)
            e.target.value = ''
          }
        }}
      />
    )
    return (
      <div data-testid="chat">
        {chats?.map((m: any) => (
          <div key={m.id} data-role={m.role}>
            {roleConfig?.[m.role]?.name ? `${roleConfig[m.role].name}: ` : ''}{m.content}
          </div>
        ))}
        {renderInputArea ? renderInputArea({ defaultNode: defaultInput, onSend: send }) : defaultInput}
      </div>
    )
  },
  SideSheet: ({ visible, title, onCancel, children }: any) => {
    if (!visible) return null
    return (
      <div data-testid="side-sheet">
        {title && <div>{title}</div>}
        <button type="button" aria-label="关闭预览" onClick={onCancel}>✕</button>
        {children}
      </div>
    )
  },
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
  IconArrowUp: () => <span>↑</span>,
  IconImage: () => <span>🖼</span>,
  IconAIImageLevel1: () => <span>✨</span>,
}))

// Export for test access
export { vi }
