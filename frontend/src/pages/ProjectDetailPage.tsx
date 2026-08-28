import { useEffect, useState, useRef, useCallback, ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Steps, Button, Tag, Spin, Toast, TextArea, Table, Modal, Typography, Card, Row, Col,
  Space, Descriptions, List, Banner, Select, Checkbox,
} from '@douyinfe/semi-ui'
import { workflowApi, filesApi, episodesApi, charactersApi, createWebSocket, WorkflowStatus, Episode } from '../services/api'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import PreviewImage from '../components/PreviewImage'
import ReferencesPanel, { RefEntry, mergeServerRefs } from '../components/ReferencesPanel'
import VideoPlayer from '../components/VideoPlayer'
import ShotArtifactPanel from '../components/ShotArtifactPanel'
import ScreenplayReviewPanel from '../components/ScreenplayReviewPanel'
import CastReviewPanel, { CastDecision } from '../components/CastReviewPanel'

const { Title, Text, Paragraph } = Typography

// 流水线步骤由后端下发(status.pipeline,单一真相见后端 pipeline_steps.py);前端只渲染。
// 每个步骤对应右侧一个内容面板(PANELS),不再把所有阶段的内容堆在一页里。

const STATUS_LABEL: Record<string, string> = {
  created: '待启动', starting: '启动中', analyzing: '故事分析中', story_analyzed: '分析完成',
  cast_resolved: '角色对齐中', cast_review: '确认角色', cast_confirmed: '角色已确认',
  screenplay_written: '剧本生成中', screenplay_review: '审核剧本', screenplay_approved: '剧本通过',
  screenplay_revision_requested: '剧本修改中', storyboard_ready: '分镜完成',
  prompts_ready: 'Prompt生成中', prompts_review: '审核Prompt', prompts_approved: 'Prompt确认',
  prompts_revision_requested: 'Prompt修改中', videos_generated: '视频完成',
  looks_assigned: '造型指派中', look_review: '审核服装造型', looks_approved: '造型确认',
  looks_revision_requested: '造型重排中',
  keyframes_ready: '关键帧生成中', keyframes_review: '审核关键帧', keyframes_approved: '关键帧确认',
  keyframes_revision_requested: '关键帧重生成中',
  assembly_failed: '合成失败', completed: '制作完成', failed: '失败',
}

// 成片时长由后端按各镜头时长求和下发(唯一真相),前端只格式化,不自己算。
const fmtDuration = (sec?: number) =>
  sec ? ` · 约 ${Math.floor(sec / 60)} 分 ${sec % 60} 秒` : ''

// 金额均为估算,币种人民币;未定价用量存在时不展示可能误导的数字。
const fmtCost = (n?: number, unpriced?: boolean) =>
  unpriced ? '未定价' : (n != null ? `¥${n.toFixed(2)}（估算）` : undefined)

/** 把若干张卡片竖排成整宽列 —— 卡片宽度统一靠这里(Col span=24),不靠内联样式。 */
function CardColumn({ cards }: { cards: (ReactNode | null | false)[] }) {
  const visible = cards.filter(Boolean)
  if (visible.length === 0) return null
  return (
    <Row gutter={[0, 16]}>
      {visible.map((card, i) => <Col span={24} key={i}>{card}</Col>)}
    </Row>
  )
}

