import { useCallback, useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button, Tag, Modal, Toast, List, Typography, Space, Row, Col, Select } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus, IconUser } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import AdaptationPanel from '../components/AdaptationPanel'
import ClipGallery from '../components/ClipGallery'
import { projectsApi, episodesApi, clipsApi, Project, Episode, Clip } from '../services/api'
import { VISUAL_STYLES } from '../constants/visual_styles'

const { Text } = Typography

// 展示名由 VISUAL_STYLES 派生 —— 取值权威在后端 db.enums.VisualStyle,前端只做中文展示。
const VISUAL_STYLE_LABEL: Record<string, string> = Object.fromEntries(
  VISUAL_STYLES.map(s => [s.value, s.label])
)

const STATUS_COLOR: Record<string, TagColor> = {
  created: 'grey', queued: 'blue', running: 'blue', paused: 'orange',
  completed: 'green', failed: 'red',
}
const STATUS_LABEL: Record<string, string> = {
  created: '待启动', queued: '排队中', running: '制作中', paused: '待审核',
  completed: '已完成', failed: '失败',
}

export default function ProjectEpisodesPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  // 改编切出、尚未建集的剧本数(由面板下发,本页不重复拉改编状态)
  const [pendingScripts, setPendingScripts] = useState(0)
  const [clips, setClips] = useState<Clip[]>([])
  const [styleEditing, setStyleEditing] = useState(false)
  const [styleDraft, setStyleDraft] = useState('')
  const [styleSaving, setStyleSaving] = useState(false)

  const load = useCallback(() => {
    if (!id) return
    setLoading(true)
    projectsApi.get(id)
      .then(p => { setProject(p); setFetchError(false) })
      .catch(() => setFetchError(true))
      .finally(() => setLoading(false))
  }, [id])
  useEffect(() => { load() }, [load])

  const loadClips = useCallback(() => {
    if (!id) return
    clipsApi.list(id).then(setClips).catch(() => setClips([]))
  }, [id])
  useEffect(() => { loadClips() }, [loadClips])

  const saveVisualStyle = async () => {
    if (!id || !styleDraft) return
    setStyleSaving(true)
    try {
      await projectsApi.update(id, { visual_style: styleDraft })
      setProject(p => p ? { ...p, visual_style: styleDraft } : p)
      setStyleEditing(false)
      Toast.success('风格已更新，仅影响后续新产出的画面')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('更新失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setStyleSaving(false)
    }
  }

  const episodes: Episode[] = project?.episodes || []

  const renderItem = (ep: Episode) => (
    <List.Item
      onClick={() => navigate(`/episodes/${ep.id}`)}
      main={
        <Space>
          <Text type="tertiary">EP {String(ep.episode_number).padStart(2, '0')}</Text>
          <Text strong>{ep.title}</Text>
          <Text type="tertiary">{ep.video_provider}</Text>
        </Space>
      }
      extra={
        <Space>
          <Text type="tertiary">{ep.cost_unpriced ? '未定价' : `¥${(ep.cost_total ?? 0).toFixed(2)}`}</Text>
          <Tag color={STATUS_COLOR[ep.status] || 'grey'}>{STATUS_LABEL[ep.status] || ep.status}</Tag>
          <Button type="danger" theme="borderless"
            onClick={(e) => {
              e.stopPropagation()
              Modal.confirm({
                title: '删除该集', content: `删除「${ep.title}」后无法恢复,确定继续?`,
                okType: 'danger', okText: '删除', cancelText: '取消',
                onOk: async () => {
                  try { await episodesApi.delete(id!, ep.id); Toast.success('已删除'); load() }
                  catch { Toast.error('删除失败') }
                },
              })
            }}>删除</Button>
        </Space>
      }
    />
  )

  return (
    <PageShell
      title={project?.title || '项目'}
      description={`共 ${episodes.length} 集${clips.length ? ` · ${clips.length} 支散片` : ''}`}
      breadcrumb={[{ label: '作品列表', href: '/' }, { label: project?.title || '项目' }]}
      headerExtra={
        <Space>
          {project && (
            <Tag onClick={() => { setStyleDraft(project.visual_style); setStyleEditing(true) }}>
              {VISUAL_STYLE_LABEL[project.visual_style] || project.visual_style}
            </Tag>
          )}
          <Button icon={<IconUser />} onClick={() => navigate(`/projects/${id}/characters`)}>角色管理</Button>
          <Button colorful theme="solid" icon={<IconPlus />} type="primary" onClick={() => navigate(`/projects/${id}/create`)}>
            新建创作
          </Button>
        </Space>
      }
    >
      {loading ? (
        <PageLoading />
      ) : fetchError ? (
        <PageEmpty variant="error" title="加载失败" description="无法获取项目详情,请检查网络或后端服务">
          <Button onClick={load}>重试</Button>
        </PageEmpty>
      ) : (
        <Row gutter={[0, 16]}>
          {/* 是否小说作品由面板自己按后端 adaptation 状态判定,非小说作品它渲染 null */}
          <Col span={24}>
            <AdaptationPanel projectId={id!} onCommitted={load}
              onPendingScripts={setPendingScripts} />
          </Col>
          <Col span={24}>
            {episodes.length === 0 ? (
              // 上方已切出剧本时,别把用户支去「新建创作」—— 该点的是「建出 N 集」。
              // 两处指向不同动作会让人以为改编白做了。
              pendingScripts > 0 ? (
                <PageEmpty
                  title="还没有剧集"
                  description={`已切出 ${pendingScripts} 个剧本，点上方「建出 ${pendingScripts} 集」即可生成剧集`}
                />
              ) : (
                <PageEmpty title="还没有剧集" description="点击右上角「新建创作」开始" />
              )
            ) : (
              <List dataSource={episodes} renderItem={renderItem} />
            )}
          </Col>
          {/* 散片区块:历史入口。空散片时不渲染 —— 大多数作品只走完整剧集,
              永久占一块空态会让页面显得有个没用的功能 */}
          {clips.length > 0 && (
            <Col span={24}>
              <ClipGallery projectId={id!} clips={clips} onRefresh={loadClips} />
            </Col>
          )}
        </Row>
      )}
      <Modal
        title="修改视觉风格" visible={styleEditing} onCancel={() => setStyleEditing(false)}
        onOk={saveVisualStyle} okText="保存" cancelText="取消" confirmLoading={styleSaving}
      >
        <Select
          aria-label="视觉风格"
          value={styleDraft}
          onChange={v => setStyleDraft(String(v ?? ''))}
        >
          {VISUAL_STYLES.map(s => <Select.Option key={s.value} value={s.value}>{s.label}</Select.Option>)}
        </Select>
      </Modal>
    </PageShell>
  )
}
