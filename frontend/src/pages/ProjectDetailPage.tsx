import { useEffect, useState, useRef, useCallback, ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Button, Tag, Spin, Toast, TextArea, Table, Modal, Typography, Card, Row, Col,
  Space, Descriptions, List, Banner, Select, Checkbox,
} from '@douyinfe/semi-ui'
import {
  workflowApi, filesApi, episodesApi, charactersApi, storiesApi, assetsApi, createWebSocket,
  WorkflowStatus, Episode, Story,
} from '../services/api'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import PreviewImage from '../components/PreviewImage'
import ReferencesPanel, { RefEntry, mergeServerRefs } from '../components/ReferencesPanel'
import VideoPlayer from '../components/VideoPlayer'
import ShotArtifactPanel from '../components/ShotArtifactPanel'
import ScreenplayReviewPanel from '../components/ScreenplayReviewPanel'
import CastReviewPanel, { CastDecision } from '../components/CastReviewPanel'
import StoryTextPanel from '../components/StoryTextPanel'
import GenerateFromScriptModal from '../components/GenerateFromScriptModal'
import WorkflowSteps from '../components/WorkflowSteps'

const { Title, Text, Paragraph } = Typography

// 流水线步骤由后端下发(status.pipeline,单一真相见后端 pipeline_steps.py);前端只渲染。
// 每个步骤对应右侧一个内容面板(PANELS),不再把所有阶段的内容堆在一页里。

// 光影枚举的展示名。取值权威在后端 workflow/constants.py(Lighting / ColorTemp);
// 这里只做中文展示,不参与任何判断。
const LIGHT_LABEL: Record<string, string> = {
  high_key: '高调', low_key: '低调', natural: '自然光', golden_hour: '黄金时刻',
  blue_hour: '蓝调时刻', tungsten: '钨丝灯', neon: '霓虹', silhouette: '剪影',
  rim_lit: '轮廓光', overcast: '阴天柔光',
}
const TEMP_LABEL: Record<string, string> = {
  warm: '暖', neutral: '中性', cool: '冷', mixed: '冷暖混合',
}

