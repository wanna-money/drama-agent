import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Table, Button, Tag, Modal, Toast, Typography, Form } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { projectsApi, Project } from '../services/api'
import { GENRES } from '../constants/genres'

const { Text } = Typography

interface CreateValues { title?: string; genre: string }

const STATUS_COLOR: Record<string, TagColor> = {
  empty: 'grey', running: 'blue', paused: 'orange',
  completed: 'green', partial_failed: 'red',
}

const STATUS_LABEL: Record<string, string> = {
  empty: '空', running: '制作中', paused: '待审核',
  completed: '已完成', partial_failed: '部分失败',
}

export default function ProjectListPage() {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const formApiRef = useRef<FormApi<CreateValues> | null>(null)
  const navigate = useNavigate()

  const handleCreate = async (values: CreateValues) => {
    setCreating(true)
    try {
      const project = await projectsApi.create({ title: (values.title ?? '').trim(), genre: values.genre })
      Toast.success('项目已创建，去添加第一集')
      navigate(`/projects/${project.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setCreating(false)
    }
  }

  const loadProjects = () => {
    setLoading(true)
    setFetchError(false)
    projectsApi.list()
      .then(data => { setProjects(data); setFetchError(false) })
      .catch(() => setFetchError(true))
      .finally(() => setLoading(false))
  }
  useEffect(loadProjects, [])

  const columns = [
    {
      title: '作品名称',
      dataIndex: 'title',
      render: (v: string, r: Project) => (
        <Text link onClick={() => navigate(`/projects/${r.id}`)}>{v}</Text>
      ),
    },
    {
      title: '类型',
      dataIndex: 'genre',
      render: (v: string) => <Text type="tertiary">{v}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'status',
      render: (v: string) => <Tag color={STATUS_COLOR[v] || 'grey'}>{STATUS_LABEL[v] || v}</Tag>,
    },
    {
      title: '总花费',
      dataIndex: 'cost_total',
      render: (v: number | undefined, r: Project) => (
        <Text type="tertiary">{r.cost_unpriced ? '未定价' : `¥${(v ?? 0).toFixed(2)}`}</Text>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      render: (v: string) => <Text type="tertiary">{new Date(v).toLocaleString('zh-CN')}</Text>,
    },
    {
      title: '',
      render: (_: unknown, r: Project) => {
        const isActive = !['created', 'completed', 'failed', 'assembly_failed'].includes(r.status)
        return (
          <Button
            type="danger"
            theme="borderless"
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
    <PageShell
      title="作品列表"
      description="管理您的 AI 短剧制作项目"
      headerExtra={
        <Button colorful theme="solid" icon={<IconPlus />} type="primary" onClick={() => setCreateOpen(true)}>新建项目</Button>
      }
    >
      {loading ? (
        <PageLoading />
      ) : fetchError ? (
        <PageEmpty variant="error" title="加载失败" description="无法获取项目列表，请检查网络或后端服务">
          <Button onClick={loadProjects}>重试</Button>
        </PageEmpty>
      ) : projects.length === 0 ? (
        <PageEmpty title="还没有作品" description="点击「新建项目」开始您的第一部 AI 短剧创作" />
      ) : (
        <Table columns={columns} dataSource={projects} rowKey="id" pagination={{ pageSize: 10 }} />
      )}

      <Modal
        title="新建短剧项目"
        visible={createOpen}
        onOk={() => formApiRef.current?.submitForm()}
        onCancel={() => setCreateOpen(false)}
        okText="创建项目"
        cancelText="取消"
        confirmLoading={creating}
        maskClosable={false}
      >
        <Form<CreateValues>
          getFormApi={(api) => (formApiRef.current = api)}
          onSubmit={handleCreate}
          initValues={{ genre: 'drama' }}
          labelPosition="top"
        >
          <Form.Input
            field="title" label="剧名" placeholder="为你的短剧起一个名字"
            rules={[{ required: true, message: '请输入剧名' }]}
          />
          <Form.Select field="genre" label="故事类型">
            {GENRES.map(g => <Form.Select.Option key={g.value} value={g.value}>{g.label}</Form.Select.Option>)}
          </Form.Select>
        </Form>
      </Modal>
    </PageShell>
  )
}
