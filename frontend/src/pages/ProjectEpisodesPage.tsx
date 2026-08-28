import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button, Tag, Modal, Toast, List, Typography, Space, Row, Col } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus, IconUser } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import AdaptationPanel from '../components/AdaptationPanel'
import { projectsApi, episodesApi, Project, Episode } from '../services/api'

const { Text } = Typography

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

  const load = () => {
    if (!id) return
    setLoading(true)
    projectsApi.get(id)
      .then(p => { setProject(p); setFetchError(false) })
      .catch(() => setFetchError(true))
      .finally(() => setLoading(false))
  }
  useEffect(load, [id])

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
      description={`共 ${episodes.length} 集 · 逐集创作`}
      breadcrumb={[{ label: '作品列表', href: '/' }, { label: project?.title || '项目' }]}
      headerExtra={
        <Space>
          <Button icon={<IconUser />} onClick={() => navigate(`/projects/${id}/characters`)}>角色管理</Button>
          <Button colorful theme="solid" icon={<IconPlus />} type="primary" onClick={() => navigate(`/projects/${id}/episodes/new`)}>
            新建一集
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
          <Col span={24}><AdaptationPanel projectId={id!} onCommitted={load} /></Col>
          <Col span={24}>
            {episodes.length === 0 ? (
              <PageEmpty title="还没有剧集" description="点击右上角「新建一集」开始创作第 1 集" />
            ) : (
              <List dataSource={episodes} renderItem={renderItem} />
            )}
          </Col>
        </Row>
      )}
    </PageShell>
  )
}
