import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Col, Radio, RadioGroup, Row } from '@douyinfe/semi-ui'
import PageShell from '../components/PageShell'
import EpisodeCreateForm from '../components/EpisodeCreateForm'
import ClipCreateForm from '../components/ClipCreateForm'
import ClipGallery from '../components/ClipGallery'
import { clipsApi, configApi, projectsApi, Clip, VideoModelOption } from '../services/api'

/** 创作模式。**不落库、不进请求体** —— 两种模式走不同的表、不同的 job kind、
 *  不同的端点,没有任何一处需要按它分支。它只决定渲染哪套表单。 */
type Mode = 'episode' | 'clip'

/** 轮询间隔:一支视频几十秒到几分钟,3 秒足够。
 *  不为散片开 WebSocket —— Event.seq 按 episode 自增、WS 路由按集寻址,
 *  散片要用就得再开一条项目级通道,而用户就盯着这张卡片看。 */
const POLL_MS = 3000

export default function NewCreationPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const [mode, setMode] = useState<Mode>('episode')
  const [projectTitle, setProjectTitle] = useState('')
  const [clips, setClips] = useState<Clip[]>([])
  // 在页面级加载,而不是让 ClipCreateForm 自己拉:切到「直接生成」时它要立刻可用,
  // 而页面从打开那一刻就已经在加载,时间上总能早于用户切换模式。
  const [videoModels, setVideoModels] = useState<VideoModelOption[]>([])
  const [videoDefault, setVideoDefault] = useState('')

  useEffect(() => {
    if (projectId) projectsApi.get(projectId).then(p => setProjectTitle(p.title)).catch(() => {})
  }, [projectId])

  useEffect(() => {
    configApi.listVideoModels()
      .then(r => { setVideoModels(r.models); setVideoDefault(r.default || '') })
      .catch(() => {})
  }, [])

  const refresh = useCallback(() => {
    if (!projectId) return
    clipsApi.list(projectId).then(setClips).catch(() => {})
  }, [projectId])

  useEffect(() => { if (mode === 'clip') refresh() }, [mode, refresh])

  // 只在有未完成散片时轮询:全部终态后继续打接口是白耗
  const pending = clips.some(c => c.status === 'queued' || c.status === 'running')
  useEffect(() => {
    if (mode !== 'clip' || !pending) return
    const t = setInterval(refresh, POLL_MS)
    return () => clearInterval(t)
  }, [mode, pending, refresh])

  return (
    <PageShell
      title="新建创作"
      description="完整剧集走分析→剧本→分镜→审核的流水线；直接生成手写提示词，立刻出一支视频"
      breadcrumb={[
        { label: '作品列表', href: '/' },
        { label: projectTitle || '作品', href: `/projects/${projectId}` },
        { label: '新建创作' },
      ]}
    >
      <Row gutter={[0, 16]}>
        <Col span={24}>
          <Card>
            <RadioGroup
              value={mode}
              onChange={(e) => setMode(e.target.value as Mode)}
              aria-label="创作模式"
            >
              <Radio value="episode">完整剧集</Radio>
              <Radio value="clip">直接生成</Radio>
            </RadioGroup>
          </Card>
        </Col>
        <Col span={24}>
          {mode === 'episode' ? (
            <EpisodeCreateForm projectId={projectId!} />
          ) : (
            <ClipCreateForm
              projectId={projectId!}
              onCreated={(clip) => setClips(prev => [clip, ...prev])}
              models={videoModels}
              videoDefault={videoDefault}
              clips={clips}
            />
          )}
        </Col>
        {mode === 'clip' && (
          <Col span={24}>
            <ClipGallery projectId={projectId!} clips={clips} onRefresh={refresh} />
          </Col>
        )}
      </Row>
    </PageShell>
  )
}
