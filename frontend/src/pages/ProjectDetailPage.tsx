import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Steps, Button, Tag, Spin, Toast, TextArea, Table, Modal, Typography, Upload, Input, Card, Space, Descriptions, List, Banner, Empty, Divider, Select, Checkbox, VideoPlayer as SemiVideoPlayer } from '@douyinfe/semi-ui'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconUpload, IconDownload, IconPlus, IconClose, IconUser, IconHome, IconImage } from '@douyinfe/semi-icons'
import { workflowApi, filesApi, episodesApi, charactersApi, createWebSocket, WorkflowStatus, Episode, artifactsApi, VideoArtifact, ActionOption, assetsApi, Asset } from '../services/api'
import ActionParamForm from '../components/ActionParamForm'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import PreviewImage from '../components/PreviewImage'

const { Title, Text, Paragraph } = Typography

// 流水线步骤由后端下发(status.pipeline,单一真相见后端 pipeline_steps.py);前端只渲染。

const STATUS_LABEL: Record<string, string> = {
  created: '待启动', starting: '启动中', analyzing: '故事分析中', story_analyzed: '分析完成',
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

// 金额均为估算,币种人民币;未定价用量存在时不展示可能误导的数字。
const fmtCost = (n?: number, unpriced?: boolean) =>
  unpriced ? '未定价' : (n != null ? `¥${n.toFixed(2)}（估算）` : undefined)

// ── Reference entry: one character or location with optional image ──────────
interface RefEntry {
  id: string        // local UI id
  key: string       // character name or location name
  refType: 'character' | 'background'
  imageUrl: string  // server URL, empty if not set
  localPreview: string // object URL for display before server confirms
  uploading: boolean
}

function newEntry(key: string, refType: 'character' | 'background', imageUrl = ''): RefEntry {
  return { id: crypto.randomUUID(), key, refType, imageUrl, localPreview: '', uploading: false }
}

// ── Reference Panel ──────────────────────────────────────────────────────────
function ReferencesPanel({
  projectId,
  episodeId,
  entries,
  onChange,
  autoAddType,
  onAutoAddConsumed,
}: {
  projectId: string
  episodeId: string
  entries: RefEntry[]
  onChange: (entries: RefEntry[]) => void
  autoAddType?: 'character' | 'background' | null
  onAutoAddConsumed?: () => void
}) {
  const [addingType, setAddingType] = useState<'character' | 'background' | null>(null)
  const [newKey, setNewKey] = useState('')
  const [pickingType, setPickingType] = useState<'character' | 'background' | null>(null)
  const [libAssets, setLibAssets] = useState<Asset[]>([])
  const [libLoading, setLibLoading] = useState(false)
  const [picking, setPicking] = useState(false)
  // Keep a ref to always-latest entries so async handlers don't use stale closures
  const entriesRef = useRef(entries)
  useEffect(() => { entriesRef.current = entries }, [entries])

  useEffect(() => {
    if (autoAddType) {
      setAddingType(autoAddType)
      setNewKey('')
      onAutoAddConsumed?.()
    }
  }, [autoAddType, onAutoAddConsumed])

  const update = (id: string, patch: Partial<RefEntry>) =>
    onChange(entriesRef.current.map(e => e.id === id ? { ...e, ...patch } : e))

  const remove = (id: string) => onChange(entriesRef.current.filter(e => e.id !== id))

  const handleUpload = async (entry: RefEntry, file: File) => {
    const preview = URL.createObjectURL(file)
    update(entry.id, { uploading: true, localPreview: preview })
    try {
      const result = await filesApi.uploadImage(projectId, file, entry.refType)
      update(entry.id, { imageUrl: result.url, localPreview: preview, uploading: false })
      // Use ref to get latest entries at the time upload finishes (avoids stale closure)
      const latest = entriesRef.current
      await filesApi.updateReferences(episodeId, latest.map(e => ({
        key: e.key, ref_type: e.refType,
        image_url: e.id === entry.id ? result.url : e.imageUrl,
      })))
    } catch {
      Toast.error('上传失败')
      update(entry.id, { uploading: false, localPreview: '' })
    }
  }

  const handleAddEntry = () => {
    if (!newKey.trim() || !addingType) return
    onChange([...entries, newEntry(newKey.trim(), addingType)])
    setNewKey('')
    setAddingType(null)
  }

  const openLibrary = (refType: 'character' | 'background') => {
    setPickingType(refType)
    setLibLoading(true)
    assetsApi.list(refType)
      .then(setLibAssets)
      .catch(() => Toast.error('素材库加载失败'))
      .finally(() => setLibLoading(false))
  }

  // 从库选择:先拷贝一份进本剧集(拿到与 upload 同形状的 url),再走同一条
  // “新增 entry + updateReferences 持久化” 的既有流程。
  const handlePickAsset = async (asset: Asset) => {
    if (!pickingType) return
    setPicking(true)
    try {
      const result = await filesApi.copyFromAsset(projectId, asset.id, pickingType)
      const entry = newEntry(asset.name, pickingType, result.url)
      const latest = [...entriesRef.current, entry]
      onChange(latest)
      await filesApi.updateReferences(episodeId, latest.map(e => ({
        key: e.key, ref_type: e.refType, image_url: e.imageUrl,
      })))
      Toast.success('已从素材库添加')
      setPickingType(null)
    } catch {
      Toast.error('添加失败')
    } finally {
      setPicking(false)
    }
  }

  const characters = entries.filter(e => e.refType === 'character')
  const backgrounds = entries.filter(e => e.refType === 'background')

  const renderEntry = (entry: RefEntry) => (
    <List.Item
      key={entry.id}
      main={
        <Space align="center">
          <Upload
            action=""
            accept="image/*"
            showUploadList={false}
            beforeUpload={({ file }: { file: FileItem }) => {
              if (file.fileInstance) handleUpload(entry, file.fileInstance)
              return { autoRemove: false, status: 'validateFail', shouldUpload: false }
            }}
          >
            {entry.uploading ? (
              <Spin size="small" />
            ) : entry.localPreview || entry.imageUrl ? (
              <PreviewImage src={entry.localPreview || entry.imageUrl} alt={entry.key} width={40} height={40} />
            ) : (
              <Button size="small" type="tertiary" icon={<IconUpload />} />
            )}
          </Upload>
          <Text>{entry.key}</Text>
          {entry.imageUrl
            ? <Tag color="green">已绑定</Tag>
            : <Tag color="grey">未上传</Tag>}
        </Space>
      }
      extra={
        <Space align="center">
          {entry.imageUrl && (
            <Button
              size="small" type="tertiary" theme="borderless"
              onClick={async () => {
                update(entry.id, { imageUrl: '', localPreview: '' })
                const latest = entriesRef.current
                await filesApi.updateReferences(episodeId, latest.map(e =>
                  e.id === entry.id ? { key: e.key, ref_type: e.refType, image_url: '' } : { key: e.key, ref_type: e.refType, image_url: e.imageUrl }
                ))
              }}
            >清除图片</Button>
          )}
          <Button
            size="small" type="tertiary" theme="borderless" icon={<IconClose />}
            onClick={async () => {
              remove(entry.id)
              const latest = entriesRef.current.filter(e => e.id !== entry.id)
              await filesApi.updateReferences(episodeId, latest.map(e => ({
                key: e.key, ref_type: e.refType, image_url: e.imageUrl
              })))
            }}
          />
        </Space>
      }
    />
  )

  const renderGroup = (group: RefEntry[], label: string, refType: 'character' | 'background') => (
    <Space vertical align="start">
      <Space align="center">
        {refType === 'character' ? <IconUser /> : <IconHome />}
        <Text strong>{label}</Text>
        <Button
          size="small" type="tertiary" icon={<IconPlus />}
          onClick={() => { setAddingType(refType); setNewKey('') }}
        >
          添加
        </Button>
        <Button
          size="small" type="tertiary" icon={<IconImage />}
          onClick={() => openLibrary(refType)}
        >
          从库选择
        </Button>
      </Space>

      <List
        dataSource={group}
        renderItem={renderEntry}
        emptyContent={<Text type="tertiary">暂无{label}，点击「添加」新增</Text>}
      />

      {/* Inline add form */}
      {addingType === refType && (
        <Space align="center">
          <Input
            placeholder={refType === 'character' ? '输入角色名称' : '输入场景地点'}
            value={newKey}
            onChange={setNewKey}
            onEnterPress={handleAddEntry}
            size="small"
            autoFocus
          />
          <Button size="small" type="primary" onClick={handleAddEntry} disabled={!newKey.trim()}>确认</Button>
          <Button size="small" type="tertiary" onClick={() => { setAddingType(null); setNewKey('') }}>取消</Button>
        </Space>
      )}
    </Space>
  )

  return (
    <Space vertical align="start" spacing="loose">
      {renderGroup(characters, '角色参考图', 'character')}
      <Divider />
      {renderGroup(backgrounds, '背景参考图', 'background')}

      <Modal
        title={pickingType === 'character' ? '从素材库选择人物' : '从素材库选择背景'}
        visible={!!pickingType}
        onCancel={() => setPickingType(null)}
        footer={null}
        width={640}
      >
        {libLoading ? (
          <Spin />
        ) : (
          <List
            grid={{ gutter: 12, span: 6 }}
            dataSource={libAssets}
            emptyContent={<Empty description="素材库暂无该分类素材" />}
            renderItem={(a: Asset) => (
              <List.Item>
                <Card
                  shadows="hover"
                  cover={<PreviewImage src={a.url} alt={a.name} width={120} height={120} />}
                  footer={
                    <Button
                      size="small" type="primary" theme="borderless" loading={picking}
                      onClick={() => handlePickAsset(a)}
                    >选择</Button>
                  }
                >
                  <Card.Meta title={a.name} description={a.description || undefined} />
                </Card>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </Space>
  )
}

// ── Video Player ─────────────────────────────────────────────────────────────
function VideoPlayer({ src, title }: { src: string; title?: string }) {
  // 播放器用 Semi 原生 VideoPlayer(自带播放/进度/音量/全屏/画中画等控件);
  // 下载不在其控件栏内,单独保留一个下载按钮。
  return (
    <Card title={title}>
      <Space vertical align="start">
        <SemiVideoPlayer
          src={src}
          height={320}
          theme="dark"
          autoPlay={false}
          muted={false}
          clickToPlay
          volume={0.6}
          defaultPlaybackRate={1}
          playbackRateList={[
            { label: '0.5x', value: 0.5 },
            { label: '1.0x', value: 1 },
            { label: '1.5x', value: 1.5 },
            { label: '2.0x', value: 2 },
          ]}
        />
        <Button
          theme="borderless" type="tertiary" icon={<IconDownload />}
          onClick={() => {
            const a = document.createElement('a')
            a.href = src
            a.download = title || 'video.mp4'
            a.click()
          }}
        >下载</Button>
      </Space>
    </Card>
  )
}

// ── Shot Artifact Tree ─────────────────────────────────────────────────────────
function ShotArtifactPanel({ episodeId, projectId, shotId }: { episodeId: string; projectId: string; shotId: string }) {
  const [artifacts, setArtifacts] = useState<VideoArtifact[]>([])
  const [actions, setActions] = useState<ActionOption[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [activeAction, setActiveAction] = useState<ActionOption | null>(null)
  const [running, setRunning] = useState(false)

  const load = useCallback(() => {
    artifactsApi.listByShot(episodeId, shotId).then(setArtifacts).catch(() => setArtifacts([]))
  }, [episodeId, shotId])

  useEffect(() => { load() }, [load])

  const pick = (aid: string) => {
    setSelected(aid); setActiveAction(null)
    artifactsApi.listActions(episodeId, aid).then(setActions).catch(() => setActions([]))
  }

  const run = (values: Record<string, unknown>) => {
    if (!selected || !activeAction) return
    setRunning(true)
    artifactsApi.runAction(episodeId, selected, activeAction.id, values)
      .then(() => { Toast.success('已生成新版本'); setActiveAction(null); load() })
      .catch((e: { response?: { data?: { detail?: string } }; message?: string }) =>
        Toast.error('执行失败: ' + (e?.response?.data?.detail || e?.message || '')))
      .finally(() => setRunning(false))
  }

  if (artifacts.length === 0) return null
  return (
    <Card title="版本树">
      <Space vertical align="start">
        <Space wrap>
          {artifacts.map(a => (
            <Button key={a.id} size="small" theme={selected === a.id ? 'solid' : 'light'} onClick={() => pick(a.id)}>
              {a.action} · {a.provider} · {a.resolution}
            </Button>
          ))}
        </Space>
        {selected && actions.length > 0 && (
          <Space wrap>
            {actions.map(act => (
              <Button key={act.id} size="small" type="tertiary" onClick={() => setActiveAction(act)}>{act.label}</Button>
            ))}
          </Space>
        )}
        {activeAction && (
          <ActionParamForm schema={activeAction.param_schema} onSubmit={run} submitting={running} projectId={projectId} />
        )}
      </Space>
    </Card>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────
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
  const [pendingAddType, setPendingAddType] = useState<'character' | 'background' | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const lastSeqRef = useRef<number>(0)
  const refEntriesInitialized = useRef(false)
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
      filesApi.getReferences(episodeId).catch(() => ({} as Record<string, string>)),
    ])
    if (ep) setEpisode(ep)
    projectStatusRef.current = ep?.status ?? 'created'
    if (wfStatus) {
      setStatus(wfStatus)
      // Re-sync ref entries whenever story_analysis or shots bring new data
      if (!refEntriesInitialized.current) {
        const chars = wfStatus.story_analysis?.characters?.map((c: { name: string }) => c.name) || []
        const locations = [...new Set((wfStatus.shots || []).map((s: { location: string }) => s.location).filter(Boolean))] as string[]

        const hasData = chars.length > 0 || locations.length > 0 || Object.keys(serverRefs).length > 0
        // Mark initialized once we have real data, or once the workflow has advanced past created
        if (hasData || (wfStatus.current_stage && wfStatus.current_stage !== 'created')) {
          refEntriesInitialized.current = true
        }

        if (hasData) {
          setRefEntries(prev => {
            const existingByKey = new Map(prev.map(e => [e.key, e]))
            const next: RefEntry[] = []
            for (const name of chars) {
              const ex = existingByKey.get(name)
              next.push(ex
                ? { ...ex, imageUrl: ex.imageUrl || serverRefs[name] || '' }
                : newEntry(name, 'character', serverRefs[name] || ''))
            }
            for (const loc of locations) {
              const ex = existingByKey.get(loc)
              next.push(ex
                ? { ...ex, imageUrl: ex.imageUrl || serverRefs[loc] || '' }
                : newEntry(loc, 'background', serverRefs[loc] || ''))
            }
            // preserve user-added entries not covered above
            for (const e of prev) {
              if (!next.some(n => n.key === e.key)) next.push(e)
            }
            // add server refs not yet in the list
            for (const [key, url] of Object.entries(serverRefs)) {
              if (!next.some(n => n.key === key)) {
                next.push(newEntry(key, chars.includes(key) ? 'character' : 'background', url))
              }
            }
            return next
          })
        }
      }
    }
  }, [episodeId])

  useEffect(() => {
    if (!episodeId) return
    refreshStatus().finally(() => setLoading(false))
    const ws = createWebSocket(episodeId, (event) => {
      if (typeof event.seq === 'number') lastSeqRef.current = Math.max(lastSeqRef.current, event.seq)
      if (event.type === 'stage_change') {
        const stage: string = event.data?.payload_json?.current_stage || ''
        if (stage === 'story_analyzed' || stage === 'storyboard_ready') {
          refEntriesInitialized.current = false
        }
        refreshStatus()
      }
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

  const handleStart = async () => {
    if (!episodeId || starting) return
    setStarting(true)
    try {
      // Persist any pre-set references before starting
      if (refEntries.some(e => e.imageUrl)) {
        await filesApi.updateReferences(episodeId, refEntries.map(e => ({
          key: e.key, ref_type: e.refType, image_url: e.imageUrl
        })))
      }
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

  const handleApproveLooks = async (approved: boolean) => {    if (!episodeId || reviewLoading) return
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
  const stepIndex = Math.max(0, steps.findIndex(s => s.key === pipeline?.current))
  const isAtScreenplayReview = isPaused && pausedAt === 'screenplay_review'
  const isAtPromptsReview = isPaused && pausedAt === 'prompts_review'
  const isAtLookReview = isPaused && pausedAt === 'look_review'
  const isAtKeyframesReview = isPaused && pausedAt === 'keyframes_review'
  const PAUSED_OR_TERMINAL = ['created', 'completed', 'failed', 'assembly_failed']
  const isRunning = !PAUSED_OR_TERMINAL.includes(stage)
    && !isAtScreenplayReview && !isAtPromptsReview && !isAtLookReview && !isAtKeyframesReview
  const stepStatus = (i: number): 'process' | 'finish' | 'error' | 'warning' | undefined => {
    if (pipeline?.current == null) return undefined
    if (i < stepIndex) return 'finish'
    if (i > stepIndex) return undefined
    if (episode.status === 'failed' || stage === 'assembly_failed') return 'error'
    if (isAtScreenplayReview || isAtPromptsReview || isAtLookReview || isAtKeyframesReview) return 'warning'
    if (!isRunning) return 'finish'
    return 'process'
  }

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
      <Space vertical align="start" spacing="loose">
      {/* Progress steps */}
      {steps.length > 0 && (
        <Card>
          <Steps current={stepIndex}>
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
      )}

      {/* Start CTA (created state) */}
      {episode.status === 'created' && (
        <Card title="项目准备就绪">
          <Space vertical align="start" spacing="loose">
            <Paragraph type="tertiary">
              AI 将自动完成故事分析、剧本创作、分镜规划、Prompt 生成和视频合成。
              您可提前上传角色/背景参考图，也可在流程启动后随时补充。
            </Paragraph>

            <Card title="参考图片（选填）" headerExtraContent={<Text type="tertiary">启动后亦可修改</Text>}>
              <ReferencesPanel
                projectId={projectId ?? ''}
                episodeId={episodeId!}
                entries={refEntries}
                onChange={setRefEntries}
                autoAddType={pendingAddType}
                onAutoAddConsumed={() => setPendingAddType(null)}
              />
            </Card>

            <Button colorful theme="solid" type="primary" loading={starting} onClick={handleStart}>
              开始制作
            </Button>
          </Space>
        </Card>
      )}

      {/* Reference images panel (after start) */}
      {episode.status !== 'created' && (
        <Card title="参考图片">
          <ReferencesPanel
            projectId={projectId ?? ''}
            episodeId={episodeId!}
            entries={refEntries}
            onChange={setRefEntries}
          />
        </Card>
      )}

      {/* Story Analysis */}
      {status?.story_analysis && (
        <Card title="故事分析">
          <Space vertical align="start" spacing="loose">
            <Descriptions
              data={[
                { key: '类型', value: status.story_analysis.genre || '-' },
                { key: '基调', value: status.story_analysis.tone || '-' },
                { key: '主题', value: status.story_analysis.themes?.join('、') || '-' },
              ]}
            />

            {status.story_analysis.plot_summary && (
              <Space vertical align="start">
                <Text type="tertiary" strong>故事梗概</Text>
                <Paragraph type="tertiary">{status.story_analysis.plot_summary}</Paragraph>
              </Space>
            )}

            {status.story_analysis.characters?.length > 0 && (
              <Space vertical align="start">
                <Text type="tertiary" strong>角色</Text>
                <Space wrap align="start">
                  {status.story_analysis.characters.map((c: { name: string; appearance?: string; personality?: string }) => {
                    const refEntry = refEntries.find(e => e.key === c.name && e.refType === 'character')
                    return (
                      <Card key={c.name} title={c.name}>
                        <Space align="start">
                          {refEntry?.imageUrl && (
                            <PreviewImage src={refEntry.localPreview || refEntry.imageUrl} alt={c.name} width={44} height={44} />
                          )}
                          <Space vertical align="start">
                            {c.appearance && <Text type="tertiary">外貌：{c.appearance}</Text>}
                            {c.personality && <Text type="tertiary">性格：{c.personality}</Text>}
                          </Space>
                        </Space>
                      </Card>
                    )
                  })}
                </Space>
              </Space>
            )}
          </Space>
        </Card>
      )}

      {/* Cost breakdown */}
      {status?.cost_total != null && (
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
      )}

      {/* Screenplay */}
      {status?.screenplay && (
        <Card
          title="剧本"
          headerExtraContent={isAtScreenplayReview && (
            <Space>
              <Button type="primary" size="small" loading={reviewLoading} onClick={() => handleApproveScreenplay(true)}>通过</Button>
              <Button type="warning" size="small" loading={reviewLoading}
                onClick={() => {
                  setReviewNotesAndRef('')
                  Modal.confirm({
                    title: '提交修改意见',
                    content: <TextArea placeholder="请描述需要修改的内容..." rows={4} onChange={v => setReviewNotesAndRef(v)} />,
                    onOk: () => handleApproveScreenplay(false),
                    onCancel: () => setReviewNotesAndRef(''),
                  })
                }}
              >修改</Button>
            </Space>
          )}
        >
          <Space vertical align="start">
            {isAtScreenplayReview && (
              <Banner
                type="info"
                fullMode={false}
                closeIcon={null}
                description="等待您审核剧本，确认内容后点击「通过」，或提交修改意见"
              />
            )}
            <pre>{status.screenplay}</pre>
          </Space>
        </Card>
      )}

      {/* Storyboard */}
      {status?.shots && status.shots.length > 0 && (
        <Card title={`分镜脚本 · ${status.shots.length} 个镜头`}>
          <Table size="small" dataSource={status.shots} rowKey="shot_id" pagination={false}
            expandRowByClick
            expandedRowRender={(row: any) => (
              <Space vertical align="start">
                <Space>
                  <Text type="tertiary" strong>地点：</Text>
                  <Text type="tertiary">{row.location || '（未指定）'}</Text>
                </Space>
                <Space>
                  <Text type="tertiary" strong>动作：</Text>
                  <Text type="tertiary">{row.action || '（无动作描述）'}</Text>
                </Space>
                <Space>
                  <Text type="tertiary" strong>台词：</Text>
                  <Text type="tertiary">{row.dialogue || '（无台词）'}</Text>
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
      )}

      {/* Look assignment review */}
      {isAtLookReview && (
        <Card title="审核服装造型（场景 → 角色 → 造型）">
          <Space vertical align="start" spacing="medium">
            <Banner
              type="info"
              fullMode={false}
              closeIcon={null}
              description="确认每个场景中各角色所穿的造型，可调整后确认，或退回重新指派"
            />
            {Object.entries(lookAssignmentsDraft).map(([scene, byName]) => (
              <Space vertical align="start" key={scene}>
                <Text strong>{`场景 ${scene}`}</Text>
                {Object.entries(byName).map(([name, lookId]) => (
                  <Space key={name} align="center">
                    <Text>{name}</Text>
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
                  </Space>
                ))}
              </Space>
            ))}
            <Space>
              <Button type="primary" theme="solid" loading={reviewLoading}
                onClick={() => handleApproveLooks(true)}>确认造型</Button>
              <Button loading={reviewLoading} onClick={() => handleApproveLooks(false)}>退回重排</Button>
            </Space>
          </Space>
        </Card>
      )}

      {/* Prompts */}
      {status?.prompts && status.prompts.length > 0 && (
        <Card
          title={`视频 Prompt · ${status.prompts.length} 个`}
          headerExtraContent={isAtPromptsReview && (
            <Space>
              <Button type="primary" size="small" loading={reviewLoading} onClick={() => handleApprovePrompts(true)}>
                全部确认，开始生成视频
              </Button>
              <Button type="warning" size="small" loading={reviewLoading}
                onClick={() => {
                  setReviewNotesAndRef('')
                  Modal.confirm({
                    title: '提交修改意见',
                    content: <TextArea placeholder="请描述 Prompt 需要调整的地方..." rows={4} onChange={v => setReviewNotesAndRef(v)} />,
                    onOk: () => handleApprovePrompts(false),
                    onCancel: () => setReviewNotesAndRef(''),
                  })
                }}
              >退回重新生成</Button>
            </Space>
          )}
        >
          <Space vertical align="start">
            {isAtPromptsReview && (
              <Banner
                type="info"
                fullMode={false}
                closeIcon={null}
                description="请检查并编辑各镜头的 Prompt，确认无误后点击「全部确认」"
              />
            )}
            <List
              dataSource={status.prompts}
              renderItem={(p: { shot_id: string; prompt_text: string; edited_prompt?: string; negative_prompt?: string; edited_negative_prompt?: string }) => {
                const shot = status.shots?.find((s: { shot_id: string; scene_number?: number; shot_number?: number; shot_type?: string; duration_seconds?: number }) => s.shot_id === p.shot_id)
                // 空串是"用户主动清空"的有效值,不能用 || 回落到原始值
                const displayNegative = p.edited_negative_prompt ?? p.negative_prompt
                return (
                  <List.Item key={p.shot_id}>
                    <Space vertical align="start">
                      <Space wrap>
                        {shot && <><Tag>场景{shot.scene_number}-镜头{shot.shot_number}</Tag><Tag color="blue">{shot.shot_type}</Tag><Tag>{shot.duration_seconds}s</Tag></>}
                      </Space>
                      {isAtPromptsReview ? (
                        <TextArea value={editedPrompts[p.shot_id] ?? p.prompt_text} onChange={v => setEditedPrompts(prev => ({ ...prev, [p.shot_id]: v }))} rows={3} />
                      ) : (
                        <Text type="tertiary">{p.edited_prompt || p.prompt_text}</Text>
                      )}
                      {isAtPromptsReview ? (
                        <TextArea
                          value={editedNegativePrompts[p.shot_id] ?? p.negative_prompt ?? ''}
                          onChange={v => setEditedNegativePrompts(prev => ({ ...prev, [p.shot_id]: v }))}
                          rows={2}
                        />
                      ) : (
                        displayNegative ? <Text type="tertiary">负向：{displayNegative}</Text> : null
                      )}
                    </Space>
                  </List.Item>
                )
              }}
            />
          </Space>
        </Card>
      )}

      {/* Keyframes review */}
      {isAtKeyframesReview && (
        <Card title="审核关键帧（勾选要重生成的镜头）">
          <Space vertical align="start" spacing="medium">
            <Banner
              type="info"
              fullMode={false}
              closeIcon={null}
              description="确认各镜头关键帧，满意则开始生成视频；不满意可勾选后提交重生成"
            />
            <List
              dataSource={status?.prompts || []}
              renderItem={(p: { shot_id: string; prompt_text: string; keyframe_url?: string | null }) => {
                const shot = status?.shots?.find((s: { shot_id: string; scene_number?: number; shot_number?: number }) => s.shot_id === p.shot_id)
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
                    extra={
                      <Checkbox
                        checked={regenSelection.includes(p.shot_id)}
                        onChange={e => setRegenSelection(prev => e.target.checked
                          ? [...prev, p.shot_id]
                          : prev.filter(x => x !== p.shot_id))}
                      >重生成</Checkbox>
                    }
                  />
                )
              }}
            />
            <Space>
              <Button type="primary" theme="solid" loading={reviewLoading}
                onClick={() => handleApproveKeyframes(true)}>确认，生成视频</Button>
              <Button loading={reviewLoading} disabled={!regenSelection.length}
                onClick={() => handleApproveKeyframes(false)}>重生成所选</Button>
            </Space>
          </Space>
        </Card>
      )}

      {/* Videos */}
      {status?.videos && status.videos.length > 0 && (
        <Card title="视频生成进度">
          <List
            dataSource={status.videos}
            renderItem={(v: { shot_id: string; status: string; local_path?: string; error?: string }) => {
              const shot = status.shots?.find((s: { shot_id: string; scene_number?: number; shot_number?: number }) => s.shot_id === v.shot_id)
              return (
                <List.Item key={v.shot_id}>
                  <Space vertical align="start">
                    <Space align="center">
                      <Text>场景{shot?.scene_number}-镜头{shot?.shot_number}</Text>
                      <Tag color={v.status === 'succeeded' ? 'green' : v.status === 'failed' ? 'red' : 'blue'}>
                        {v.status === 'succeeded' ? '完成' : v.status === 'failed' ? '失败' : '生成中'}
                      </Tag>
                    </Space>
                    {v.status === 'running' && (
                      <Space align="center">
                        <Spin size="small" />
                        <Text type="tertiary">生成中...</Text>
                      </Space>
                    )}
                    {v.status === 'succeeded' && v.local_path && episodeId && (
                      <VideoPlayer
                        src={filesApi.downloadUrl(episodeId, `${v.shot_id}.mp4`)}
                        title={`场景${shot?.scene_number} · 镜头${shot?.shot_number}`}
                      />
                    )}
                    {v.status === 'failed' && <Text type="danger" size="small">错误: {v.error}</Text>}
                    {episodeId && <ShotArtifactPanel episodeId={episodeId} projectId={projectId ?? ''} shotId={v.shot_id} />}
                  </Space>
                </List.Item>
              )
            }}
          />
        </Card>
      )}

      {/* Final video */}
      {status?.assembled_video_path && episodeId && (
        <Card title="✦ 最终成片">
          <Space vertical align="start">
            <VideoPlayer src={filesApi.exportUrl(episodeId)} title="完整成片" />
            <Button colorful theme="solid" type="primary" icon={<IconDownload />} onClick={() => {
              const a = document.createElement('a')
              a.href = filesApi.exportUrl(episodeId!)
              a.download = `${episode?.title || 'final'}.mp4`
              a.click()
            }}>
              下载完整视频
            </Button>
          </Space>
        </Card>
      )}

      {/* Error */}
      {episode.error_message && (
        <Card title="错误信息">
          <Text type="danger">{episode.error_message}</Text>
        </Card>
      )}
      </Space>
    </PageShell>
  )
}
