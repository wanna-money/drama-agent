import React from 'react'
import { vi } from 'vitest'

// AIChatInput.Configure.* 在真实组件里靠内部 Context 把各项的值收进 `setup`
// (getConfigureItem.js:onChange/onRemove)。Configure 本身不对外导出 hook,
// 故替身自建一份同构 Context,由 AIChatInput 替身在渲染 renderConfigureArea 时
// 提供,Select/Button 替身读写它 —— 否则测试里选中的值永远进不了 onMessageSend 的 setup。
const ConfigureContext = React.createContext<any>({
  value: {}, onChange: () => {}, onRemove: () => {},
})

// Configure.Select 替身:真实组件是自定义下拉(点开显示选项),不是原生 <select>——
// 原生 <option> 在 jsdom 里 userEvent.click 选不中(已验证),而测试要靠
// "点开 → 点选项文字"驱动,故这里用按钮列表还原同一种交互。
const ConfigureSelectMock = (props: any) => {
  const { field, initValue, onChange, optionList, disabled, placeholder, ...rest } = props
  const ctx = React.useContext(ConfigureContext)
  const [open, setOpen] = React.useState(false)
  React.useEffect(() => {
    if (initValue !== undefined) ctx.onChange({ [field]: initValue })
    return () => ctx.onRemove(field)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const current = optionList?.find((o: any) => o.value === ctx.value[field])
  return (
    <span>
      <button
        type="button" disabled={!!disabled} data-testid={rest['data-testid']}
        onClick={() => setOpen(o => !o)}
      >{current?.label ?? placeholder ?? ''}</button>
      {open && optionList?.map((o: any) => (
        <button
          key={o.value} type="button"
          // 必须透传 option 级 disabled:不传的话"某个选项被禁用"这件事
          // 在测试里完全观测不到,针对它的断言会恒真。
          disabled={!!o.disabled}
          onClick={() => {
            ctx.onChange({ [field]: o.value })
            onChange?.(o.value)
            setOpen(false)
          }}
        >{o.label}</button>
      ))}
    </span>
  )
}

// Configure.Button 替身:布尔开关。真实组件的点击回调是 `onClick`(不是 `onChange` ——
// 那个名字被 getConfigureItem 占去写 Configure 的内部 value 了),调用方
// (ClipConfigureBar)靠它驱动"展开/收起负向提示词"这类自有状态。
const ConfigureButtonMock = ({ field, initValue, onClick, children, icon, disabled, ...rest }: any) => {
  const ctx = React.useContext(ConfigureContext)
  React.useEffect(() => {
    if (initValue !== undefined) ctx.onChange({ [field]: initValue })
    return () => ctx.onRemove(field)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const active = !!ctx.value[field]
  return (
    <button
      type="button" disabled={!!disabled} data-testid={rest['data-testid']}
      onClick={() => {
        const next = !active
        ctx.onChange({ [field]: next })
        onClick?.(next)
      }}
    >{icon}{children}</button>
  )
}

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
    ({ value, onChange, optionList, placeholder, children, disabled, ...rest }: any) => (
      <select
        value={value ?? ''} disabled={!!disabled} onChange={e => onChange?.(e.target.value)}
        aria-label={rest['aria-label']}
      >
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
  // 真实 Cropper 通过 ref 暴露 getCropperCanvas();测试替身按同一契约返回一个
  // toDataURL 可用的 canvas,否则调用方拿不到裁切结果。
  Cropper: React.forwardRef(({ src }: any, ref: any) => {
    React.useImperativeHandle(ref, () => ({
      getCropperCanvas: () => ({
        toDataURL: () => `data:image/png;base64,CROP(${src})`,
      }),
    }))
    return <div data-testid="cropper" data-src={src} />
  }),
  Switch: ({ checked, onChange }: any) => (
    <input type="checkbox" checked={!!checked} onChange={e => onChange?.(e.target.checked)} />
  ),
  Checkbox: ({ checked, onChange, children }: any) => (
    <label>
      <input type="checkbox" checked={!!checked} onChange={e => onChange?.({ target: { checked: e.target.checked } })} />
      {children}
    </label>
  ),
  // RadioGroup 的 onChange 收到的是**事件对象**(值在 e.target.value),不是裸值 ——
  // mock 若回裸值,页面里写 e.target.value 的代码在测试里会拿到 undefined 而仍"通过"。
  RadioGroup: ({ value, onChange, children }: any) => (
    <div data-testid="radio-group" data-value={value}>
      {React.Children.map(children, (ch: any) =>
        React.cloneElement(ch, { checked: ch.props.value === value, onChange }))}
    </div>
  ),
  Radio: ({ value, checked, onChange, children }: any) => (
    <label>
      <input
        type="radio" value={value} checked={!!checked}
        onChange={() => onChange?.({ target: { value } })}
      />
      {children}
    </label>
  ),
  Divider: () => <hr />,
  Row: ({ children }: any) => <div data-testid="row">{children}</div>,
  Col: ({ children }: any) => <div data-testid="col">{children}</div>,
  Space: ({ children }: any) => <div data-testid="space">{children}</div>,
  Tag: ({ children, color, onClick }: any) => <span data-color={color} onClick={onClick}>{children}</span>,
  // 提示文案挂 title,测试可据此断言"为什么这个按钮不可用"
  Tooltip: ({ children, content }: any) => <span title={String(content ?? '')}>{children}</span>,
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
    // 真实 Semi 只在 Step 拿到 onChange/onClick 时才加 clickable/hover 类
    // (basicStep.tsx);mock 用 data-clickable 暴露同一判据,供断言"看起来能点"。
    { Step: ({ title, status, onClick }: any) => (
      <div
        data-testid="step" data-status={status || 'wait'}
        data-clickable={onClick ? 'true' : 'false'}
        onClick={onClick}
      >{title}</div>
    ) }
  ),
  Typography: {
    Title: ({ children }: any) => <h1>{children}</h1>,
    // 透传 onClick:Text link 是本项目里常用的点击目标(列表标题、卡片标题)。
    // 丢掉它这些点击就无法被测到(实测:分组卡片标题的跳转因此测不出来)。
    Text: ({ children, onClick }: any) => <span onClick={onClick}>{children}</span>,
    Paragraph: ({ children }: any) => <p>{children}</p>,
    Numeral: ({ children }: any) => <span>{children}</span>,
  },
  Card: Object.assign(
    ({ children, title, headerExtraContent, footer, actions, cover }: any) => (
      <div data-testid="card">
        {/* 标题单独打标:断言"分组顺序/组标题"需要能定位它,而不是全文搜文本 */}
        {title && <div><span data-testid="card-title">{title}</span>{headerExtraContent}</div>}
        {cover}
        {children}
        {actions}
        {footer}
      </div>
    ),
    { Meta: ({ title, description }: any) => <div>{title}{description}</div> }
  ),
  // Collapse 替身:面板内容始终渲染(不模拟折叠/展开的可见性切换)——现有测试
  // 只断言角色/造型的内容存在,不断言"折叠态下不可见",故不需要还原真实的
  // 展开/收起交互,保持替身最简。
  Collapse: Object.assign(
    ({ children }: any) => <div data-testid="collapse">{children}</div>,
    { Panel: ({ header, children }: any) => (
      <div data-testid="collapse-panel">
        <div data-testid="collapse-panel-header">{header}</div>
        {children}
      </div>
    ) }
  ),
  VideoPlayer: ({ src }: any) => <video src={src} />,
  // onClick 必须转发:preview={false} 的用法(点图直接选中而非放大预览)靠它触发,
  // 吞掉会让"点图没反应"的回归在测试里仍是绿的。
  Image: ({ src, alt, onClick }: any) => <img src={src} alt={alt} onClick={onClick} />,
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
          const val = store.current[f]
          const req = (rules as any[]).find(r => r.required)
          if (req && (val === undefined || val === null || String(val).trim() === '')) {
            newErrs[f] = req.message || 'required'
            continue
          }
          // 也跑 validator 规则(与 Semi 一致):只认 required 的话,靠 validator 表达的
          // 跨字段约束(如"二选一")在测试里永远是绿的 —— 而那正是"点了没反应"那类
          // 静默失败的藏身处。
          for (const r of rules as any[]) {
            if (typeof r.validator !== 'function') continue
            let ok = true
            try { ok = r.validator(r, val) !== false } catch { ok = false }
            if (!ok) { newErrs[f] = r.message || 'invalid'; break }
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
    const Field = (tag: 'input' | 'textarea') => ({ field, label, placeholder, rules, initValue, onChange, ...rest }: any) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules, initValue) }, [])
      const Tag: any = tag
      return (
        <div>
          {label && <label>{label}</label>}
          <Tag
            aria-label={label}
            placeholder={placeholder}
            data-testid={rest['data-testid']}
            defaultValue={c?.store.current[field] ?? ''}
            onChange={(e: any) => { c?.change(field, e.target.value); onChange?.(e.target.value) }}
          />
          {c?.errs[field] && <div role="alert">{c.errs[field]}</div>}
        </div>
      )
    }
    const FormInput = Field('input')
    const FormTextArea = Field('textarea')
    // 与真实 Semi 一致:Form.InputNumber 有值时写进表单 store 的是 number,
    // 清空时是空字符串 ''(见 semi-foundation/inputNumber/foundation.js 的 notifyChange:
    // value == null || value === '' 一律回调 ''),不是 undefined。
    const FormInputNumber: any = ({ field, label, placeholder, rules, initValue, onChange }: any) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules, initValue) }, [])
      return (
        <div>
          {label && <label>{label}</label>}
          <input
            type="number"
            placeholder={placeholder}
            defaultValue={c?.store.current[field] ?? ''}
            onChange={(e) => {
              const v = e.target.value === '' ? '' : Number(e.target.value)
              c?.change(field, v); onChange?.(v)
            }}
          />
          {c?.errs[field] && <div role="alert">{c.errs[field]}</div>}
        </div>
      )
    }
    // disabled / extraText 必须透出:依赖字段(未选前置项时禁用)与字段附属区
    // (预览按钮、"这段原文还没有方案"的提示)都靠它们表达,吞掉就测不到。
    // value 受控而非 defaultValue —— 前置项变化时上游会清空本字段,吞掉这个清空
    // 会让"换故事后仍提交旧方案"的回归无人拦截。
    const FormSelect: any = (
      { field, label, children, rules, onChange, disabled, extraText }: any
    ) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules) }, [])
      return (
        <div>
          {label && <label>{label}</label>}
          {/* 不插 placeholder 空 option:它会混进"选项清单"类断言(分辨率/比例/时长
              都断言过 option 值的完整列表)。空值由受控 value='' 表达即可。 */}
          <select
            aria-label={label}
            disabled={disabled}
            value={c?.store.current[field] ?? ''}
            onChange={(e) => { c?.change(field, e.target.value); onChange?.(e.target.value) }}
          >{children}</select>
          {extraText}
          {c?.errs[field] && <div role="alert">{c.errs[field]}</div>}
        </div>
      )
    }
    // disabled 必须透传:未配凭证的模型选项靠它禁用,吞掉就测不出
    // "选中一个没凭证的模型"这类回归(会一路跑到流水线全失败才报错)。
    FormSelect.Option = ({ value, disabled, children }: any) => (
      <option value={value} disabled={!!disabled}>{children}</option>
    )
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
    // 真实 Cascader 的值是**整条路径**(['作品','剧本']);mock 用扁平 <select> 承载,
    // option 的 value 是路径 JSON,change 时解析回数组 —— 否则测不出"取路径末位"这段逻辑。
    const FormCascader: any = ({ field, label, treeData, rules, placeholder, extraText }: any) => {
      const c = useCtx()
      React.useEffect(() => { c?.register(field, rules) }, [])
      const cur = c?.store.current[field]
      return (
        <div>
          {label && <label>{label}</label>}
          <select
            data-testid="cascader"
            aria-label={label}
            defaultValue={cur ? JSON.stringify(cur) : ''}
            onChange={(e) => c?.change(field, e.target.value ? JSON.parse(e.target.value) : undefined)}
          >
            <option value="">{placeholder}</option>
            {(treeData || []).map((g: any) => (
              <optgroup key={g.value} label={g.label}>
                {(g.children || []).map((ch: any) => (
                  <option key={ch.value} value={JSON.stringify([g.value, ch.value])}>{ch.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
          {extraText}
          {c?.errs[field] && <div role="alert">{c.errs[field]}</div>}
        </div>
      )
    }
    return Object.assign(FormMock, {
      Input: FormInput, TextArea: FormTextArea, InputNumber: FormInputNumber,
      Select: FormSelect, Switch: FormSwitch, Cascader: FormCascader,
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
    // 两个 pane 同时渲染(不按 activeKey 裁剪):这样测试无需先点 tab 就能填字段。
    // 代价是同名字段会在两个 pane 里各出现一次,故给 pane 挂 itemKey 作 testid,
    // 让测试能 within(getByTestId('tabpane-xxx')) 限定范围。
    {
      TabPane: ({ tab, itemKey, children }: any) => (
        <div data-testid={`tabpane-${itemKey}`}>{tab}{children}</div>
      ),
    }
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
  // AI 组件替身:只保留测试要用的契约(渲染消息 / 发送 / 建议 / 上传)。
  AIChatDialogue: ({ chats, roleConfig }: any) => (
    <div data-testid="ai-dialogue">
      {chats?.map((m: any) => (
        <div key={m.id} data-role={m.role}>
          {roleConfig?.[m.role]?.name ? `${roleConfig[m.role].name}: ` : ''}{m.content}
        </div>
      ))}
    </div>
  ),
  // 建议项经 renderSuggestionItem 渲染 —— 与真实 Semi 一致。
  // **不要**改回调 onSuggestClick:那个 prop 只存在于 Semi 的类型声明里,实现从不调用它
  // (内部走 handleSuggestionSelect → editor.setContent(suggestion),而 suggestion 是
  // {content} 对象、不是 tiptap 文档,于是点了没有任何反应)。mock 若替它兜着,
  // 这个"点建议没反应"的 bug 在测试里永远是绿的。
  AIChatInput: Object.assign(
    ({
      placeholder, suggestions, onMessageSend, renderSuggestionItem, onUploadChange,
      generating, references, renderReference, onReferenceDelete,
      skills, skillHotKey, onSkillChange, renderConfigureArea,
    }: any) => {
      // 配置值汇总在此:真实组件靠 Configure 的 context 收集各项的值,发送时
      // 一并塞进 onMessageSend 的 setup —— 替身用一个可变的 ref 复现同一契约
      // (不用 state:值只在发送那一刻读取,不需要为它触发本组件重渲染)。
      const configValue = React.useRef<Record<string, any>>({})
      const ctx = React.useMemo(() => ({
        value: configValue.current,
        onChange: (obj: Record<string, any>) => { Object.assign(configValue.current, obj) },
        onRemove: (field: string) => { delete configValue.current[field] },
      }), [])
      return (
        <div data-testid="ai-input">
          {/* 配置区:真实组件把它渲染在底部,测试里位置无关紧要 */}
          <div data-testid="configure-area">
            <ConfigureContext.Provider value={ctx}>
              {renderConfigureArea?.('cls')}
            </ConfigureContext.Provider>
          </div>
          {/* 引用条:每条引用一个容器 + 组件自定义的渲染 */}
          <div data-testid="reference-bar">
            {references?.map((ref: any) => (
              <div key={ref.id} data-testid={`reference-${ref.id}`}>
                {renderReference?.(ref)}
                <button onClick={() => onReferenceDelete?.(ref)}>删除引用</button>
              </div>
            ))}
          </div>
          {/* skills:@ 面板的候选项。真实组件靠 skillHotKey 唤起,
              测试里直接把候选渲染成按钮点选 —— 我们要验的是"候选来自哪、选中后做什么" */}
          <div data-testid="skill-panel" data-hotkey={skillHotKey}>
            {skills?.map((sk: any) => (
              <button key={sk.value} onClick={() => onSkillChange?.(sk)}>{sk.label}</button>
            ))}
          </div>
          <input
            placeholder={placeholder}
            disabled={!!generating}
            onKeyDown={(e: any) => {
              if (e.key === 'Enter' && e.target.value) {
                onMessageSend?.({
                  inputContents: [{ type: 'text', text: e.target.value }],
                  setup: { ...configValue.current },
                })
                e.target.value = ''
              }
            }}
          />
          {suggestions?.map((sg: any, i: number) => (
            <React.Fragment key={i}>
              {renderSuggestionItem?.({
                suggestion: sg,
                className: 'semi-aiChatInput-suggestion-item',
                onMouseEnter: () => {},
              })}
            </React.Fragment>
          ))}
          <input
            type="file" aria-label="上传附件"
            onChange={(e: any) => onUploadChange?.({
              fileList: Array.from(e.target.files ?? []).map((f: any) => ({ fileInstance: f, name: f.name })),
            })}
          />
        </div>
      )
    },
    { Configure: { Select: ConfigureSelectMock, Button: ConfigureButtonMock } },
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
  IconTickCircle: () => <span>✓</span>,
  IconAlertTriangle: () => <span>!</span>,
}))

// Export for test access
export { vi }
