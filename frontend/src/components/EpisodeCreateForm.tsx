import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Toast, Form, Card, Typography, Space, Tabs, Empty, SideSheet, Descriptions, MarkdownRender } from '@douyinfe/semi-ui'
import {
  episodesApi, scriptsApi, storiesApi, configApi,
  CastPending, CreateEpisodeData, Script, Story, LLMModelOption, VideoModelOption,
} from '../services/api'
import { PageLoading } from './PageShell'
import CastReviewPanel, { CastDecision } from './CastReviewPanel'
import VideoModelFields, { splitVideoModel, videoInitValues } from './VideoModelFields'

const { Text } = Typography

// 集级目标时长(秒),建集时可选;驱动分镜总时长收敛(后端 storyboard_director)。
const TARGET_SECONDS = [
  // 30 秒是"短集":后端会把单镜下限从 5s 放宽到 3s(见 workflow/constants.min_shot_duration),
  // 否则 5s 下限下只容得 6 个镜头,装不下一条完整的起承转合。
  { value: 30, label: '30 秒' },
  { value: 60, label: '60 秒' },
  { value: 90, label: '90 秒' },
  { value: 120, label: '120 秒' },
  { value: 180, label: '180 秒' },
]

export default function EpisodeCreateForm({ projectId }: { projectId: string }) {
  const navigate = useNavigate()
  const [videoModels, setVideoModels] = useState<VideoModelOption[]>([])
  const [llmModels, setLlmModels] = useState<LLMModelOption[]>([])
  const [llmDefault, setLlmDefault] = useState<string>('')
  const [videoDefault, setVideoDefault] = useState<string>('')
  const [modelsLoading, setModelsLoading] = useState(true)
  const [stories, setStories] = useState<Story[]>([])
  const [storiesLoading, setStoriesLoading] = useState(true)
  // 选中故事后才拉它的方案:方案只有正文能区分彼此,而一次性把所有故事的方案都取回来
  // 既拿不到正文摘要(响应会很大),也无从按故事分组展示
  const [pickedStory, setPickedStory] = useState<string>('')
  const [scripts, setScripts] = useState<Script[]>([])
  const [scriptsLoading, setScriptsLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [previewOpen, setPreviewOpen] = useState(false)
  /** 待确认角色时暂存这次提交,确认后接着建剧本 + 建集(见 submitFromStory)。 */
  const [storyDraft, setStoryDraft] = useState<{
    values: any; sourceText: string
    story_analysis: Record<string, any> | null; pending: CastPending[]
  } | null>(null)

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

  // 不按作品过滤:故事是全局可复用的,散稿(project_id=null)不属于任何作品,
  // 按 projectId 过滤会让它对每个作品的「新建一集」都不可见。归属改为在选项里标注。
  // 只列顶层原文 —— 片段属于其父原文的内部结构,平铺会把一本小说的 N 段与别的故事混在一起。
  useEffect(() => {
    setStoriesLoading(true)
    storiesApi.list({ topLevelOnly: true })
      .then(setStories)
      .catch(() => Toast.error('加载故事失败'))
      .finally(() => setStoriesLoading(false))
  }, [])

  /** 拉某段原文的改编方案。换故事时清空上一批 —— 留着会让用户以为新故事也有那些方案。 */
  const loadScriptsOf = (storyId: string) => {
    setPickedStory(storyId)
    setScripts([])
    if (!storyId) return
    setScriptsLoading(true)
    scriptsApi.list({ storyId })
      .then(setScripts)
      .catch(() => Toast.error('加载改编方案失败'))
      .finally(() => setScriptsLoading(false))
  }

  /** 有改编方案的故事。「复用已有方案」tab 只列它们 ——
   *  没有方案的故事在那个 tab 里本就选不出任何东西,列出来只会走到死路
   *  (选完发现第二个下拉是空的,而正确做法是换 tab 从原文开拍)。 */
  const storiesWithScripts = stories.filter(s => (s.script_count ?? 0) > 0)

  /** 故事选项的辅助说明:归属 + 已有几个方案。
   *
   * 同名故事(「第 1 集」这类标题很常见)只靠标题分不开,而"有没有方案"决定了选它之后
   * 第二个下拉是不是空的 —— 提前标出来,免得用户选完才发现无从继续。 */
  const storyHint = (s: Story) => {
    const owner = s.project_title || '未归属作品'
    return s.script_count ? `${owner} · ${s.script_count} 个方案` : `${owner} · 暂无方案`
  }

  /** 方案的一句话摘要。方案之间的差别全在正文里 —— 只给标题的话
   * 「悬疑版」「温情版」这种同源方案在下拉里长得一模一样。 */
  const scriptHint = (s: Script) =>
    (s.content || '').replace(/\s+/g, ' ').slice(0, 60) || '（无正文）'

  const groupBy = <T extends { provider: string }>(items: T[]) =>
    items.reduce<Record<string, T[]>>((acc, m) => { ;(acc[m.provider] ??= []).push(m); return acc }, {})
  const llmGroups = groupBy(llmModels)

  const commonInit = {
    // 默认模型只认后端下发的 default(唯一权威);前端不设写死的兜底模型名,
    // 那会与用户在「模型管理」标的默认模型分叉。
    llm_model: llmDefault,
    ...videoInitValues(videoModels, videoDefault),
    use_keyframes: false,
    target_seconds: 120,
  }
  // 不预选故事/方案:预选一个会让"我确认过这是我要的"与"表单默认恰好如此"无法区分,
  // 而这一步选错要到成片才发现。
  const episodeInit = { ...commonInit }
  const storyInit = { ...commonInit }

  /** 集级配置(不含"拍什么" —— 两条入口各自补 story_id 或 script_id)。 */
  const baseData = (values: any): Omit<CreateEpisodeData, 'story_id' | 'script_id'> => ({
    title: values.title.trim(),
    llm_model: values.llm_model,
    ...splitVideoModel(values, videoModels),
    resolution: values.resolution,
    aspect_ratio: values.aspect_ratio,
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

  // 入口一:复用已有方案 → 直接建集(图内从分镜开始)。
  // 只传 script_id:原文由后端经该方案的 story_id 解析(规范 4,前端不搬运两个 id)。
  const submitFromScript = (values: any) =>
    doCreate({ ...baseData(values), script_id: values.script_id })

  /** 拍一段原文 → 建集。原文有两个来源,分别处理:
   *
   * · 选了库里已有的 → 直接建集(它的角色在入库时已确认过,不重复问一遍)
   * · 粘了一段新的   → 先落成原文(内容的源头)再建集;有名单外角色时停下确认身份
   *
   * 两条都不建剧本 —— 剧本正文正是流水线要产出的东西,提前建一个空方案会让
   * 剧本库长满没有正文的行。 */
  const submitFromStory = async (values: any) => {
    if (!projectId) return
    // 选了已有故事:它已在库里(角色也已确认),直接开拍。这是本轮修的缺陷 ——
    // 逼用户为一段已存在的原文重新粘一遍,库里就会多出一份重复的原文。
    if (values.story_id) {
      await doCreate({ ...baseData(values), story_id: values.story_id })
      return
    }
    const sourceText = (values.source_text || '').trim()
    if (!sourceText) {
      Toast.error('请选择一段已有故事，或粘一段新的')
      return
    }
    setCreating(true)
    try {
      const r = await storiesApi.analyze(projectId, sourceText, values.llm_model)
      if (r.pending.length > 0) {
        // 待确认清单交给确认面板;确认后由 finishFromStory 继续建原文 + 建集
        setStoryDraft({ values, sourceText, story_analysis: r.story_analysis, pending: r.pending })
        return
      }
      await createStoryThenEpisode(values, sourceText, r.story_analysis, {})
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setCreating(false)
    }
  }

  const createStoryThenEpisode = async (
    values: any, sourceText: string,
    storyAnalysis: Record<string, any> | null,
    cast: Record<string, CastDecision>,
  ) => {
    if (!projectId) return
    const story = await storiesApi.create({
      project_id: projectId, title: values.title.trim(),
      content: sourceText, story_analysis: storyAnalysis, cast,
    })
    // 集拍这段原文(story_id 是集的锚点);没有起始方案 —— 剧本由流水线产出
    await doCreate({ ...baseData(values), story_id: story.id })
  }

  const finishFromStory = async (cast: Record<string, CastDecision>) => {
    if (!storyDraft) return
    setCreating(true)
    try {
      await createStoryThenEpisode(
        storyDraft.values, storyDraft.sourceText, storyDraft.story_analysis, cast)
      setStoryDraft(null)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setCreating(false)
    }
  }

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
      <VideoModelFields formApi={formApi} models={videoModels} />
      <Form.Select field="target_seconds" label="目标时长">
        {TARGET_SECONDS.map(o => (
          <Form.Select.Option key={o.value} value={o.value}>{o.label}</Form.Select.Option>
        ))}
      </Form.Select>
      <Form.Switch field="use_keyframes" label="关键帧先行（先出静态图审核再生成视频）" />
    </>
  )

  if (modelsLoading || storiesLoading) {
    return <PageLoading />
  }

  return (
    <Card>
      <Tabs type="line">
        <Tabs.TabPane tab="拍一段故事" itemKey="story">
          {storyDraft ? (
            <Space vertical align="start">
              <CastReviewPanel
                pending={storyDraft.pending}
                loading={creating}
                onConfirm={finishFromStory}
              />
              <Button onClick={() => setStoryDraft(null)}>返回修改故事</Button>
            </Space>
          ) : (
          <Form initValues={storyInit} onSubmit={submitFromStory} labelPosition="top">
            {({ formApi }: any) => (
              <>
                <Form.Input
                  field="title" label="本集标题" placeholder="给这一集起个名字"
                  rules={[{ required: true, message: '请输入本集标题' }]}
                />
                {/* 原文可以是库里已有的,也可以是刚粘的 —— 两者都是"拍一段原文",
                    故同属本 tab。只留"粘一段"的话,已入库的故事要重新粘一遍
                    (库里那条还在,于是同一段原文有了两份)。 */}
                <Form.Select
                  field="story_id" label="拍哪段原文"
                  placeholder={stories.length ? '选择已有故事，或在下方粘一段新的' : '还没有已入库的故事，请在下方粘一段'}
                  disabled={stories.length === 0}
                  showClear
                  filter
                  onChange={() => {
                    // 选了已有故事就不该再留着粘贴框里的内容:两者同时有值时
                    // "到底拍哪一段"没有答案,而提交只能取一个。
                    formApi.setValue('source_text', undefined)
                  }}
                >
                  {stories.map(s => (
                    <Form.Select.Option key={s.id} value={s.id}>
                      {`${s.title} · ${storyHint(s)}`}
                    </Form.Select.Option>
                  ))}
                </Form.Select>
                {/* 选了已有故事时隐藏粘贴框 —— 留着它等于摆一个填了也不生效的输入框。
                    两者是"二选一",不是"都填"。 */}
                {!formApi.getValue('story_id') && (
                  <Form.TextArea
                    field="source_text" label="或粘一段新故事" rows={9}
                    placeholder="粘贴故事、小说或剧情大纲（支持中英文，建议 500–5000 字）"
                    // 校验挂在**字段**上,不靠提交时弹 toast:两者都拦得住空提交,
                    // 但 toast 是一闪而过的全局提示,离出错的输入框很远,而且不留痕 ——
                    // 用户(尤其是内容被别处操作清空、自己没察觉时)只会看到"点了没反应"。
                    // 字段级错误就停在框下面,指着该填的地方。
                    rules={[{
                      validator: (_r: unknown, v: string) =>
                        !!(v || '').trim() || !!formApi.getValue('story_id'),
                      message: '请选择一段已有故事，或在此粘一段新的',
                    }]}
                  />
                )}
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
          )}
        </Tabs.TabPane>

        <Tabs.TabPane tab="拍一个已有方案" itemKey="pick">
          {storiesWithScripts.length === 0 ? (
            <Empty description="还没有可复用的改编方案。先在「拍一段故事」页开拍，剧本通过审核后即可存为方案。" />
          ) : (
            <Form initValues={episodeInit} onSubmit={submitFromScript} labelPosition="top">
              {({ formApi }: any) => (
                <>
                  <Form.Input
                    field="title" label="本集标题" placeholder="例如：第 1 集 · 深夜来客"
                    rules={[{ required: true, message: '请输入本集标题' }]}
                  />
                  {/* 分两步选:先定"拍哪段原文",再定"用它的哪一版改编"。
                      不用级联:方案彼此只有正文能区分,而级联的叶子只放得下一个标题
                      (「悬疑版」「温情版」在下拉里长得一模一样)。分开后第二个下拉
                      能给每个方案带上正文摘要。 */}
                  <Form.Select
                    field="story_id" label="拍哪段原文"
                    placeholder="选择一段故事"
                    filter
                    rules={[{ required: true, message: '请选择原文' }]}
                    onChange={v => {
                      // 换故事必须清掉已选方案 —— 留着会提交上一段原文的方案,
                      // 而两个字段看起来是一致的(校验也过),错到成片才发现。
                      formApi.setValue('script_id', undefined)
                      loadScriptsOf((v as string) || '')
                    }}
                  >
                    {storiesWithScripts.map(s => (
                      <Form.Select.Option key={s.id} value={s.id}>
                        {`${s.title} · ${storyHint(s)}`}
                      </Form.Select.Option>
                    ))}
                  </Form.Select>
                  {/* 未选故事前禁用 —— 此时它没有任何可选项,能点开只会让人以为加载坏了 */}
                  <Form.Select
                    field="script_id" label="用哪一版改编"
                    placeholder={pickedStory ? '选择一个改编方案' : '请先选择原文'}
                    disabled={!pickedStory}
                    loading={scriptsLoading}
                    filter
                    rules={[{ required: true, message: '请选择改编方案' }]}
                    extraTextPosition="middle"
                    extraText={
                      <Button
                        size="small"
                        disabled={!formApi.getValue('script_id')}
                        onClick={() => setPreviewOpen(true)}
                      >预览这个方案</Button>
                    }
                  >
                    {scripts.map(s => (
                      <Form.Select.Option key={s.id} value={s.id}>
                        {`${s.title} — ${scriptHint(s)}`}
                      </Form.Select.Option>
                    ))}
                  </Form.Select>
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
                              { key: '改编自', value: s.story_title || '-' },
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
  )
}
