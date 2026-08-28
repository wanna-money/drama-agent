import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Toast, Form, Card, Typography, Space, Tabs, Empty, SideSheet, Descriptions, MarkdownRender } from '@douyinfe/semi-ui'
import {
  episodesApi, scriptsApi, configApi, projectsApi,
  CreateEpisodeData, Script, LLMModelOption, VideoModelOption,
} from '../services/api'
import PageShell, { PageLoading } from '../components/PageShell'

const { Text } = Typography

// 集级目标时长(秒),建集时可选;驱动分镜总时长收敛(后端 storyboard_director)。
const TARGET_SECONDS = [
  { value: 60, label: '60 秒' },
  { value: 90, label: '90 秒' },
  { value: 120, label: '120 秒' },
  { value: 180, label: '180 秒' },
]

export default function NewEpisodePage() {
  const { id: projectId } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [videoModels, setVideoModels] = useState<VideoModelOption[]>([])
  const [llmModels, setLlmModels] = useState<LLMModelOption[]>([])
  const [llmDefault, setLlmDefault] = useState<string>('')
  const [videoDefault, setVideoDefault] = useState<string>('')
  const [modelsLoading, setModelsLoading] = useState(true)
  const [scripts, setScripts] = useState<Script[]>([])
  const [scriptsLoading, setScriptsLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [projectTitle, setProjectTitle] = useState<string>('')
  const [previewOpen, setPreviewOpen] = useState(false)

  useEffect(() => {
    if (projectId) projectsApi.get(projectId).then(p => setProjectTitle(p.title)).catch(() => {})
  }, [projectId])

  useEffect(() => {
    Promise.all([
      configApi.listModels().catch(() => ({ models: [] as LLMModelOption[], default: null })),
      configApi.listVideoModels().catch(() => ({ models: [] as VideoModelOption[], default: null })),
    ]).then(([llm, video]) => {
      setLlmModels(llm.models)
      setLlmDefault(llm.default || '')
      setVideoModels(video.models)
      setVideoDefault(video.default || '')
    }).finally(() => setModelsLoading(false))
  }, [])

  // 不按作品过滤:剧本库是全局的,散稿(project_id=null)不属于任何作品,
  // 按 projectId 过滤会让它对每个作品的「新建一集」都不可见。归属改为在选项里标注。
  const loadScripts = () => {
    setScriptsLoading(true)
    scriptsApi.list()
      .then(setScripts)
      .catch(() => Toast.error('加载剧本失败'))
      .finally(() => setScriptsLoading(false))
  }
  useEffect(() => { loadScripts() }, [])

  const groupBy = <T extends { provider: string }>(items: T[]) =>
    items.reduce<Record<string, T[]>>((acc, m) => { ;(acc[m.provider] ??= []).push(m); return acc }, {})
  const llmGroups = groupBy(llmModels)
  const videoGroups = groupBy(videoModels)

  const commonInit = {
    // 默认模型只认后端下发的 default(唯一权威);前端不设写死的兜底模型名,
    // 那会与用户在「模型管理」标的默认模型分叉。
    llm_model: llmDefault,
    video_provider: videoDefault || 'seedance',
    resolution: (videoModels.find(m => m.value === videoDefault)?.default_resolution) || '768P',
    use_keyframes: false,
    target_seconds: 120,
  }
  const episodeInit = { ...commonInit, script_id: scripts[0]?.id }
  const storyInit = { ...commonInit }

  const baseData = (values: any): CreateEpisodeData => ({
    title: values.title.trim(),
    llm_model: values.llm_model,
    video_provider: values.video_provider,
    resolution: values.resolution,
    use_keyframes: !!values.use_keyframes,
    target_seconds: values.target_seconds,
  })

  const doCreate = async (data: CreateEpisodeData) => {
    if (!projectId) return
    setCreating(true)
    try {
      const ep = await episodesApi.create(projectId, data)
      Toast.success('剧集已创建')
      navigate(`/episodes/${ep.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setCreating(false)
    }
  }

  // 入口一:复用剧本库里的剧本 → 直接建集(图内从分镜开始)
  const submitFromScript = (values: any) => doCreate({ ...baseData(values), script_id: values.script_id })
  // 入口二:输入故事 → 直接建集(图内从故事分析开始,剧本审核在剧集页内完成)
  const submitFromStory = (values: any) => doCreate({ ...baseData(values), raw_input: values.source_text.trim() })

  // 视频模型/分辨率/目标时长片段在两个 tab 复用
  const modelFields = (formApi: any) => (
    <>
      <Form.Select field="llm_model" label="文本模型（LLM）">
        {Object.entries(llmGroups).map(([provider, opts]) => (
          <Form.Select.OptGroup key={provider} label={provider}>
            {opts.map(m => <Form.Select.Option key={m.value} value={m.value}>{m.label}</Form.Select.Option>)}
          </Form.Select.OptGroup>
        ))}
      </Form.Select>
      <Form.Select
        field="video_provider" label="视频模型"
        onChange={(val) => {
          const m = videoModels.find(x => x.value === val)
          if (m?.default_resolution) formApi.setValue('resolution', m.default_resolution)
        }}
      >
        {Object.entries(videoGroups).map(([provider, opts]) => (
          <Form.Select.OptGroup key={provider} label={provider}>
            {opts.map(m => <Form.Select.Option key={m.value} value={m.value}>{m.label}</Form.Select.Option>)}
          </Form.Select.OptGroup>
        ))}
      </Form.Select>
      <Form.Select field="resolution" label="分辨率">
        {(videoModels.find(m => m.value === formApi.getValue('video_provider'))?.resolutions ?? ['768P']).map(r => (
          <Form.Select.Option key={r} value={r}>{r}</Form.Select.Option>
        ))}
      </Form.Select>
      <Form.Select field="target_seconds" label="目标时长">
        {TARGET_SECONDS.map(o => (
          <Form.Select.Option key={o.value} value={o.value}>{o.label}</Form.Select.Option>
        ))}
      </Form.Select>
      <Form.Switch field="use_keyframes" label="关键帧先行（先出静态图审核再生成视频）" />
    </>
  )

  if (modelsLoading || scriptsLoading) {
    return <PageLoading />
  }

  return (
    <PageShell
      title="新建一集"
      description="输入故事直接开拍,或从剧本库复用已有剧本"
      breadcrumb={[
        { label: '作品列表', href: '/' },
        { label: projectTitle || '作品', href: `/projects/${projectId}` },
        { label: '新建一集' },
      ]}
    >
      <Card>
        <Tabs type="line">
          <Tabs.TabPane tab="输入故事" itemKey="story">
            <Form initValues={storyInit} onSubmit={submitFromStory} labelPosition="top">
              {({ formApi }: any) => (
                <>
                  <Form.Input
                    field="title" label="本集标题" placeholder="给这一集起个名字"
                    rules={[{ required: true, message: '请输入本集标题' }]}
                  />
                  <Form.TextArea
                    field="source_text" label="故事内容" rows={9}
                    placeholder="粘贴故事、小说或剧情大纲（支持中英文，建议 500–5000 字）"
                    rules={[{ required: true, message: '请输入故事内容' }]}
                  />
                  {modelFields(formApi)}
                  <Space align="center">
                    <Button colorful theme="solid" htmlType="submit" type="primary" loading={creating}>
                      开始制作
                    </Button>
                    <Text type="tertiary" size="small">剧本审核在剧集页内完成,可 AI 改写 · 分镜/Prompt 均可编辑</Text>
                  </Space>
                </>
              )}
            </Form>
          </Tabs.TabPane>

          <Tabs.TabPane tab="从剧本库选" itemKey="pick">
            {scripts.length === 0 ? (
              <Empty description="剧本库还没有剧本。可在「输入故事」页直接开拍,通过审核后即可存入剧本库复用。" />
            ) : (
              <Form initValues={episodeInit} onSubmit={submitFromScript} labelPosition="top">
                {({ formApi }: any) => (
                  <>
                    <Form.Input
                      field="title" label="本集标题" placeholder="例如：第 1 集 · 深夜来客"
                      rules={[{ required: true, message: '请输入本集标题' }]}
                    />
                    <Space align="end">
                      <Form.Select
                        field="script_id" label="源剧本"
                        placeholder="选择一个剧本"
                        rules={[{ required: true, message: '请选择源剧本' }]}
                      >
                        {scripts.map(s => (
                          <Form.Select.Option key={s.id} value={s.id}>
                            {s.project_title ? `${s.title}（${s.project_title}）` : `${s.title}（未归属）`}
                          </Form.Select.Option>
                        ))}
                      </Form.Select>
                      <Button
                        disabled={!formApi.getValue('script_id')}
                        onClick={() => setPreviewOpen(true)}
                      >预览</Button>
                    </Space>
                    {modelFields(formApi)}
                    <Space align="center">
                      <Button colorful theme="solid" htmlType="submit" type="primary" loading={creating}>
                        创建视频
                      </Button>
                      <Text type="tertiary" size="small">分镜与 Prompt 均可编辑 · 多阶段人工审核干预</Text>
                    </Space>
                    <SideSheet
                      title={scripts.find(s => s.id === formApi.getValue('script_id'))?.title}
                      visible={previewOpen}
                      onCancel={() => setPreviewOpen(false)}
                      placement="right"
                    >
                      {(() => {
                        const s = scripts.find(x => x.id === formApi.getValue('script_id'))
                        if (!s) return null
                        return (
                          <Space vertical align="start">
                            <Descriptions
                              data={[
                                { key: '类型', value: s.story_analysis?.genre || '-' },
                                { key: '基调', value: s.story_analysis?.tone || '-' },
                                { key: '主题', value: s.story_analysis?.themes?.join('、') || '-' },
                              ]}
                            />
                            <MarkdownRender raw={s.content || ''} />
                          </Space>
                        )
                      })()}
                    </SideSheet>
                  </>
                )}
              </Form>
            )}
          </Tabs.TabPane>
        </Tabs>
      </Card>
    </PageShell>
  )
}
