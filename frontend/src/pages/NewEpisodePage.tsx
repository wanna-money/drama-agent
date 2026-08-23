import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Button, Toast, Form, Card, Typography, Space, Tabs, Empty, SideSheet, Descriptions, MarkdownRender } from '@douyinfe/semi-ui'
import {
  episodesApi, scriptsApi, configApi, projectsApi,
  CreateEpisodeData, Script, LLMModelOption, VideoModelOption,
} from '../services/api'
import { GENRES } from '../constants/genres'
import PageShell, { PageLoading } from '../components/PageShell'

const { Text } = Typography

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

  const loadScripts = () => {
    setScriptsLoading(true)
    scriptsApi.list(projectId)
      .then(setScripts)
      .catch(() => Toast.error('加载剧本失败'))
      .finally(() => setScriptsLoading(false))
  }
  useEffect(() => { loadScripts() }, [projectId])

  const completedScripts = scripts.filter(s => s.status === 'completed')

  const groupBy = <T extends { provider: string }>(items: T[]) =>
    items.reduce<Record<string, T[]>>((acc, m) => { ;(acc[m.provider] ??= []).push(m); return acc }, {})
  const llmGroups = groupBy(llmModels)
  const videoGroups = groupBy(videoModels)

  const episodeInit = {
    script_id: completedScripts[0]?.id,
    llm_model: llmDefault || 'deepseek-v4-pro',
    video_provider: videoDefault || 'seedance',
    resolution: (videoModels.find(m => m.value === videoDefault)?.default_resolution) || '768P',
    use_keyframes: false,
  }

  // 入口一:从剧本库选 completed 剧本 → 直接建集
  const submitFromScript = async (values: any) => {
    if (!projectId) return
    setCreating(true)
    try {
      const data: CreateEpisodeData = {
        title: values.title.trim(),
        script_id: values.script_id,
        llm_model: values.llm_model,
        video_provider: values.video_provider,
        resolution: values.resolution,
        use_keyframes: !!values.use_keyframes,
      }
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

  // 入口二:输入故事 → 建剧本草稿并生成正文 → 跳剧本详情审核(审核通过后回来选它建集)
  const submitFromStory = async (values: any) => {
    setCreating(true)
    try {
      const script = await scriptsApi.create({
        title: values.title.trim(),
        genre: values.genre,
        source_text: values.source_text.trim(),
        project_id: projectId,
        llm_model: values.llm_model,
      })
      Toast.success('剧本创作已启动,审核通过后即可用它创建视频')
      navigate(`/scripts/${script.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setCreating(false)
    }
  }

  if (modelsLoading || scriptsLoading) {
    return <PageLoading />
  }

  return (
    <PageShell
      title="新建一集"
      description="从已有剧本创建视频,或输入故事先创作剧本"
      breadcrumb={[
        { label: '作品列表', href: '/' },
        { label: projectTitle || '作品', href: `/projects/${projectId}` },
        { label: '新建一集' },
      ]}
    >
      <Card>
        <Tabs type="line">
          <Tabs.TabPane tab="从剧本库选" itemKey="pick">
            {completedScripts.length === 0 ? (
              <Empty description="暂无可用剧本(需已完成的剧本)。可在「输入故事」页创作,或到剧本库创建。" />
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
                        placeholder="选择一个已完成的剧本"
                        rules={[{ required: true, message: '请选择源剧本' }]}
                      >
                        {completedScripts.map(s => (
                          <Form.Select.Option key={s.id} value={s.id}>{s.title}</Form.Select.Option>
                        ))}
                      </Form.Select>
                      <Button
                        disabled={!formApi.getValue('script_id')}
                        onClick={() => setPreviewOpen(true)}
                      >预览</Button>
                    </Space>
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
                    <Form.Switch field="use_keyframes" label="关键帧先行（先出静态图审核再生成视频）" />
                    <Space align="center">
                      <Button colorful theme="solid" htmlType="submit" type="primary" loading={creating}>
                        创建视频
                      </Button>
                      <Text type="tertiary" size="small">分镜与 Prompt 均可编辑 · 多阶段人工审核干预</Text>
                    </Space>
                    <SideSheet
                      title={completedScripts.find(s => s.id === formApi.getValue('script_id'))?.title}
                      visible={previewOpen}
                      onCancel={() => setPreviewOpen(false)}
                      placement="right"
                    >
                      {(() => {
                        const s = completedScripts.find(x => x.id === formApi.getValue('script_id'))
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

          <Tabs.TabPane tab="输入故事" itemKey="story">
            <Form
              initValues={{ genre: 'drama', llm_model: llmDefault }}
              onSubmit={submitFromStory}
              labelPosition="top"
            >
              <Form.Input
                field="title" label="剧本标题" placeholder="给这个剧本起个名字"
                rules={[{ required: true, message: '请输入剧本标题' }]}
              />
              <Form.Select field="genre" label="类型">
                {GENRES.map(o => (
                  <Form.Select.Option key={o.value} value={o.value}>{o.label}</Form.Select.Option>
                ))}
              </Form.Select>
              <Form.Select field="llm_model" label="文本模型（LLM）">
                {Object.entries(llmGroups).map(([provider, opts]) => (
                  <Form.Select.OptGroup key={provider} label={provider}>
                    {opts.map(m => <Form.Select.Option key={m.value} value={m.value}>{m.label}</Form.Select.Option>)}
                  </Form.Select.OptGroup>
                ))}
              </Form.Select>
              <Form.TextArea
                field="source_text" label="故事内容" rows={9}
                placeholder="粘贴故事、小说或剧情大纲（支持中英文，建议 500–5000 字）"
                rules={[{ required: true, message: '请输入故事内容' }]}
              />
              <Space align="center">
                <Button colorful theme="solid" htmlType="submit" type="primary" loading={creating}>
                  创作剧本
                </Button>
                <Text type="tertiary" size="small">剧本生成后进入审核,通过后回此页选它创建视频</Text>
              </Space>
            </Form>
          </Tabs.TabPane>
        </Tabs>
      </Card>
    </PageShell>
  )
}
