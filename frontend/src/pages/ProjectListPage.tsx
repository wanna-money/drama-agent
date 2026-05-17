import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Table, Button, Tag, Spin, Modal, Toast } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus } from '@douyinfe/semi-icons'
import { projectsApi, Project } from '../services/api'

const STATUS_COLOR: Record<string, TagColor> = {
  created: 'grey',
  starting: 'blue', analyzing: 'blue', story_analyzed: 'blue',
  screenplay_written: 'blue', screenplay_review: 'orange', screenplay_approved: 'blue',
  screenplay_revision_requested: 'orange',
  storyboard_ready: 'blue',
  prompts_ready: 'blue', prompts_review: 'orange', prompts_approved: 'blue',
  prompts_revision_requested: 'orange',
  videos_generated: 'purple', assembly_failed: 'red',
  completed: 'green', failed: 'red',
}

const STATUS_LABEL: Record<string, string> = {
  created: '已创建',
  starting: '启动中', analyzing: '分析中', story_analyzed: '分析完成',
  screenplay_written: '剧本生成中', screenplay_review: '待审核剧本', screenplay_approved: '剧本已通过',
  screenplay_revision_requested: '剧本修改中',
  storyboard_ready: '分镜完成',
  prompts_ready: 'Prompt生成中', prompts_review: '待审核Prompt', prompts_approved: 'Prompt已确认',
  prompts_revision_requested: 'Prompt修改中',
  videos_generated: '视频生成完成', assembly_failed: '合成失败',
  completed: '已完成', failed: '失败',
}

const VIDEO_PROVIDER_LABEL: Record<string, string> = {
  seedance: 'Seedance 2.0',
  bailian: '万相 2.7',
}

export default function ProjectListPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    projectsApi.list()
      .then(data => { setProjects(data); setFetchError(false) })
      .catch(() => setFetchError(true))
      .finally(() => setLoading(false))
  }, [])

  const columns = [
    {
      title: '作品名称',
      dataIndex: 'title',
      render: (v: string, r: Project) => (
        <button
          onClick={() => navigate(`/projects/${r.id}`)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer', padding: 0,
            fontSize: 13, fontWeight: 600, color: '#111827', fontFamily: 'inherit',
            transition: 'color 0.18s',
          }}
          onMouseEnter={e => (e.currentTarget as HTMLButtonElement).style.color = '#7C3AED'}
          onMouseLeave={e => (e.currentTarget as HTMLButtonElement).style.color = '#111827'}
        >
          {v}
        </button>
      ),
    },
    {
      title: '类型',
      dataIndex: 'genre',
      render: (v: string) => <span style={{ color: '#9CA3AF', fontSize: 12 }}>{v}</span>,
    },
    {
      title: '视频模型',
      dataIndex: 'video_provider',
      render: (v: string) => (
        <span style={{ color: '#9CA3AF', fontSize: 12 }}>
          {VIDEO_PROVIDER_LABEL[v] || v}
        </span>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'grey'}>{STATUS_LABEL[v] || v}</Tag>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (v: string) => <span style={{ color: '#9CA3AF', fontSize: 12 }}>{new Date(v).toLocaleString('zh-CN')}</span>,
    },
    {
      title: '',
      render: (_: unknown, r: Project) => {
        const isActive = !['created', 'completed', 'failed', 'assembly_failed'].includes(r.status)
        return (
          <Button
            type="danger"
            size="small"
            theme="borderless"
            style={{ opacity: 0.5, fontSize: 12 }}
            onClick={() => {
              Modal.confirm({
                title: '确认删除',
                content: isActive
                  ? `「${r.title}」正在制作中，删除后将中断流程且无法恢复，确定继续？`
                  : `删除「${r.title}」后无法恢复，确定继续？`,
                okType: 'danger',
                okText: '删除',
                cancelText: '取消',
                onOk: async () => {
                  try {
                    await projectsApi.delete(r.id)
                    setProjects(ps => ps.filter(p => p.id !== r.id))
                    Toast.success('已删除')
                  } catch {
                    Toast.error('删除失败，请重试')
                  }
                },
              })
            }}
          >
            删除
          </Button>
        )
      },
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginBottom: 28 }}>
        <div className="page-title-section" style={{ marginBottom: 0 }}>
          <div className="page-title-eyebrow">My Projects</div>
          <h1 className="page-title-main">作品列表</h1>
          <p className="page-title-sub">管理您的 AI 短剧制作项目</p>
        </div>
        <Button icon={<IconPlus />} type="primary" size="large" onClick={() => navigate('/new')} style={{ minWidth: 120 }}>
          新建项目
        </Button>
      </div>

      <hr className="grad-divider" />

      <div className="glass-card">
        {loading ? (
          <div style={{ textAlign: 'center', padding: '60px 0' }}>
            <Spin size="large" />
            <div style={{ color: '#9CA3AF', marginTop: 14, fontSize: 12, letterSpacing: '0.5px' }}>载入中...</div>
          </div>
        ) : fetchError ? (
          <div style={{ textAlign: 'center', padding: '72px 24px' }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#EF4444', marginBottom: 8 }}>加载失败</div>
            <p style={{ color: '#9CA3AF', fontSize: 13, marginBottom: 24 }}>无法获取项目列表，请检查网络或后端服务</p>
            <Button onClick={() => { setLoading(true); setFetchError(false); projectsApi.list().then(setProjects).catch(() => setFetchError(true)).finally(() => setLoading(false)) }}>
              重试
            </Button>
          </div>
        ) : projects.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '72px 24px' }}>
            <div style={{ fontSize: 40, marginBottom: 16, opacity: 0.25 }}>🎬</div>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#374151', marginBottom: 8 }}>还没有作品</div>
            <p style={{ color: '#9CA3AF', fontSize: 13, marginBottom: 24 }}>
              点击「新建项目」开始您的第一部 AI 短剧创作
            </p>
            <Button type="primary" icon={<IconPlus />} onClick={() => navigate('/new')}>立即创作</Button>
          </div>
        ) : (
          <Table columns={columns} dataSource={projects} rowKey="id" pagination={{ pageSize: 10 }} style={{ background: 'transparent' }} />
        )}
      </div>
    </div>
  )
}
