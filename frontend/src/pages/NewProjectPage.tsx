import { useState, useEffect, useRef } from 'react'
import { useNavigate, useBlocker } from 'react-router-dom'
import { Button, Toast, Select, Spin, Input, TextArea, Modal } from '@douyinfe/semi-ui'
import { projectsApi, configApi, CreateProjectData, LLMModelOption, VideoModelOption } from '../services/api'

export default function NewProjectPage() {
  const [loading, setLoading] = useState(false)
  const [llmModels, setLlmModels] = useState<LLMModelOption[]>([])
  const [videoModels, setVideoModels] = useState<VideoModelOption[]>([])
  const [modelsLoading, setModelsLoading] = useState(true)
  const [title, setTitle] = useState('')
  const [rawInput, setRawInput] = useState('')
  const [genre, setGenre] = useState('drama')
  const [videoProvider, setVideoProvider] = useState('seedance')
  const [llmModel, setLlmModel] = useState('deepseek-v4-pro')
  const [errors, setErrors] = useState<{ title?: string; raw_input?: string }>({})
  const navigate = useNavigate()
  const modelsInitialized = useRef(false)

  useEffect(() => {
    Promise.all([
      configApi.listModels().catch(() => [{ value: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', provider: 'DeepSeek' }] as LLMModelOption[]),
      configApi.listVideoModels().catch(() => [{ value: 'seedance', label: 'Seedance 2.0', provider: '字节跳动' }] as VideoModelOption[]),
    ]).then(([llm, video]) => {
      setLlmModels(llm)
      setVideoModels(video)
      if (!modelsInitialized.current) {
        modelsInitialized.current = true
        if (llm[0]) setLlmModel(llm[0].value)
        if (video[0]) setVideoProvider(video[0].value)
      }
    }).finally(() => setModelsLoading(false))
  }, [])

  useEffect(() => {
    const isDirty = title.trim() || rawInput.trim()
    if (!isDirty) return
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault() }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [title, rawInput])

  const isDirty = !!(title.trim() || rawInput.trim())
  const blocker = useBlocker(isDirty && !loading)
  useEffect(() => {
    if (blocker.state === 'blocked') {
      Modal.confirm({
        title: '离开页面',
        content: '您已输入内容，离开后将丢失，确定离开？',
        okText: '离开',
        cancelText: '继续编辑',
        onOk: () => blocker.proceed(),
        onCancel: () => blocker.reset(),
      })
    }
  }, [blocker.state])

  const handleSubmit = async () => {
    const errs: { title?: string; raw_input?: string } = {}
    if (!title.trim()) errs.title = '请输入项目标题'
    if (!rawInput.trim()) errs.raw_input = '请输入故事内容'
    setErrors(errs)
    if (Object.keys(errs).length > 0) return

    setLoading(true)
    try {
      const data: CreateProjectData = {
        title: title.trim(),
        raw_input: rawInput.trim(),
        genre,
        llm_model: llmModel,
        video_provider: videoProvider,
      }
      const project = await projectsApi.create(data)
      Toast.success('项目创建成功')
      navigate(`/projects/${project.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  const groupBy = <T extends { provider: string }>(items: T[]) =>
    items.reduce<Record<string, T[]>>((acc, m) => { ;(acc[m.provider] ??= []).push(m); return acc }, {})

  const llmGroups = groupBy(llmModels)
  const videoGroups = groupBy(videoModels)

  const labelStyle: React.CSSProperties = {
    fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 6, display: 'block',
  }
  const errorStyle: React.CSSProperties = {
    fontSize: 11, color: '#EF4444', marginTop: 4,
  }

  return (
    <div style={{ maxWidth: 720, margin: '0 auto' }}>
      <div className="page-title-section">
        <div className="page-title-eyebrow">New Project</div>
        <h1 className="page-title-main">新建短剧项目</h1>
        <p className="page-title-sub">输入故事内容，AI 将自动完成剧本、分镜、视频生成全流程</p>
      </div>

      <hr className="grad-divider" />

      <div className="glass-card" style={{ marginTop: 24, padding: '32px 36px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* 项目标题 */}
          <div>
            <label style={labelStyle}>
              项目标题 <span style={{ color: '#EF4444' }}>*</span>
            </label>
            <Input
              value={title}
              onChange={v => { setTitle(v); if (v.trim()) setErrors(e => ({ ...e, title: undefined })) }}
              placeholder="为您的短剧起一个名字"
              validateStatus={errors.title ? 'error' : undefined}
            />
            {errors.title && <div style={errorStyle}>{errors.title}</div>}
          </div>

          {/* 故事内容 */}
          <div>
            <label style={labelStyle}>
              故事内容 <span style={{ color: '#EF4444' }}>*</span>
            </label>
            <TextArea
              value={rawInput}
              onChange={v => { setRawInput(v); if (v.trim()) setErrors(e => ({ ...e, raw_input: undefined })) }}
              placeholder="粘贴您的故事、小说或剧情大纲（支持中英文，建议 500–5000 字）"
              rows={9}
              validateStatus={errors.raw_input ? 'error' : undefined}
            />
            {errors.raw_input && <div style={errorStyle}>{errors.raw_input}</div>}
          </div>

          {/* 选项行 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
            <div>
              <label style={labelStyle}>故事类型</label>
              <Select value={genre} onChange={v => setGenre(v as string)} style={{ width: '100%' }}>
                <Select.Option value="drama">剧情</Select.Option>
                <Select.Option value="romance">爱情</Select.Option>
                <Select.Option value="thriller">悬疑</Select.Option>
                <Select.Option value="comedy">喜剧</Select.Option>
                <Select.Option value="action">动作</Select.Option>
                <Select.Option value="fantasy">奇幻</Select.Option>
              </Select>
            </div>

            <div>
              <label style={labelStyle}>视频模型</label>
              <Select
                value={videoProvider}
                onChange={v => setVideoProvider(v as string)}
                style={{ width: '100%' }}
                prefix={modelsLoading ? <Spin size="small" /> : undefined}
              >
                {Object.entries(videoGroups).map(([provider, opts]) => (
                  <Select.OptGroup key={provider} label={provider}>
                    {opts.map(m => (
                      <Select.Option key={m.value} value={m.value}>{m.label}</Select.Option>
                    ))}
                  </Select.OptGroup>
                ))}
              </Select>
            </div>

            <div>
              <label style={labelStyle}>文本模型</label>
              <Select
                value={llmModel}
                onChange={v => setLlmModel(v as string)}
                style={{ width: '100%' }}
                prefix={modelsLoading ? <Spin size="small" /> : undefined}
              >
                {Object.entries(llmGroups).map(([provider, opts]) => (
                  <Select.OptGroup key={provider} label={provider}>
                    {opts.map(m => (
                      <Select.Option key={m.value} value={m.value}>{m.label}</Select.Option>
                    ))}
                  </Select.OptGroup>
                ))}
              </Select>
            </div>
          </div>

          {/* 提交 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: '#9CA3AF', letterSpacing: '0.3px' }}>
              剧本与 Prompt 均可编辑 · 多阶段人工审核干预
            </span>
            <Button onClick={handleSubmit} type="primary" loading={loading} size="large" style={{ minWidth: 140 }}>
              开始创作
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