export default function ProjectDetailPage() {
  const { episodeId } = useParams<{ episodeId: string }>()
  const navigate = useNavigate()
  const [episode, setEpisode] = useState<Episode | null>(null)
  const [status, setStatus] = useState<WorkflowStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [editedPrompts, setEditedPrompts] = useState<Record<string, string>>({})
  const [editedNegativePrompts, setEditedNegativePrompts] = useState<Record<string, string>>({})
  const [lookAssignmentsDraft, setLookAssignmentsDraft] = useState<Record<string, Record<string, string>>>({})
  const [looksCatalog, setLooksCatalog] = useState<Record<string, { id: string; name: string }[]>>({})
  const [regenSelection, setRegenSelection] = useState<string[]>([])
  const [reviewNotes, setReviewNotes] = useState('')
  const reviewNotesRef = useRef('')
  const setReviewNotesAndRef = (v: string) => { setReviewNotes(v); reviewNotesRef.current = v }
  const [starting, setStarting] = useState(false)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [editingStory, setEditingStory] = useState(false)
  const [storyText, setStoryText] = useState('')
  const [savingStory, setSavingStory] = useState(false)
  const [refEntries, setRefEntries] = useState<RefEntry[]>([])
  // 用户手动点开的步骤;null = 跟随流水线当前步
  const [selectedStep, setSelectedStep] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const lastSeqRef = useRef<number>(0)
  const lookDraftSeeded = useRef(false)
  const projectStatusRef = useRef<string>('created')

  const projectId = episode?.project_id

  const refreshStatus = useCallback(async () => {
    if (!episodeId) return
    // Workflow status carries project_id, which we need before we can load the episode.
    const wfStatus = await workflowApi.status(episodeId).catch(() => null)
    const [ep, serverRefs] = await Promise.all([
      wfStatus?.project_id
        ? episodesApi.get(wfStatus.project_id, episodeId).catch(() => null)
        : Promise.resolve(null),
      filesApi.getReferences(episodeId).catch(() => null),
    ])
    if (ep) setEpisode(ep)
    projectStatusRef.current = ep?.status ?? 'created'
    if (wfStatus) setStatus(wfStatus)
    // 参考图清单(含未上传占位与 ref_type)整份由后端下发,前端不再合并/推断类型。
    // 拉取失败时保留现有清单,不把面板刷空。
    if (serverRefs) setRefEntries(cur => mergeServerRefs(serverRefs, cur))
  }, [episodeId])

  useEffect(() => {
    if (!episodeId) return
    refreshStatus().finally(() => setLoading(false))
    const ws = createWebSocket(episodeId, (event) => {
      if (typeof event.seq === 'number') lastSeqRef.current = Math.max(lastSeqRef.current, event.seq)
      if (event.type === 'stage_change') refreshStatus()
      if (event.type === 'error') Toast.error('工作流错误: ' + (event.data?.payload_json?.message || ''))
    }, lastSeqRef.current)
    wsRef.current = ws
    ws.onclose = (e) => {
      const INACTIVE = ['created', 'completed', 'failed']
      if (!e.wasClean && !INACTIVE.includes(projectStatusRef.current)) {
        Toast.warning({ content: '实时连接已断开，请刷新页面获取最新状态', duration: 0 })
      }
    }
    return () => { ws.onclose = null; ws.close() }
  }, [episodeId, refreshStatus])

  // 进入 look_review 时:用 status 的指派作草稿初值,并拉角色 Looks 供下拉选择。
  // 只在「刚进入」时播种,避免后续 status 刷新覆盖用户正在编辑的选择。
  useEffect(() => {
    if (status?.paused_at !== 'look_review') {
      lookDraftSeeded.current = false
      return
    }
    if (lookDraftSeeded.current) return
    lookDraftSeeded.current = true
    setLookAssignmentsDraft(status.look_assignments || {})
    if (!projectId) return
    let cancelled = false
    charactersApi.list(projectId)
      .then(async chars => {
        const pairs = await Promise.all(chars.map(async c => {
          const looks = await charactersApi.listLooks(projectId, c.id).catch(() => [])
          return [c.name, looks.map(lk => ({ id: lk.id, name: lk.name }))] as const
        }))
        if (!cancelled) setLooksCatalog(Object.fromEntries(pairs))
      })
      .catch(() => { if (!cancelled) setLooksCatalog({}) })
    return () => { cancelled = true }
  }, [status?.paused_at, status?.look_assignments, projectId])

  // 参考图瞬时态(上传中/本地预览)——不落库
  const patchRef = useCallback((key: string, patch: Partial<RefEntry>) => {
    setRefEntries(prev => prev.map(e => e.key === key ? { ...e, ...patch } : e))
  }, [])

  // 参考图落库:整表提交后用后端返回的清单回填(类型与占位都以后端为准)
  const persistRefs = useCallback(async (next: RefEntry[]) => {
    if (!episodeId) return
    setRefEntries(next)
    try {
      const saved = await filesApi.updateReferences(
        episodeId, next.map(({ key, ref_type, image_url }) => ({ key, ref_type, image_url })))
      setRefEntries(cur => mergeServerRefs(saved, cur))
    } catch {
      Toast.error('参考图保存失败')
      const server = await filesApi.getReferences(episodeId).catch(() => null)
      if (server) setRefEntries(cur => mergeServerRefs(server, cur))
    }
  }, [episodeId])

  const handleStart = async () => {
    if (!episodeId || starting) return
    setStarting(true)
    try {
      // 参考图在每次增删改时已落库,这里无需再提交一遍
      await workflowApi.start(episodeId)
      Toast.info('制作流程已启动')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('启动失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setStarting(false)
    }
  }

  const handleApproveScreenplay = async (approved: boolean) => {
    if (!episodeId || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(episodeId, { approved, notes: reviewNotesRef.current })
      setReviewNotesAndRef('')
      Toast.success(approved ? '剧本已通过' : '已提交修改意见')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  const handleSaveStory = async () => {
    if (!projectId || !episodeId || savingStory) return
    if (!storyText.trim()) { Toast.error('故事内容不能为空'); return }
    setSavingStory(true)
    try {
      await episodesApi.update(projectId, episodeId, { raw_input: storyText })
      Toast.success('已保存')
      setEditingStory(false)
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSavingStory(false)
    }
  }

  const handleConfirmCast = async (cast: Record<string, CastDecision>) => {
    if (!episodeId || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(episodeId, { approved: true, cast })
      Toast.success('角色已确认')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  const handleApprovePrompts = async (approved: boolean) => {
    if (!episodeId || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(episodeId, {
        approved, notes: reviewNotesRef.current,
        edited_prompts: editedPrompts, edited_negative_prompts: editedNegativePrompts,
      })
      setReviewNotesAndRef('')
      Toast.success(approved ? '确认完成，开始生成视频' : '已提交修改意见')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  const handleApproveLooks = async (approved: boolean) => {
    if (!episodeId || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(episodeId, { approved, assignments: lookAssignmentsDraft })
      Toast.success(approved ? '造型已确认' : '已退回重排')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  const handleApproveKeyframes = async (approved: boolean) => {
    if (!episodeId || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(episodeId, { approved, regenerate_shot_ids: regenSelection })
      if (!approved) setRegenSelection([])
      Toast.success(approved ? '关键帧已确认，开始生成视频' : '已提交重生成')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  if (loading) return <PageLoading />

  if (!episode) return (
    <PageEmpty variant="error" title="项目未找到">
      <Button type="tertiary" onClick={() => navigate('/')}>返回列表</Button>
    </PageEmpty>
  )

  const stage = status?.current_stage || episode.status
  const isPaused = status?.db_status === 'paused'
  const pausedAt = status?.paused_at || null
  const pipeline = status?.pipeline
  const steps = pipeline?.steps ?? []
  // 流水线真实进度(驱动各步状态色)与用户正在查看的步(驱动右侧面板)是两件事
  const progressIndex = Math.max(0, steps.findIndex(s => s.key === pipeline?.current))
  const activeKey = selectedStep ?? pipeline?.current ?? steps[0]?.key ?? null
  const activeIndex = Math.max(0, steps.findIndex(s => s.key === activeKey))
  const isAtScreenplayReview = isPaused && pausedAt === 'screenplay_review'
  const isAtPromptsReview = isPaused && pausedAt === 'prompts_review'
  const isAtLookReview = isPaused && pausedAt === 'look_review'
  const isAtKeyframesReview = isPaused && pausedAt === 'keyframes_review'
  const PAUSED_OR_TERMINAL = ['created', 'completed', 'failed', 'assembly_failed']
  const isRunning = !PAUSED_OR_TERMINAL.includes(stage)
    && !isAtScreenplayReview && !isAtPromptsReview && !isAtLookReview && !isAtKeyframesReview
  const stepStatus = (i: number): 'process' | 'finish' | 'error' | 'warning' | undefined => {
    if (pipeline?.current == null) return undefined
    if (i < progressIndex) return 'finish'
    // 不显式返回 'wait':Semi 在 status 缺省时按 index > current 自己推导成 wait
    // (semi-ui/lib/es/steps/basicSteps.js),写死一遍属于重复实现同一规则。
    if (i > progressIndex) return undefined
    if (episode.status === 'failed' || stage === 'assembly_failed') return 'error'
    if (isAtScreenplayReview || isAtPromptsReview || isAtLookReview || isAtKeyframesReview) return 'warning'
    if (!isRunning) return 'finish'
    return 'process'
  }
  // 点回"流水线正在跑的那一步" = 恢复自动跟随;点其它步则钉住,不被后台推进抢走。
  // 未推进到的步不响应:那边没有内容可看,切过去只会得到一个空面板。
  const handleStepChange = (i: number) => {
    const key = steps[i]?.key
    if (!key) return
    if (pipeline?.current != null && i > progressIndex) return
    setSelectedStep(key === pipeline?.current ? null : key)
  }

  const revisionModal = (title: string, placeholder: string, onOk: () => void) => {
    setReviewNotesAndRef('')
    Modal.confirm({
      title,
      content: <TextArea placeholder={placeholder} rows={4} onChange={v => setReviewNotesAndRef(v)} />,
      onOk,
      onCancel: () => setReviewNotesAndRef(''),
    })
  }

  // ── 各步骤面板 ──────────────────────────────────────────────────────────
  const startCard = episode.status === 'created' ? (
    <Card title="项目准备就绪">
      <Row gutter={[0, 16]}>
        <Col span={24}>
          <Paragraph type="tertiary">
            AI 将自动完成故事分析、剧本创作、分镜规划、Prompt 生成和视频合成。
            您可提前上传角色/背景参考图，也可在流程启动后随时补充。
          </Paragraph>
        </Col>
        <Col span={24}>
          <Button colorful theme="solid" type="primary" loading={starting} onClick={handleStart}>
            开始制作
          </Button>
        </Col>
      </Row>
    </Card>
  ) : null

  // 用户自己输入的原始故事,是这一集所有产出的源头,必须全程可见。
  // 只在 created 态可编辑:开拍后故事分析与剧本都由这段原文推导而来,改它会让产出与源头不符
  // (要改内容走剧本审核的 AI 改写/手动编辑,那条路有版本树)。
  const storyCard = episode.raw_input ? (
    <Card
      title="故事内容"
      headerExtraContent={
        episode.status === 'created' ? (
          editingStory ? (
            <Space>
              <Button onClick={() => setEditingStory(false)}>取消</Button>
              <Button type="primary" loading={savingStory} onClick={handleSaveStory}>保存</Button>
            </Space>
          ) : (
            <Button onClick={() => { setStoryText(episode.raw_input ?? ''); setEditingStory(true) }}>
              编辑
            </Button>
          )
        ) : (
          <Text type="tertiary">已开拍，如需调整请在剧本审核阶段改写</Text>
        )
      }
    >
      {editingStory
        ? <TextArea value={storyText} onChange={setStoryText} rows={12} />
        : <Paragraph>{episode.raw_input}</Paragraph>}
    </Card>
  ) : null

  const referencesCard = (
    <Card title="参考图片" headerExtraContent={<Text type="tertiary">启动后亦可修改</Text>}>
      <ReferencesPanel
        projectId={projectId ?? ''}
        entries={refEntries}
        onPersist={persistRefs}
        onPatch={patchRef}
      />
    </Card>
  )

  const storyAnalysisCard = status?.story_analysis ? (
    <Card title="故事分析">
      <Row gutter={[0, 16]}>
        <Col span={24}>
          <Descriptions
            data={[
              { key: '类型', value: status.story_analysis.genre || '-' },
              { key: '基调', value: status.story_analysis.tone || '-' },
              { key: '主题', value: status.story_analysis.themes?.join('、') || '-' },
            ]}
          />
        </Col>
        {status.story_analysis.plot_summary && (
          <Col span={24}>
            <Text type="tertiary" strong>故事梗概</Text>
            <Paragraph type="tertiary">{status.story_analysis.plot_summary}</Paragraph>
          </Col>
        )}
        {status.story_analysis.characters?.length > 0 && (
          <Col span={24}>
            <Row gutter={[0, 8]}>
              <Col span={24}><Text type="tertiary" strong>角色</Text></Col>
              {status.story_analysis.characters.map((c: { name: string; appearance?: string; personality?: string }) => {
                const refEntry = refEntries.find(e => e.key === c.name && e.ref_type === 'character')
                return (
                  <Col span={24} key={c.name}>
                    <Card title={c.name}>
                      <Space align="start" wrap>
                        {refEntry?.image_url && (
                          <PreviewImage src={refEntry.localPreview || refEntry.image_url} alt={c.name} width={44} height={44} />
                        )}
                        <Space vertical align="start">
                          {c.appearance && <Text type="tertiary">外貌：{c.appearance}</Text>}
                          {c.personality && <Text type="tertiary">性格：{c.personality}</Text>}
                        </Space>
                      </Space>
                    </Card>
                  </Col>
                )
              })}
            </Row>
          </Col>
        )}
      </Row>
    </Card>
  ) : null

  // 待确认清单非空即表示停在"确认角色"步(判据在后端,前端只消费)
  const castCard = (status?.cast_pending?.length ?? 0) > 0 ? (
    <CastReviewPanel
      pending={status?.cast_pending ?? []}
      loading={reviewLoading}
      onConfirm={handleConfirmCast}
    />
  ) : null

  const screenplayCard = status?.screenplay ? (
    <ScreenplayReviewPanel
      episodeId={episodeId ?? ''}
      screenplay={status.screenplay}
      versions={status.screenplay_versions}
      current={status.screenplay_version_current}
      isReviewing={isAtScreenplayReview}
      reviewLoading={reviewLoading}
      onApprove={handleApproveScreenplay}
      onReject={() => revisionModal('提交修改意见', '请描述需要修改的内容...', () => handleApproveScreenplay(false))}
      onApplied={refreshStatus}
    />
  ) : null

  const storyboardCard = status?.shots && status.shots.length > 0 ? (
    <Card title={`分镜脚本 · ${status.shots.length} 个镜头${fmtDuration(status.total_duration_seconds)}`}
      headerExtraContent={status.duration_over_target
        ? <Text type="warning">总时长超出目标，建议退回重新生成</Text> : undefined}>
      <Table size="small" dataSource={status.shots} rowKey="shot_id" pagination={false}
        expandRowByClick
        expandedRowRender={(row?: { location?: string; action?: string; dialogue?: string }) => (
          <Space vertical align="start">
            <Space>
              <Text type="tertiary" strong>地点：</Text>
              <Text type="tertiary">{row?.location || '（未指定）'}</Text>
            </Space>
            <Space>
              <Text type="tertiary" strong>动作：</Text>
              <Text type="tertiary">{row?.action || '（无动作描述）'}</Text>
            </Space>
            <Space>
              <Text type="tertiary" strong>台词：</Text>
              <Text type="tertiary">{row?.dialogue || '（无台词）'}</Text>
            </Space>
          </Space>
        )}
        columns={[
          { title: '场景', dataIndex: 'scene_number', width: 60 },
          { title: '镜头', dataIndex: 'shot_number', width: 60 },
          { title: '景别', dataIndex: 'shot_type', width: 80 },
          { title: '运镜', dataIndex: 'camera_movement', width: 80 },
          { title: '时长', dataIndex: 'duration_seconds', width: 60, render: (v: number) => `${v}s` },
          { title: '描述', dataIndex: 'description' },
          { title: '人物', dataIndex: 'characters', render: (v: string[]) => v?.join(', ') || '-' },
        ]}
      />
    </Card>
  ) : null

  const lookAssignments = isAtLookReview ? lookAssignmentsDraft : (status?.look_assignments || {})
  const looksCard = Object.keys(lookAssignments).length > 0 ? (
    <Card title="审核服装造型（场景 → 角色 → 造型）">
      <Row gutter={[0, 12]}>
        {isAtLookReview && (
          <Col span={24}>
            <Banner
              type="info"
              fullMode={false}
              closeIcon={null}
              description="确认每个场景中各角色所穿的造型，可调整后确认，或退回重新指派"
            />
          </Col>
        )}
        {Object.entries(lookAssignments).map(([scene, byName]) => (
          <Col span={24} key={scene}>
            <Space vertical align="start">
              <Text strong>{`场景 ${scene}`}</Text>
              {Object.entries(byName).map(([name, lookId]) => (
                <Space key={name} align="center">
                  <Text>{name}</Text>
                  {isAtLookReview ? (
                    <Select
                      value={lookId}
                      onChange={v => setLookAssignmentsDraft(prev => ({
                        ...prev, [scene]: { ...prev[scene], [name]: v as string },
                      }))}
                    >
                      {(looksCatalog[name] || []).map(lk => (
                        <Select.Option key={lk.id} value={lk.id}>{lk.name}</Select.Option>
                      ))}
                    </Select>
                  ) : (
                    <Text type="tertiary">{lookId}</Text>
                  )}
                </Space>
              ))}
            </Space>
          </Col>
        ))}
        {isAtLookReview && (
          <Col span={24}>
            <Space>
              <Button type="primary" theme="solid" loading={reviewLoading}
                onClick={() => handleApproveLooks(true)}>确认造型</Button>
              <Button loading={reviewLoading} onClick={() => handleApproveLooks(false)}>退回重排</Button>
            </Space>
          </Col>
        )}
      </Row>
    </Card>
  ) : null

  const promptsCard = status?.prompts && status.prompts.length > 0 ? (
    <Card
      title={`视频 Prompt · ${status.prompts.length} 个`}
      headerExtraContent={isAtPromptsReview && (
        <Space>
          <Button type="primary" size="small" loading={reviewLoading} onClick={() => handleApprovePrompts(true)}>
            全部确认，开始生成视频
          </Button>
          <Button type="warning" size="small" loading={reviewLoading}
            onClick={() => revisionModal('提交修改意见', '请描述 Prompt 需要调整的地方...', () => handleApprovePrompts(false))}
          >退回重新生成</Button>
        </Space>
      )}
    >
      <Row gutter={[0, 8]}>
        {isAtPromptsReview && (
          <Col span={24}>
            <Banner
              type="info"
              fullMode={false}
              closeIcon={null}
              description="请检查并编辑各镜头的 Prompt，确认无误后点击「全部确认」"
            />
          </Col>
        )}
        <Col span={24}>
          <List
            dataSource={status.prompts}
            renderItem={(p: { shot_id: string; prompt_text: string; edited_prompt?: string; negative_prompt?: string; edited_negative_prompt?: string }) => {
              const shot = status.shots?.find((s: { shot_id: string }) => s.shot_id === p.shot_id)
              // 空串是"用户主动清空"的有效值,不能用 || 回落到原始值
              const displayNegative = p.edited_negative_prompt ?? p.negative_prompt
              return (
                <List.Item key={p.shot_id}>
                  <Row gutter={[0, 8]}>
                    <Col span={24}>
                      <Space wrap>
                        {shot && <><Tag>场景{shot.scene_number}-镜头{shot.shot_number}</Tag><Tag color="blue">{shot.shot_type}</Tag><Tag>{shot.duration_seconds}s</Tag></>}
                      </Space>
                    </Col>
                    <Col span={24}>
                      {isAtPromptsReview ? (
                        <TextArea value={editedPrompts[p.shot_id] ?? p.prompt_text} onChange={v => setEditedPrompts(prev => ({ ...prev, [p.shot_id]: v }))} rows={3} />
                      ) : (
                        <Text type="tertiary">{p.edited_prompt || p.prompt_text}</Text>
                      )}
                    </Col>
                    <Col span={24}>
                      {isAtPromptsReview ? (
                        <TextArea
                          value={editedNegativePrompts[p.shot_id] ?? p.negative_prompt ?? ''}
                          onChange={v => setEditedNegativePrompts(prev => ({ ...prev, [p.shot_id]: v }))}
                          rows={2}
                        />
                      ) : (
                        displayNegative ? <Text type="tertiary">负向：{displayNegative}</Text> : null
                      )}
                    </Col>
                  </Row>
                </List.Item>
              )
            }}
          />
        </Col>
      </Row>
    </Card>
  ) : null

  const keyframePrompts = (status?.prompts || []).filter(p => p.keyframe_url)
  const keyframesCard = (isAtKeyframesReview || keyframePrompts.length > 0) ? (
    <Card title={isAtKeyframesReview ? '审核关键帧（勾选要重生成的镜头）' : '关键帧'}>
      <Row gutter={[0, 12]}>
        {isAtKeyframesReview && (
          <Col span={24}>
            <Banner
              type="info"
              fullMode={false}
              closeIcon={null}
              description="确认各镜头关键帧，满意则开始生成视频；不满意可勾选后提交重生成"
            />
          </Col>
        )}
        <Col span={24}>
          <List
            dataSource={status?.prompts || []}
            renderItem={(p: { shot_id: string; prompt_text: string; keyframe_url?: string | null }) => {
              const shot = status?.shots?.find((s: { shot_id: string }) => s.shot_id === p.shot_id)
              return (
                <List.Item
                  key={p.shot_id}
                  header={p.keyframe_url
                    ? <PreviewImage src={p.keyframe_url} alt={p.shot_id} width={96} height={54} />
                    : <Text type="tertiary">无关键帧</Text>}
                  main={
                    <Space vertical align="start">
                      {shot && <Tag>场景{shot.scene_number}-镜头{shot.shot_number}</Tag>}
                      <Text type="tertiary">{p.prompt_text}</Text>
                    </Space>
                  }
                  extra={isAtKeyframesReview && (
                    <Checkbox
                      checked={regenSelection.includes(p.shot_id)}
                      onChange={e => setRegenSelection(prev => e.target.checked
                        ? [...prev, p.shot_id]
                        : prev.filter(x => x !== p.shot_id))}
                    >重生成</Checkbox>
                  )}
                />
              )
            }}
          />
        </Col>
        {isAtKeyframesReview && (
          <Col span={24}>
            <Space>
              <Button type="primary" theme="solid" loading={reviewLoading}
                onClick={() => handleApproveKeyframes(true)}>确认，生成视频</Button>
              <Button loading={reviewLoading} disabled={!regenSelection.length}
                onClick={() => handleApproveKeyframes(false)}>重生成所选</Button>
            </Space>
          </Col>
        )}
      </Row>
    </Card>
  ) : null

  const videosCard = status?.videos && status.videos.length > 0 ? (
    <Card title="视频生成进度">
      <List
        dataSource={status.videos}
        renderItem={(v: { shot_id: string; status: string; local_path?: string; error?: string }) => {
          const shot = status.shots?.find((s: { shot_id: string }) => s.shot_id === v.shot_id)
          return (
            <List.Item key={v.shot_id}>
              <Row gutter={[0, 8]}>
                <Col span={24}>
                  <Space align="center">
                    <Text>场景{shot?.scene_number}-镜头{shot?.shot_number}</Text>
                    <Tag color={v.status === 'succeeded' ? 'green' : v.status === 'failed' ? 'red' : 'blue'}>
                      {v.status === 'succeeded' ? '完成' : v.status === 'failed' ? '失败' : '生成中'}
                    </Tag>
                  </Space>
                </Col>
                {v.status === 'running' && (
                  <Col span={24}>
                    <Space align="center">
                      <Spin size="small" />
                      <Text type="tertiary">生成中...</Text>
                    </Space>
                  </Col>
                )}
                {v.status === 'succeeded' && v.local_path && episodeId && (
                  <Col span={24}>
                    <VideoPlayer
                      src={filesApi.downloadUrl(episodeId, `${v.shot_id}.mp4`)}
                      title={`场景${shot?.scene_number} · 镜头${shot?.shot_number}`}
                    />
                  </Col>
                )}
                {v.status === 'failed' && (
                  <Col span={24}><Text type="danger" size="small">错误: {v.error}</Text></Col>
                )}
                {episodeId && (
                  <Col span={24}>
                    <ShotArtifactPanel episodeId={episodeId} projectId={projectId ?? ''} shotId={v.shot_id} />
                  </Col>
                )}
              </Row>
            </List.Item>
          )
        }}
      />
    </Card>
  ) : null

  const finalCard = status?.assembled_video_path && episodeId ? (
    <Card title="✦ 最终成片">
      <Row gutter={[0, 8]}>
        <Col span={24}><VideoPlayer src={filesApi.exportUrl(episodeId)} title="完整成片" /></Col>
        <Col span={24}>
          <Button colorful theme="solid" type="primary" onClick={() => {
            const a = document.createElement('a')
            a.href = filesApi.exportUrl(episodeId)
            a.download = `${episode.title || 'final'}.mp4`
            a.click()
          }}>
            下载完整视频
          </Button>
        </Col>
      </Row>
    </Card>
  ) : null

  // 步骤 key → 该步的内容面板。加一步 = 在此加一条,不散落在 JSX 里判断阶段。
  // 注意:故事分析与参考图**不在**这里 —— 它们是跨步骤常驻上下文(见下方 contextCards),
  // 挂在某一步下会导致流程一推进就随该步离开屏幕(参考图的"启动后亦可修改"也就成了空话)。
  const PANELS: Record<string, ReactNode> = {
    analysis: <CardColumn cards={[startCard]} />,
    cast: <CardColumn cards={[castCard]} />,
    screenplay: <CardColumn cards={[screenplayCard]} />,
    screenplay_review: <CardColumn cards={[screenplayCard]} />,
    storyboard: <CardColumn cards={[storyboardCard]} />,
    looks: <CardColumn cards={[looksCard]} />,
    prompts: <CardColumn cards={[promptsCard]} />,
    keyframes: <CardColumn cards={[keyframesCard]} />,
    video: <CardColumn cards={[videosCard]} />,
    done: <CardColumn cards={[finalCard, videosCard]} />,
  }
  const activePanel = activeKey ? PANELS[activeKey] : null
  // 跨步骤常驻上下文:全程都该看得见、也该能改的东西,故**不挂进 PANELS**。
  // 故事分析是后续每一步的依据;参考图按设计"启动后亦可修改"(见 api/files.py)。
  // 放进某一步的面板下,流程推进后 activeKey 一变它们就随之离开屏幕。
  const contextCards = <CardColumn cards={[storyCard, referencesCard, storyAnalysisCard]} />

  return (
    <PageShell
      breadcrumb={[
        { label: '作品列表', href: '/' },
        { label: '作品', href: projectId ? `/projects/${projectId}` : undefined },
        { label: episode.title },
      ]}
      title={
        <Space wrap align="center">
          <Title heading={3}>{episode.title}</Title>
          <Tag>第 {episode.episode_number} 集</Tag>
          <Tag color="blue">{{ seedance: 'Seedance 2.0', minimax: 'MiniMax H3' }[episode.video_provider] ?? episode.video_provider}</Tag>
          {episode.script_id && (
            <Text link onClick={() => navigate(`/scripts/${episode.script_id}`)}>源剧本 →</Text>
          )}
          {isRunning && <Tag color="blue">{STATUS_LABEL[stage] || stage}</Tag>}
          {!isRunning && stage !== 'created' && (
            <Text type="tertiary">{STATUS_LABEL[stage] || stage}</Text>
          )}
        </Space>
      }
    >
      <Row gutter={[16, 16]}>
        {/* 左栏:竖向流水线 + 跨步骤常驻信息(成本/错误) */}
        <Col xs={24} md={7} lg={6}>
          <Row gutter={[0, 16]}>
            {steps.length > 0 && (
              <Col span={24}>
                <Card>
                  <Steps direction="vertical" type="basic" current={activeIndex} onChange={handleStepChange}>
                    {steps.map((s, i) => (
                      <Steps.Step
                        key={s.key}
                        title={s.label}
                        description={fmtCost(s.cost, status?.cost_unpriced)}
                        status={stepStatus(i)}
                      />
                    ))}
                  </Steps>
                </Card>
              </Col>
            )}
            {status?.cost_total != null && (
              <Col span={24}>
                <Card title="成本（估算）">
                  <Descriptions
                    data={[
                      { key: 'LLM', value: fmtCost(status.cost_by_kind?.llm, status.cost_unpriced) ?? '—' },
                      { key: '图像', value: fmtCost(status.cost_by_kind?.image, status.cost_unpriced) ?? '—' },
                      { key: '视频', value: fmtCost(status.cost_by_kind?.video, status.cost_unpriced) ?? '—' },
                      { key: '合计', value: fmtCost(status.cost_total, status.cost_unpriced) ?? '—' },
                      { key: 'Token 总数', value: String(status.cost_tokens_total ?? 0) },
                    ]}
                  />
                </Card>
              </Col>
            )}
            {/* 图状态已丢失:后端判定(status.state_lost),前端只提示。
                不提示的话审核面板看着能点,点下去必然失败 —— 那正是这个字段要消除的体验。 */}
            {status?.state_lost && (
              <Col span={24}>
                <Card title="制作状态已丢失">
                  <Space vertical align="start">
                    <Text type="danger">
                      这一集的流程状态已不可恢复（进度记录丢失），无法继续或审核。
                    </Text>
                    <Text type="tertiary">请重置这一集后重新开始制作。</Text>
                  </Space>
                </Card>
              </Col>
            )}
            {episode.error_message && (
              <Col span={24}>
                <Card title="错误信息">
                  <Text type="danger">{episode.error_message}</Text>
                </Card>
              </Col>
            )}
          </Row>
        </Col>

        {/* 右栏:当前步骤的内容 + 跨步骤常驻上下文(故事分析 / 参考图) */}
        <Col xs={24} md={17} lg={18}>
          <Row gutter={[0, 16]}>
            <Col span={24}>
              {activePanel ?? (
                <PageEmpty
                  title="该步骤尚未开始"
                  description="流程推进到这一步后，内容会自动出现在这里"
                />
              )}
            </Col>
            <Col span={24}>{contextCards}</Col>
          </Row>
        </Col>
      </Row>
    </PageShell>
  )
}
