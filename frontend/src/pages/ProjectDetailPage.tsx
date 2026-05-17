import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Steps, Button, Tag, Spin, Toast, TextArea, Table, Progress, Modal, Typography, Upload, Input } from '@douyinfe/semi-ui'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconUpload, IconDownload, IconPlay, IconPause, IconPlus, IconClose, IconUser, IconHome } from '@douyinfe/semi-icons'
import { workflowApi, filesApi, projectsApi, createWebSocket, WorkflowStatus, Project } from '../services/api'

const { Text } = Typography

const STAGE_STEP: Record<string, number> = {
  starting: 0, analyzing: 0, story_analyzed: 0,
  screenplay_written: 1, screenplay_review: 2, screenplay_approved: 2,
  screenplay_revision_requested: 1,
  storyboard_ready: 3, prompts_ready: 4, prompts_review: 4, prompts_approved: 4,
  prompts_revision_requested: 4,
  videos_generated: 5, assembly_failed: 5, completed: 6,
}

const STATUS_LABEL: Record<string, string> = {
  created: '待启动', starting: '启动中', analyzing: '故事分析中', story_analyzed: '分析完成',
  screenplay_written: '剧本生成中', screenplay_review: '审核剧本', screenplay_approved: '剧本通过',
  screenplay_revision_requested: '剧本修改中', storyboard_ready: '分镜完成',
  prompts_ready: 'Prompt生成中', prompts_review: '审核Prompt', prompts_approved: 'Prompt确认',
  prompts_revision_requested: 'Prompt修改中', videos_generated: '视频完成',
  assembly_failed: '合成失败', completed: '制作完成', failed: '失败',
}

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
  entries,
  onChange,
  autoAddType,
  onAutoAddConsumed,
}: {
  projectId: string
  entries: RefEntry[]
  onChange: (entries: RefEntry[]) => void
  autoAddType?: 'character' | 'background' | null
  onAutoAddConsumed?: () => void
}) {
  const [addingType, setAddingType] = useState<'character' | 'background' | null>(null)
  const [newKey, setNewKey] = useState('')
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
      await filesApi.updateReferences(projectId, latest.map(e => ({
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

  const characters = entries.filter(e => e.refType === 'character')
  const backgrounds = entries.filter(e => e.refType === 'background')

  const renderGroup = (group: RefEntry[], label: string, refType: 'character' | 'background') => (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {refType === 'character' ? <IconUser style={{ color: '#7C3AED', fontSize: 12 }} /> : <IconHome style={{ color: '#3B82F6', fontSize: 12 }} />}
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#9CA3AF' }}>{label}</span>
        </div>
        <Button
          size="small" type="tertiary" icon={<IconPlus />}
          onClick={() => { setAddingType(refType); setNewKey('') }}
          style={{ fontSize: 11, height: 24, padding: '0 8px' }}
        >
          添加
        </Button>
      </div>

      {group.length === 0 && (
        <div style={{ fontSize: 12, color: '#C4C9D4', padding: '8px 0', fontStyle: 'italic' }}>
          暂无{label}，点击「添加」新增
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {group.map(entry => (
          <div key={entry.id} className="ref-row">
            {/* Thumbnail */}
            <Upload
              action=""
              accept="image/*"
              showUploadList={false}
              beforeUpload={({ file }: { file: FileItem }) => {
                if (file.fileInstance) handleUpload(entry, file.fileInstance)
                return { autoRemove: false, status: 'validateFail', shouldUpload: false }
              }}
            >
              <div className={`ref-thumb-upload ${entry.uploading ? 'uploading' : ''}`}>
                {entry.localPreview || entry.imageUrl ? (
                  <img
                    src={entry.localPreview || entry.imageUrl}
                    alt={entry.key}
                    style={{ width: '100%', height: '100%', objectFit: 'cover', borderRadius: 7 }}
                  />
                ) : (
                  <div className="ref-thumb-empty">
                    <IconUpload style={{ fontSize: 14, color: entry.uploading ? '#7C3AED' : '#C4C9D4' }} />
                  </div>
                )}
                {entry.uploading && <div className="ref-thumb-overlay"><Spin size="small" /></div>}
              </div>
            </Upload>

            {/* Name */}
            <span className="ref-row-name">{entry.key}</span>

            {/* Status */}
            {entry.imageUrl ? (
              <Tag size="small" color="green" style={{ fontSize: 10 }}>已绑定</Tag>
            ) : (
              <Tag size="small" color="grey" style={{ fontSize: 10 }}>未上传</Tag>
            )}

            {/* Clear image */}
            {entry.imageUrl && (
              <Button
                size="small" type="tertiary" theme="borderless"
                style={{ color: '#9CA3AF', padding: '0 4px', height: 22, fontSize: 11 }}
                onClick={async () => {
                  update(entry.id, { imageUrl: '', localPreview: '' })
                  const latest = entriesRef.current
                  await filesApi.updateReferences(projectId, latest.map(e =>
                    e.id === entry.id ? { key: e.key, ref_type: e.refType, image_url: '' } : { key: e.key, ref_type: e.refType, image_url: e.imageUrl }
                  ))
                }}
              >清除图片</Button>
            )}

            {/* Delete row */}
            <button
              className="ref-row-delete"
              onClick={async () => {
                remove(entry.id)
                const latest = entriesRef.current.filter(e => e.id !== entry.id)
                await filesApi.updateReferences(projectId, latest.map(e => ({
                  key: e.key, ref_type: e.refType, image_url: e.imageUrl
                })))
              }}
            >
              <IconClose style={{ fontSize: 11 }} />
            </button>
          </div>
        ))}
      </div>

      {/* Inline add form */}
      {addingType === refType && (
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
          <Input
            placeholder={refType === 'character' ? '输入角色名称' : '输入场景地点'}
            value={newKey}
            onChange={setNewKey}
            onEnterPress={handleAddEntry}
            size="small"
            style={{ flex: 1 }}
            autoFocus
          />
          <Button size="small" type="primary" onClick={handleAddEntry} disabled={!newKey.trim()}>确认</Button>
          <Button size="small" type="tertiary" onClick={() => { setAddingType(null); setNewKey('') }}>取消</Button>
        </div>
      )}
    </div>
  )

  return (
    <div>
      {renderGroup(characters, '角色参考图', 'character')}
      <div style={{ height: 1, background: 'rgba(255,255,255,0.4)', margin: '4px 0 16px' }} />
      {renderGroup(backgrounds, '背景参考图', 'background')}
    </div>
  )
}

// ── Video Player ─────────────────────────────────────────────────────────────
function VideoPlayer({ src, title }: { src: string; title?: string }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0)
  const [duration, setDuration] = useState(0)
  const [currentTime, setCurrentTime] = useState(0)

  const togglePlay = () => {
    const v = videoRef.current
    if (!v) return
    if (v.paused) { v.play(); setPlaying(true) }
    else { v.pause(); setPlaying(false) }
  }

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60)
    return `${m}:${Math.floor(s % 60).toString().padStart(2, '0')}`
  }

  const handleSeek = (e: React.MouseEvent<HTMLDivElement>) => {
    const v = videoRef.current
    if (!v || !duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    v.currentTime = ((e.clientX - rect.left) / rect.width) * duration
  }

  return (
    <div className="video-player-wrap">
      {title && <div className="video-player-title">{title}</div>}
      <div className="video-player-screen" onClick={togglePlay}>
        <video
          ref={videoRef}
          src={src}
          style={{ width: '100%', display: 'block', borderRadius: '10px 10px 0 0' }}
          onTimeUpdate={e => {
            const v = e.currentTarget
            setCurrentTime(v.currentTime)
            setProgress(v.duration ? (v.currentTime / v.duration) * 100 : 0)
          }}
          onLoadedMetadata={e => setDuration(e.currentTarget.duration)}
          onEnded={() => setPlaying(false)}
        />
        {!playing && (
          <div className="video-play-overlay">
            <div className="video-play-btn"><IconPlay size="extra-large" /></div>
          </div>
        )}
      </div>
      <div className="video-controls">
        <button className="video-ctrl-btn" onClick={togglePlay}>
          {playing ? <IconPause /> : <IconPlay />}
        </button>
        <span className="video-time">{formatTime(currentTime)}</span>
        <div className="video-progress-bar" onClick={handleSeek}>
          <div className="video-progress-fill" style={{ width: `${progress}%` }} />
        </div>
        <span className="video-time">{formatTime(duration)}</span>
        <button className="video-ctrl-btn" onClick={() => {
          const a = document.createElement('a')
          a.href = src
          a.download = title || 'video.mp4'
          a.click()
        }}>
          <IconDownload />
        </button>
      </div>
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [status, setStatus] = useState<WorkflowStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [editedPrompts, setEditedPrompts] = useState<Record<string, string>>({})
  const [reviewNotes, setReviewNotes] = useState('')
  const reviewNotesRef = useRef('')
  const setReviewNotesAndRef = (v: string) => { setReviewNotes(v); reviewNotesRef.current = v }
  const [starting, setStarting] = useState(false)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [refEntries, setRefEntries] = useState<RefEntry[]>([])
  const [pendingAddType, setPendingAddType] = useState<'character' | 'background' | null>(null)
  const [rawInputExpanded, setRawInputExpanded] = useState(false)
  const [storyRawExpanded, setStoryRawExpanded] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const refEntriesInitialized = useRef(false)
  const projectStatusRef = useRef<string>('created')

  const refreshStatus = useCallback(async () => {
    if (!id) return
    const [proj, wfStatus] = await Promise.all([
      projectsApi.get(id),
      workflowApi.status(id).catch(() => null),
    ])
    setProject(proj)
    if (proj) projectStatusRef.current = proj.status
    if (wfStatus) {
      setStatus(wfStatus)
      // Re-sync ref entries whenever story_analysis or shots bring new data
      if (!refEntriesInitialized.current) {
        const serverRefs = wfStatus.character_references || {}
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
  }, [id])

  useEffect(() => {
    if (!id) return
    refreshStatus().finally(() => setLoading(false))
    const ws = createWebSocket(id, (event) => {
      if (event.type === 'stage_change') {
        const stage: string = event.data?.stage || ''
        if (stage === 'story_analyzed' || stage === 'storyboard_ready') {
          refEntriesInitialized.current = false
        }
        refreshStatus()
      }
      if (event.type === 'error') Toast.error('工作流错误: ' + event.data?.message)
    })
    wsRef.current = ws
    ws.onclose = (e) => {
      const INACTIVE = ['created', 'completed', 'failed', 'assembly_failed']
      if (!e.wasClean && !INACTIVE.includes(projectStatusRef.current)) {
        Toast.warning({ content: '实时连接已断开，请刷新页面获取最新状态', duration: 0 })
      }
    }
    return () => { ws.onclose = null; ws.close() }
  }, [id, refreshStatus])

  const handleStart = async () => {
    if (!id || starting) return
    setStarting(true)
    try {
      // Persist any pre-set references before starting
      if (refEntries.some(e => e.imageUrl)) {
        await filesApi.updateReferences(id, refEntries.map(e => ({
          key: e.key, ref_type: e.refType, image_url: e.imageUrl
        })))
      }
      await workflowApi.start(id)
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
    if (!id || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(id, { approved, notes: reviewNotesRef.current })
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
    if (!id || reviewLoading) return
    setReviewLoading(true)
    try {
      await workflowApi.resume(id, { approved, notes: reviewNotes, edited_prompts: editedPrompts })
      setReviewNotes('')
      Toast.success(approved ? '确认完成，开始生成视频' : '已提交修改意见')
      await refreshStatus()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setReviewLoading(false)
    }
  }

  if (loading) return (
    <div style={{ textAlign: 'center', marginTop: 120 }}>
      <Spin size="large" />
      <div style={{ color: '#9CA3AF', marginTop: 16, fontSize: 12, letterSpacing: '0.5px' }}>载入中...</div>
    </div>
  )

  if (!project) return (
    <div style={{ textAlign: 'center', marginTop: 120, color: '#9CA3AF' }}>
      <div style={{ marginBottom: 16 }}>项目未找到</div>
      <Button type="tertiary" onClick={() => navigate('/')}>返回列表</Button>
    </div>
  )

  const stage = status?.current_stage || project.status
  const nextNodes = status?.next || []
  const effectiveStage = nextNodes.includes('screenplay_review') ? 'screenplay_review'
    : nextNodes.includes('prompts_review') ? 'prompts_review'
    : stage
  const stepIndex = STAGE_STEP[effectiveStage] ?? 0
  const isAtScreenplayReview = stage === 'screenplay_review' || nextNodes.includes('screenplay_review')
  const isAtPromptsReview = stage === 'prompts_review' || nextNodes.includes('prompts_review')
  const PAUSED_OR_TERMINAL = ['created', 'completed', 'failed', 'assembly_failed']
  const isRunning = !PAUSED_OR_TERMINAL.includes(stage) && !isAtScreenplayReview && !isAtPromptsReview

  const sectionHeader = (title: string, extra?: React.ReactNode) => (
    <div className="glass-card-header">
      <span className="glass-card-title">{title}</span>
      {extra}
    </div>
  )

  return (
    <div>
      {/* Project header */}
      <div style={{ marginBottom: 28 }}>
        <button
          onClick={() => navigate('/')}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', fontSize: 12, padding: '0 0 10px 0', display: 'flex', alignItems: 'center', gap: 4 }}
        >
          ← 返回列表
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: '#111827', letterSpacing: '-0.4px', margin: 0 }}>
            {project.title}
          </h1>
          <Tag>{project.genre}</Tag>
          <Tag color="blue">{{ seedance: 'Seedance 2.0', bailian: '万相 2.7' }[project.video_provider] ?? project.video_provider}</Tag>
          {isRunning && (
            <span style={{ display: 'inline-flex', alignItems: 'center', fontSize: 12, color: '#7C3AED', fontWeight: 500 }}>
              <span className="status-dot" />
              {STATUS_LABEL[stage] || stage}
            </span>
          )}
          {!isRunning && stage !== 'created' && (
            <span style={{ fontSize: 12, color: '#9CA3AF' }}>{STATUS_LABEL[stage] || stage}</span>
          )}
        </div>
      </div>

      {/* Progress steps */}
      <div className="glass-card" style={{ padding: '20px 28px', marginBottom: 20 }}>
        <Steps current={stepIndex}>
          <Steps.Step title="故事分析" description="提取角色情节" />
          <Steps.Step title="生成剧本" description="专业格式" />
          <Steps.Step title="审核剧本" description="人工确认" />
          <Steps.Step title="分镜" description="拆分镜头" />
          <Steps.Step title="Prompt" description="视频提示词" />
          <Steps.Step title="生成视频" description="AI 合成" />
          <Steps.Step title="完成" description="最终成片" />
        </Steps>
      </div>

      {/* Start CTA (created state) */}
      {project.status === 'created' && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          <div style={{ padding: '32px 32px 24px' }}>
            <div style={{ textAlign: 'center', marginBottom: 28 }}>
              <div className="start-cta-title">项目准备就绪</div>
              <div className="start-cta-desc">
                AI 将自动完成故事分析、剧本创作、分镜规划、Prompt 生成和视频合成<br />
                您可提前上传角色/背景参考图，也可在流程启动后随时补充
              </div>
            </div>

            {/* Raw input preview */}
            {project.raw_input && (
              <div className="glass-inset" style={{ marginBottom: 16 }}>
                <div
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 20px', cursor: 'pointer', userSelect: 'none' }}
                  onClick={() => setRawInputExpanded(v => !v)}
                >
                  <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#9CA3AF' }}>故事内容</span>
                  <span style={{ fontSize: 11, color: '#9CA3AF' }}>{rawInputExpanded ? '收起 ▲' : '展开 ▼'}</span>
                </div>
                {rawInputExpanded && (
                  <div style={{ padding: '0 20px 16px', fontSize: 13, color: '#4B5563', lineHeight: 1.8, whiteSpace: 'pre-wrap', maxHeight: 300, overflowY: 'auto' }}>
                    {project.raw_input}
                  </div>
                )}
              </div>
            )}
            <div className="glass-inset" style={{ marginBottom: 24 }}>
              {sectionHeader('参考图片（选填）', (
                <span style={{ fontSize: 11, color: '#9CA3AF' }}>启动后亦可修改</span>
              ))}
              <div style={{ padding: '16px 20px' }}>
                <ReferencesPanel
                    projectId={id!}
                    entries={refEntries}
                    onChange={setRefEntries}
                    autoAddType={pendingAddType}
                    onAutoAddConsumed={() => setPendingAddType(null)}
                  />
              </div>
            </div>

            <div style={{ textAlign: 'center' }}>
              <Button type="primary" size="large" loading={starting} onClick={handleStart} style={{ minWidth: 160 }}>
                开始制作
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Reference images panel (after start) */}
      {project.status !== 'created' && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader('参考图片')}
          <div style={{ padding: '16px 20px' }}>
            <ReferencesPanel
              projectId={id!}
              entries={refEntries}
              onChange={setRefEntries}
            />
          </div>
        </div>
      )}

      {/* Story Analysis */}
      {status?.story_analysis && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader('故事分析', project.raw_input && (
            <button
              onClick={() => setStoryRawExpanded(v => !v)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 11, color: '#9CA3AF', padding: '2px 8px' }}
            >
              {storyRawExpanded ? '收起原文 ▲' : '查看原文 ▼'}
            </button>
          ))}
          {storyRawExpanded && project.raw_input && (
            <div style={{ margin: '0 20px', padding: '14px 16px', background: 'rgba(0,0,0,0.03)', borderRadius: 8, borderLeft: '3px solid rgba(124,58,237,0.2)', marginBottom: 4 }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#9CA3AF', marginBottom: 8 }}>原始故事</div>
              <div style={{ fontSize: 13, color: '#4B5563', lineHeight: 1.8, whiteSpace: 'pre-wrap', maxHeight: 260, overflowY: 'auto' }}>
                {project.raw_input}
              </div>
            </div>
          )}
          <div className="glass-card-body">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 20, marginBottom: 20 }}>
              {[
                { k: '类型', v: status.story_analysis.genre },
                { k: '基调', v: status.story_analysis.tone },
                { k: '主题', v: status.story_analysis.themes?.join('、') },
              ].map(({ k, v }) => (
                <div key={k}>
                  <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#9CA3AF', marginBottom: 5 }}>{k}</div>
                  <div style={{ color: '#374151', fontSize: 13 }}>{v || '-'}</div>
                </div>
              ))}
            </div>
            {status.story_analysis.plot_summary && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#9CA3AF', marginBottom: 8 }}>故事梗概</div>
                <div style={{ fontSize: 13, color: '#4B5563', lineHeight: 1.75, paddingLeft: 12, borderLeft: '3px solid rgba(124,58,237,0.25)', borderRadius: '0 4px 4px 0' }}>
                  {status.story_analysis.plot_summary}
                </div>
              </div>
            )}
            {status.story_analysis.characters?.length > 0 && (
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase', color: '#9CA3AF', marginBottom: 12 }}>角色</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(220px,1fr))', gap: 10 }}>
                  {status.story_analysis.characters.map((c: { name: string; appearance?: string; personality?: string }) => {
                    const refEntry = refEntries.find(e => e.key === c.name && e.refType === 'character')
                    return (
                      <div key={c.name} className="character-card">
                        <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                          {refEntry?.imageUrl && (
                            <img src={refEntry.localPreview || refEntry.imageUrl} alt={c.name}
                              style={{ width: 44, height: 44, borderRadius: 6, objectFit: 'cover', flexShrink: 0, border: '1px solid rgba(255,255,255,0.7)' }} />
                          )}
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div className="character-name">{c.name}</div>
                            {c.appearance && <div style={{ color: '#9CA3AF', fontSize: 11, marginBottom: 2 }}>外貌：{c.appearance}</div>}
                            {c.personality && <div style={{ color: '#9CA3AF', fontSize: 11 }}>性格：{c.personality}</div>}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Screenplay */}
      {status?.screenplay && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader('剧本', isAtScreenplayReview && (
            <div style={{ display: 'flex', gap: 8 }}>
              <Button type="primary" size="small" loading={reviewLoading} onClick={() => handleApproveScreenplay(true)}>通过</Button>
              <Button size="small" loading={reviewLoading}
                style={{ background: 'rgba(217,119,6,0.08)', borderColor: 'rgba(217,119,6,0.25)', color: '#D97706', borderRadius: '100px' }}
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
            </div>
          ))}
          <div className="glass-card-body">
            {isAtScreenplayReview && <div className="review-bar">等待您审核剧本，确认内容后点击「通过」，或提交修改意见</div>}
            <pre className="screenplay-block">{status.screenplay}</pre>
          </div>
        </div>
      )}

      {/* Storyboard */}
      {status?.shots && status.shots.length > 0 && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader(`分镜脚本 · ${status.shots.length} 个镜头`)}
          <div style={{ padding: '0 20px 16px' }}>
            <Table size="small" dataSource={status.shots} rowKey="shot_id" pagination={false} style={{ marginTop: 8 }}
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
          </div>
        </div>
      )}

      {/* Prompts */}
      {status?.prompts && status.prompts.length > 0 && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader(`视频 Prompt · ${status.prompts.length} 个`, isAtPromptsReview && (
            <Button type="primary" size="small" loading={reviewLoading} onClick={() => handleApprovePrompts(true)}>
              全部确认，开始生成视频
            </Button>
          ))}
          <div className="glass-card-body">
            {isAtPromptsReview && <div className="review-bar">请检查并编辑各镜头的 Prompt，确认无误后点击「全部确认」</div>}
            {status.prompts.map((p: { shot_id: string; prompt_text: string; edited_prompt?: string; negative_prompt?: string }) => {
              const shot = status.shots?.find((s: { shot_id: string; scene_number?: number; shot_number?: number; shot_type?: string; duration_seconds?: number }) => s.shot_id === p.shot_id)
              return (
                <div key={p.shot_id} className="prompt-item">
                  <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                    {shot && <><Tag>场景{shot.scene_number}-镜头{shot.shot_number}</Tag><Tag color="blue">{shot.shot_type}</Tag><Tag>{shot.duration_seconds}s</Tag></>}
                  </div>
                  {isAtPromptsReview ? (
                    <TextArea value={editedPrompts[p.shot_id] ?? p.prompt_text} onChange={v => setEditedPrompts(prev => ({ ...prev, [p.shot_id]: v }))} rows={3} style={{ fontFamily: 'monospace', fontSize: 12 }} />
                  ) : (
                    <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#4B5563', lineHeight: 1.6 }}>{p.edited_prompt || p.prompt_text}</div>
                  )}
                  {p.negative_prompt && <div style={{ marginTop: 5, color: '#9CA3AF', fontSize: 11 }}>负向：{p.negative_prompt}</div>}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Videos */}
      {status?.videos && status.videos.length > 0 && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader('视频生成进度')}
          <div className="glass-card-body">
            {status.videos.map((v: { shot_id: string; status: string; local_path?: string; error?: string }) => {
              const shot = status.shots?.find((s: { shot_id: string; scene_number?: number; shot_number?: number }) => s.shot_id === v.shot_id)
              return (
                <div key={v.shot_id} style={{ marginBottom: 24, paddingBottom: 24, borderBottom: '1px solid rgba(255,255,255,0.4)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                    <span style={{ fontSize: 13, color: '#374151', fontWeight: 500 }}>场景{shot?.scene_number}-镜头{shot?.shot_number}</span>
                    <Tag color={v.status === 'succeeded' ? 'green' : v.status === 'failed' ? 'red' : 'blue'}>
                      {v.status === 'succeeded' ? '完成' : v.status === 'failed' ? '失败' : '生成中'}
                    </Tag>
                  </div>
                  {v.status === 'running' && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                      <Spin size="small" />
                      <span style={{ fontSize: 12, color: '#7C3AED' }}>生成中...</span>
                    </div>
                  )}
                  {v.status === 'succeeded' && v.local_path && id && (
                    <VideoPlayer
                      src={filesApi.downloadUrl(id, `${v.shot_id}.mp4`)}
                      title={`场景${shot?.scene_number} · 镜头${shot?.shot_number}`}
                    />
                  )}
                  {v.status === 'failed' && <Text type="danger" size="small">错误: {v.error}</Text>}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Final video */}
      {status?.assembled_video_path && id && (
        <div className="glass-card" style={{ marginBottom: 20 }}>
          {sectionHeader('✦ 最终成片')}
          <div className="glass-card-body" style={{ textAlign: 'center' }}>
            <VideoPlayer src={filesApi.exportUrl(id)} title="完整成片" />
            <div style={{ marginTop: 20 }}>
              <Button type="primary" size="large" icon={<IconDownload />} onClick={() => {
                const a = document.createElement('a')
                a.href = filesApi.exportUrl(id!)
                a.download = `${project?.title || 'final'}.mp4`
                a.click()
              }} style={{ minWidth: 160 }}>
                下载完整视频
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {project.error_message && (
        <div className="glass-card" style={{ marginBottom: 20, borderColor: 'rgba(220,38,38,0.25)' }}>
          {sectionHeader('错误信息')}
          <div className="glass-card-body">
            <Text type="danger">{project.error_message}</Text>
          </div>
        </div>
      )}
    </div>
  )
}