const STATUS_LABEL: Record<string, string> = {
  created: '待启动', starting: '启动中', analyzing: '故事分析中', story_analyzed: '分析完成',
  cast_resolved: '角色对齐中', cast_review: '确认角色', cast_confirmed: '角色已确认',
  screenplay_written: '剧本生成中', screenplay_review: '审核剧本', screenplay_approved: '剧本通过',
  screenplay_revision_requested: '剧本修改中',
  // from_script 集(复用剧本/改编切片)图内直达分镜,起跑就是这个阶段(见
  // pipeline_steps.py 的 storyboard 步 stages);漏了它会让顶部标签裸显英文阶段码。
  storyboard_start: '分镜生成中', storyboard_ready: '分镜完成',
  prompts_ready: 'Prompt生成中', prompts_review: '审核Prompt', prompts_approved: 'Prompt确认',
  prompts_revision_requested: 'Prompt修改中',
  // node 在真正开跑视频生成前落一次(video_generator.py),使"正在生成"独立可观测
  // (与 videos_generated 的"已生成完毕"区分);漏了它会让顶部标签裸显英文阶段码。
  videos_generating: '生成视频中', videos_generated: '视频完成',
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
  const [refEntries, setRefEntries] = useState<RefEntry[]>([])
  // 「从剧本提炼 → 生成」的目标。人物落成 Look 四视图,背景落成参考图 —— 去处不同,
  // 但提炼与生成的流程一致,故共用一个弹窗(见 GenerateFromScriptModal)。
  const [genTarget, setGenTarget] = useState<
    { subject: 'character'; key: string; characterId: string }
    | { subject: 'background'; key: string; prompt: string }
    | null>(null)
  // 故事原文住在源剧本上(集只引用剧本),故本页要多读一次剧本才能展示它
  const [story, setStory] = useState<Story | null>(null)
  // 用户手动点开的步骤;null = 跟随流水线当前步
  const [selectedStep, setSelectedStep] = useState<string | null>(null)
  // 分镜审核态选中的历史版本;null = 当前版本(镜 ScreenplayReviewPanel 的 selectedVersion)
  const [selectedShotsVersion, setSelectedShotsVersion] = useState<number | null>(null)
  const [revertingShots, setRevertingShots] = useState(false)
  // 剧本之后,常驻上下文默认收起(见 contextCards);按卡片各自记展开态,用户可随时点开
  const [openContext, setOpenContext] = useState<Record<string, boolean>>({})
  const toggleContext = (key: string) =>
    setOpenContext(m => ({ ...m, [key]: !m[key] }))
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
    // 原文经集的锚点(story_id)取 —— 不绕源剧本:从故事开跑的集没有起始方案。
    // 拉不到时故事卡不显示,不阻断本页其余内容。
    if (ep?.story_id) {
      const st = await storiesApi.get(ep.story_id).catch(() => null)
      if (st) setStory(st)
    }
    if (wfStatus) {
      setStatus(wfStatus)
      // 用后端下发的水位播种:否则首次以 last_seq=0 连 WS,历史事件会被当增量补拉,
      // 那些早已修掉的旧 error 每次刷新都会重新弹一次 toast。
      if (typeof wfStatus.last_seq === 'number') {
        lastSeqRef.current = Math.max(lastSeqRef.current, wfStatus.last_seq)
      }
    }
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
      // prompt 必须一并提交:它是生成该图的描述,漏掉就等于每次重生成都要重新提炼,
      // 用户改过的措辞也随之丢失(挑字段提交时容易漏,故此处显式列出)
      const saved = await filesApi.updateReferences(
        episodeId,
        next.map(({ key, ref_type, image_url, prompt }) => ({ key, ref_type, image_url, prompt })))
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

  const handleApproveStoryboard = async (approved: boolean) => {
    if (!episodeId || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(episodeId, { approved, notes: reviewNotesRef.current })
      setReviewNotesAndRef('')
      setSelectedShotsVersion(null)
      Toast.success(approved ? '分镜已通过' : '已退回重新生成')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  /** 回退分镜到历史版本(镜 ScreenplayReviewPanel.handleRevert)。 */
  const handleRevertShotsVersion = async (versionIndex: number) => {
    if (!episodeId || revertingShots) return
    setRevertingShots(true)
    try {
      await workflowApi.revertStoryboard(episodeId, versionIndex)
      Toast.success('已恢复到该版本')
      setSelectedShotsVersion(null)
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('恢复失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setRevertingShots(false)
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

  /** 该角色的默认造型(没有则建一套)。
   *
   * 四视图必须落在 Look 上:Character 表没有图片列,下游只认 Look 的四个 *_key。
   * 复用已有默认造型而不是每次新建 —— 否则反复生成会堆出一串同名造型。
   */
  const ensureDefaultLook = async (characterId: string) => {
    const looks = await charactersApi.listLooks(projectId!, characterId)
    return looks.find(l => l.is_default) || looks[0]
      || await charactersApi.createLook(projectId!, characterId,
        { name: '默认造型', is_default: true })
  }

  /** 生成一张图。人物走四视图 sheet(单次生成保证四视图同一人),背景走普通文生图。 */
  const generateForTarget = async (r: { prompt: string; modelId: string; size: string }) => {
    const t = genTarget
    if (!t || !projectId) return ''
    if (t.subject === 'character') {
      const look = await ensureDefaultLook(t.characterId)
      const out = await charactersApi.generateSheet(projectId, t.characterId, look.id,
        { model_id: r.modelId, prompt: r.prompt })
      return out.sheet_b64
    }
    const out = await assetsApi.generate(
      { model_id: r.modelId, prompt: r.prompt, size: r.size || undefined, project_id: projectId })
    return out.images[0] || ''
  }

  /** 落库:人物 → 该角色默认造型的四视图;背景 → 场景参考图。
   *
   * 两者都顺带存一份进素材库 —— 这张图值得被别的集复用,而素材库是复用的唯一入口。
   * 存素材库是旁路,失败只提示、不回滚已绑好的图(规范 6)。
   */
  const saveGeneratedForTarget = async (
    r: { imageB64: string; prompt: string; modelId: string }
  ) => {
    const t = genTarget
    if (!t || !projectId) return
    try {
      if (t.subject === 'character') {
        const look = await ensureDefaultLook(t.characterId)
        // 四视图裁切在后端做(白底找空隙);切不开时 views=null —— 那时图已生成成功,
        // 引导用户去角色页人工裁切,不在这里把生成结果丢掉。
        const out = await charactersApi.cropSheetToViews(projectId, t.characterId, look.id,
          { sheet_b64: r.imageB64 })
        if (!out.views) {
          Toast.warning('图已存入素材库，但四视图未能自动切开，请到「角色」页手动裁切')
        } else {
          Toast.success('已生成并填入该角色的造型')
        }
      } else {
        const up = await filesApi.uploadFromBase64(
          projectId, { image_b64: r.imageB64, type: 'background', filename: `${t.key}.png` })
        const cur = refEntries.find(e => e.key === t.key)
        await persistRefs(
          cur
            ? refEntries.map(e => e.key === t.key
              ? { ...e, image_url: up.url, prompt: r.prompt } : e)
            : [...refEntries, {
              key: t.key, ref_type: 'background' as const, image_url: up.url,
              prompt: r.prompt, localPreview: '', uploading: false,
            }])
        Toast.success('已生成并设为该场景的参考图')
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
      throw e   // 让弹窗留在预览态,用户可重试而不是丢掉刚生成的图
    }
    assetsApi.saveGenerated({
      category: t.subject, name: t.key, description: r.prompt, image_b64: r.imageB64,
    }).catch(() => Toast.warning('已绑定，但存入素材库失败'))
    setGenTarget(null)
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
  // from_story 模式的流水线含 analysis 步;from_script(复用剧本/改编切片)不含。
  // 不新增后端字段 —— pipeline.steps 本身已经是这个判据的唯一真相。
  const isFromStory = steps.some(s => s.key === 'analysis')
  // 流水线真实进度(驱动各步状态色)与用户正在查看的步(驱动右侧面板)是两件事
  const progressIndex = Math.max(0, steps.findIndex(s => s.key === pipeline?.current))
  const activeKey = selectedStep ?? pipeline?.current ?? steps[0]?.key ?? null
  const activeIndex = Math.max(0, steps.findIndex(s => s.key === activeKey))
  const isAtScreenplayReview = isPaused && pausedAt === 'screenplay_review'
  const isAtStoryboardReview = isPaused && pausedAt === 'storyboard_review'
  const isAtPromptsReview = isPaused && pausedAt === 'prompts_review'
  const isAtLookReview = isPaused && pausedAt === 'look_review'
  const isAtKeyframesReview = isPaused && pausedAt === 'keyframes_review'
  const PAUSED_OR_TERMINAL = ['created', 'completed', 'failed', 'assembly_failed']
  const isRunning = !PAUSED_OR_TERMINAL.includes(stage)
    && !isAtScreenplayReview && !isAtStoryboardReview && !isAtPromptsReview
    && !isAtLookReview && !isAtKeyframesReview
  const stepStatus = (i: number): 'process' | 'finish' | 'error' | 'warning' | undefined => {
    if (pipeline?.current == null) return undefined
    // 流水线所在的那一步:它的真实状态(失败/待审核/跑完/进行中)优先于"我在看哪一步" ——
    // 卡点在这里就得看得出来,否则用户会漏掉需要他操作的那一步。
    if (i === progressIndex) {
      if (episode.status === 'failed' || stage === 'assembly_failed') return 'error'
      if (isAtScreenplayReview || isAtStoryboardReview || isAtPromptsReview
          || isAtLookReview || isAtKeyframesReview) return 'warning'
      if (!isRunning) return 'finish'
      return 'process'
    }
    // 正在查看的步用 process 高亮:Semi 的 -active 类会被 finish 样式盖住,
    // 一集跑完后所有步都是 finish,点哪步都看不出选中(实测)。
    // 用原生 status 表达而非自定义样式(规范 8)。
    if (i === activeIndex) return 'process'
    if (i < progressIndex) return 'finish'
    // 不显式返回 'wait':Semi 在 status 缺省时按 index > current 自己推导成 wait
    // (semi-ui/lib/es/steps/basicSteps.js),写死一遍属于重复实现同一规则。
    return undefined
  }
  // 未推进到的步不可点:那边没有内容可看,切过去只会得到一个空面板。
  // current == null 是**尚未启动**(不是"所有步都到过"):此时只有第一步可点,
  // 否则整条流水线看起来全都能点,点进去却是空面板。
  const stepReached = (i: number) => (pipeline?.current == null ? i === 0 : i <= progressIndex)
  // 点回"流水线正在跑的那一步" = 恢复自动跟随;点其它步则钉住,不被后台推进抢走。
  const selectStep = (i: number) => {
    const key = steps[i]?.key
    if (!key) return
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
  // 启动卡在开拍后**不消失**,改为显示"正在跑哪一步"。
  // 只在 created 态渲染的话,一点「开始制作」它就随状态变更整块卸载,而首个节点
  // 产出前右栏又没有别的内容 —— 用户看到的是一片空白,像是操作失败了。
  //
  // 判据不能是"story_analysis 还没来":那只对 from_story 集成立(它的首个节点正是
  // 故事分析)。from_script 集(复用剧本/改编切片)图内直达分镜,story_analysis
  // 继承自 Story、开拍那一刻就非空 —— 若仍用这条判据,分镜生成中(LLM 调用,
  // 可能耗时数十秒到几分钟)这张占位卡永远不出现,右栏只剩一张空的参考图卡,
  // 用户看不到任何进度、也没有任何按钮(实测)。
  // 改用"当前步(必是流水线首步,见下方 activeIndex===0 才会用到)有没有产出"
  // 这一更general的判据,与各步卡片(storyboardCard 等)判空的条件同源。
  const activeStepHasContent = (() => {
    switch (activeKey) {
      case 'analysis': return Boolean(status?.story_analysis)
      case 'cast': return (status?.cast_pending?.length ?? 0) > 0
      case 'screenplay': return Boolean(status?.screenplay)
      case 'storyboard': return Boolean(status?.shots && status.shots.length > 0)
      case 'looks': return Object.keys(status?.look_assignments || {}).length > 0
      case 'prompts': return Boolean(status?.prompts && status.prompts.length > 0)
      case 'keyframes':
        return isAtKeyframesReview || (status?.prompts || []).some(p => !!p.keyframe_url)
      case 'video': return Boolean(status?.videos && status.videos.length > 0)
      case 'done': return Boolean(status?.assembled_video_path) || Boolean(status?.videos?.length)
      default: return false
    }
  })()
  const startedButIdle = isRunning && activeIndex === 0 && !activeStepHasContent
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
  ) : startedButIdle ? (
    <Card title="制作已启动">
      <Space align="center">
        <Spin />
        <Text type="tertiary">
          {`${STATUS_LABEL[stage] || stage}…首个产出完成后会自动显示在这里`}
        </Text>
      </Space>
    </Card>
  ) : null

  // 用户自己输入的原始故事,是这一集所有产出的源头,挂在故事分析那一步内可见。
  // 只在 created 态可编辑:开拍后故事分析与剧本都由这段原文推导而来,改它会让产出与源头不符
  // (要改内容走剧本审核的 AI 改写/手动编辑,那条路有版本树)。
  const storyText0 = story?.content || ''
  // 原文为空(旧数据里的改编切片没保存过片段原文)时不显示这张卡。
  const storyCard = storyText0 ? (
    <StoryTextPanel
      title="故事内容"
      text={storyText0}
      editable={episode.status === 'created'}
      lockedHint="已开拍，如需调整请在剧本审核阶段改写"
      onSave={async next => {
        if (!episode.story_id) return
        // 原文的家是 Story(集经 story_id 锚定它),故写的是 Story 而非 Script:
        // 写进方案会让同一段原文的多个方案各持一份并逐渐漂移。
        setStory(await storiesApi.update(episode.story_id, { content: next }))
      }}
    />
  ) : null

  const referencesCard = (
    <Card title="参考图片" headerExtraContent={<Text type="tertiary">启动后亦可修改</Text>}>
      <ReferencesPanel
        projectId={projectId ?? ''}
        entries={refEntries}
        onPersist={persistRefs}
        onPatch={patchRef}
        onGenerate={(key, prompt) =>
          setGenTarget({ subject: 'background', key, prompt: prompt || '' })}
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
      cast={status?.cast}
      loading={reviewLoading}
      onConfirm={handleConfirmCast}
      onGenerateLook={(name, characterId) =>
        setGenTarget({ subject: 'character', key: name, characterId })}
    />
  ) : null

  /** 剧本面板。reviewing=true 时带审核控件(版本树 / AI 改写 / 通过·修改)。
   *
   * 「生成剧本」与「审核剧本」是两步,故审核控件只在审核步出现 —— 两步都给的话,
   * 停在审核卡点时点这两步看到的东西一模一样(实测)。
   * 判据是**用户在看哪一步** ∧ **图确实停在该卡点**:后者不成立时点开审核步也无从审核。 */
  const makeScreenplayCard = (reviewing: boolean) => status?.screenplay ? (
    <ScreenplayReviewPanel
      episodeId={episodeId ?? ''}
      screenplay={status.screenplay}
      versions={status.screenplay_versions}
      current={status.screenplay_version_current}
      isReviewing={reviewing}
      reviewLoading={reviewLoading}
      onApprove={handleApproveScreenplay}
      onReject={() => revisionModal('提交修改意见', '请描述需要修改的内容...', () => handleApproveScreenplay(false))}
      onApplied={refreshStatus}
    />
  ) : null

  // 分镜版本树:退回重新生成会整份覆盖 shots,故上一版分镜(可能更满意、已看过)
  // 若不留痕就再也找不回来 —— 只在审核态且有多于 1 版时才展示版本下拉,
  // 单版本时下拉除了显示"当前版本"什么都不做,是死 UI。
  const shotsVersions = status?.shots_versions ?? []
  const shotsViewIdx = selectedShotsVersion ?? (status?.shots_version_current ?? 0)
  const shotsViewingCurrent = shotsViewIdx === (status?.shots_version_current ?? 0)
  const shotsViewData = isAtStoryboardReview && selectedShotsVersion != null
    ? (shotsVersions[shotsViewIdx]?.shots ?? status?.shots ?? [])
    : (status?.shots ?? [])

  const storyboardCard = status?.shots && status.shots.length > 0 ? (
    <Card title={`分镜脚本 · ${status.shots.length} 个镜头${fmtDuration(status.total_duration_seconds)}`}
      headerExtraContent={
        <Space>
          {status.duration_over_target && (
            <Text type="warning">总时长超出目标，建议退回重新生成</Text>
          )}
          {/* 版本下拉:仅审核态且有历史版本才展示(镜 ScreenplayReviewPanel 的版本 Select,
              label 截断同理,意见原文可能很长,不截断会把 Select 撑爆)。 */}
          {isAtStoryboardReview && shotsVersions.length > 1 && (
            <Select
              value={shotsViewIdx}
              optionList={shotsVersions.map((ver, i) => ({
                value: i,
                label: `版本${i + 1}·${(ver.label || '').trim().slice(0, 12)}${(ver.label || '').trim().length > 12 ? '…' : ''}`,
              }))}
              onChange={v => {
                const idx = Number(v)
                setSelectedShotsVersion(idx === (status?.shots_version_current ?? 0) ? null : idx)
              }}
            />
          )}
          {isAtStoryboardReview && !shotsViewingCurrent && (
            <Button size="small" loading={revertingShots}
              onClick={() => handleRevertShotsVersion(shotsViewIdx)}>恢复到此版本</Button>
          )}
          {/* 分镜是人工卡点(storyboard_review),必须给通过/退回 —— 只提示"建议退回"
              却不给按钮,用户无从操作,整集卡在这里。 */}
          {isAtStoryboardReview && shotsViewingCurrent && (
            <>
              <Button type="primary" size="small" loading={reviewLoading}
                onClick={() => handleApproveStoryboard(true)}>通过，继续造型</Button>
              <Button type="warning" size="small" loading={reviewLoading}
                onClick={() => revisionModal(
                  '提交修改意见', '请描述分镜需要调整的地方（如镜头过多、节奏、时长）...',
                  () => handleApproveStoryboard(false))}
              >退回重新生成</Button>
            </>
          )}
        </Space>
      }>
      <Table size="small" dataSource={shotsViewData} rowKey="shot_id" pagination={false}
        expandRowByClick
        expandedRowRender={(row?: {
          location?: string; action?: string; dialogue?: string; color_temp?: string
        }) => (
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
          // 光影列:同场景内应当一致(后端收敛),列出来才能一眼看出哪镜跳了
          { title: '光影', dataIndex: 'lighting', width: 100,
            render: (v: string, r: {
              location?: string; action?: string; dialogue?: string; color_temp?: string
            }) => LIGHT_LABEL[v]
              ? `${LIGHT_LABEL[v]}·${TEMP_LABEL[r.color_temp ?? ''] ?? '-'}` : '-' },
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

  // 合成只拼成功的镜头,失败的被跳过 —— 成片照样能播,用户不会知道少了什么
  // (实测:20 镜里 1 支超时,少的恰好是高潮戏)。故缺镜必须在成片卡上讲明白:
  // 数量 + 具体镜号,并给出补齐入口 —— 只说"不完整"用户不知道该补哪个。
  const missingShots = (status?.videos || [])
    .filter((v: { status: string }) => v.status !== 'succeeded')
    .map((v: { shot_id: string }) =>
      status?.shots?.find((s: { shot_id: string }) => s.shot_id === v.shot_id)?.shot_number)
    .filter((n): n is number => typeof n === 'number')
    .sort((a, b) => a - b)

  const finalCard = status?.assembled_video_path && episodeId ? (
    <Card title="✦ 最终成片">
      <Row gutter={[0, 8]}>
        {missingShots.length > 0 && (
          <Col span={24}>
            <Banner
              type="warning"
              fullMode={false}
              closeIcon={null}
              description={
                <Space vertical align="start">
                  <Text>
                    {`有 ${missingShots.length} 个镜头未纳入成片`}
                    {`（镜 ${missingShots.join('、镜 ')}）`}
                    —— 它们生成失败，成片已跳过这些镜头拼接。
                  </Text>
                  <Text link onClick={() => setSelectedStep('video')}>去补齐这些镜头</Text>
                </Space>
              }
            />
          </Col>
        )}
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
  // 注意:故事分析**不在**这里 —— 它是跨步骤常驻上下文(见下方 contextCards)。
  // 参考图跨多步但不跨全程,故不进 PANELS(单步归属)也不进 contextCards(全程常驻),
  // 由 activePanel 按 REFERENCES_VISIBLE_STEPS 判定。
  // **每步只放属于自己的内容**:同一张卡出现在两步下,用户点来点去看到的东西一样,
  // 分不清自己在哪一步(实测)。剧本正文归"生成剧本",审核操作归"审核剧本";
  // 视频清单归"生成视频",成片归"完成"。
  const PANELS: Record<string, ReactNode> = {
    // 故事分析步只放该步自己的产出;**不得放剧本** ——
    // 剧本是后一步的产出,放这里会让"故事分析"面板顶着「剧本」标题(实测)。
    // 故事原文收紧到只在本步展示(2026-09-12):它是本步的输入依据,其余步骤
    // 看的是剧本/分镜/镜头,不再需要跨步回看原文——顶部「故事 →」链接够用。
    // from_script 模式没有 analysis 步,storyCard 在这类集里恒为 null。
    analysis: <CardColumn cards={[isFromStory ? storyCard : null, storyAnalysisCard]} />,
    cast: <CardColumn cards={[castCard]} />,
    // 剧本步:正文 + 审核控件(停在该卡点时才有审核可做)。生成与审核是同一步 ——
    // 审核的对象就是本步产出,拆开只能靠"有没有按钮"区分(见 pipeline_steps 的注释)。
    screenplay: <CardColumn cards={[makeScreenplayCard(isAtScreenplayReview)]} />,
    storyboard: <CardColumn cards={[storyboardCard]} />,
    looks: <CardColumn cards={[looksCard]} />,
    prompts: <CardColumn cards={[promptsCard]} />,
    keyframes: <CardColumn cards={[keyframesCard]} />,
    video: <CardColumn cards={[videosCard]} />,
    // 完成步聚焦成片:视频清单是上一步的内容,重放一遍会让两步看起来一样。
    // 成片还没合出来时(如合成失败)才退回显示清单,否则这一步会是空的。
    done: <CardColumn cards={[finalCard ?? videosCard]} />,
  }
  // 背景参考图的提炼依据是分镜产出的场景/地点,分镜完成前没有列表可对照;
  // 分镜之后(造型/Prompt/关键帧/视频)随时可能要回看或补传,成片阶段(done)
  // 已不需要再改它。起点选"分镜"步本身,让用户看分镜表时就能顺手补图。
  const REFERENCES_VISIBLE_STEPS = new Set(['storyboard', 'looks', 'prompts', 'keyframes', 'video'])
  const showReferences = activeKey != null && REFERENCES_VISIBLE_STEPS.has(activeKey)
  // 启动卡挂**流水线首步**,而不是写死某个 key:复用剧本的集(from_script)首步是分镜,
  // 只挂 analysis 的话这类集没有任何启动入口;而写死两个 key 又让分镜步夹带了
  // 不属于它的卡片。判据是"这是不是第一步"。startCard 仅未开拍时非空,故开拍后自动消失。
  const activePanel = activeKey
    ? (
        <CardColumn cards={[
          activeIndex === 0 ? startCard : null,
          PANELS[activeKey],
          showReferences ? referencesCard : null,
        ]} />
      )
    : null
  // 跨步骤常驻上下文:全程都该看得见的东西,故**不挂进 PANELS**。
  // 故事分析是后续每一步的依据;剧本定稿后它已"用过",只作判断产出是否跑偏的参照 ——
  // 故收成折叠形态,只占一行、点开可看全,不与分镜表争版面。
  const collapsible = (key: string, title: string, summary: string, body: ReactNode) => (
    <Card title={title} headerExtraContent={
      <Text link onClick={() => toggleContext(key)}>
        {openContext[key] ? '收起' : '展开'}
      </Text>
    }>
      {openContext[key] ? body : <Text type="tertiary">{summary}</Text>}
    </Card>
  )
  // 跨步骤常驻的现在只剩故事分析的折叠摘要 —— 故事原文(只在 analysis 步展示)
  // 与参考图(只在 storyboard~video 展示)都已挪进各自步骤的面板,
  // 见 activePanel 的计算与 PANELS.analysis。
  const contextCards = (
    <CardColumn cards={[
      // 故事分析的主场是它自己那一步(PANELS.analysis 里是完整卡片)。此处只在**别的步**
      // 补一份折叠摘要作参照 —— 两处都渲染完整卡片,点到 analysis 步就会看到两遍。
      activeKey !== 'analysis' && storyAnalysisCard
        ? collapsible('analysis', '故事分析',
            status?.story_analysis?.plot_summary || '（无梗概）', storyAnalysisCard)
        : null,
    ]} />
  )

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
          {/* 回到源头的路径:原文恒有(集的锚点),故它是主链接;起始方案可空
              (从故事开跑的集没有),只在有的时候补一个。
              只挂方案链接的话,从故事开跑的集完全没有回源头的入口。 */}
          {episode.story_id && (
            <Text link onClick={() => navigate(`/stories/${episode.story_id}`)}>故事 →</Text>
          )}
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
                  {/* 可点性由每步的 onClick 决定:未推进到的步不传 onClick,WorkflowSteps
                      据此渲染为不可点(data-clickable=false),看起来能点必须与真的能点是
                      同一个判据。"正在查看哪一步"与"节点自身状态"两个通道各司其职:
                      前者由 stepStatus 在 i === activeIndex 时返回 'process' 表达,
                      后者(finish/warning/error)优先级更高、互不冒充。 */}
                  <WorkflowSteps items={steps.map((s, i) => ({
                    key: s.key,
                    label: s.label,
                    description: fmtCost(s.cost, status?.cost_unpriced),
                    status: stepStatus(i),
                    onClick: stepReached(i) ? () => selectStep(i) : undefined,
                  }))} />
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

        {/* 右栏:当前步骤的内容 + 跨步骤常驻上下文(故事分析折叠摘要) */}
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
      {genTarget && (
        <GenerateFromScriptModal
          visible
          subject={genTarget.subject}
          subjectKey={genTarget.key}
          episodeId={episodeId}
          initialPrompt={genTarget.subject === 'background' ? genTarget.prompt : undefined}
          onGenerate={generateForTarget}
          onSave={saveGeneratedForTarget}
          onCancel={() => setGenTarget(null)}
        />
      )}
    </PageShell>
  )
}
