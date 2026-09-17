import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Row, Col, Button, Card, Tag, Modal, Toast, Typography, Form } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { IconPlus, IconDelete } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { projectsApi, Project } from '../services/api'
import { GENRES } from '../constants/genres'
import { VISUAL_STYLES } from '../constants/visual_styles'
import { genreCoverClass } from '../constants/genreGradients'

// 展示名由 GENRES 派生 —— 取值权威在后端 db.enums.Genre,前端只做中文展示。
// 各页都从这里派生,不各抄一份(抄了迟早分叉)。
const GENRE_LABEL: Record<string, string> = Object.fromEntries(
  GENRES.map(g => [g.value, g.label])
)

const { Text } = Typography

interface CreateValues { title?: string; genre: string; visual_style: string }

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
      const project = await projectsApi.create({
        title: (values.title ?? '').trim(), genre: values.genre, visual_style: values.visual_style,
      })
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

  const confirmDelete = (p: Project) => {
    const isActive = !['created', 'completed', 'failed', 'assembly_failed'].includes(p.status)
    Modal.confirm({
      title: '确认删除',
      content: isActive
        ? `「${p.title}」正在制作中，删除后将中断流程且无法恢复，确定继续？`
        : `删除「${p.title}」后无法恢复，确定继续？`,
      okType: 'danger',
      okText: '删除',
      cancelText: '取消',
      onOk: async () => {
        try {
          await projectsApi.delete(p.id)
          setProjects(ps => ps.filter(x => x.id !== p.id))
          Toast.success('已删除')
        } catch {
          Toast.error('删除失败，请重试')
        }
      },
    })
  }

  const renderCard = (p: Project) => (
    <Card
      key={p.id}
      className="project-card"
      cover={
        <div className={`project-cover ${genreCoverClass(p.genre)}`}>
          <span className="project-cover-label">{GENRE_LABEL[p.genre] || p.genre}</span>
        </div>
      }
      actions={[
        <Button
          key="delete" className="project-card-delete" type="danger" theme="borderless"
          icon={<IconDelete />} onClick={() => confirmDelete(p)}
        >删除</Button>,
      ]}
    >
      <Row gutter={[0, 8]}>
        <Col span={24}>
          <Text strong link onClick={() => navigate(`/projects/${p.id}`)}>{p.title}</Text>
        </Col>
        <Col span={24}>
          <Tag color={STATUS_COLOR[p.status] || 'grey'}>{STATUS_LABEL[p.status] || p.status}</Tag>
        </Col>
        <Col span={24}>
          <Row type="flex" justify="space-between">
            <Col>
              <Text type="tertiary" size="small">
                {p.cost_unpriced ? '未定价' : `¥${(p.cost_total ?? 0).toFixed(2)}`}
              </Text>
            </Col>
            <Col>
              <Text type="tertiary" size="small">{new Date(p.created_at).toLocaleDateString('zh-CN')}</Text>
            </Col>
          </Row>
        </Col>
      </Row>
    </Card>
  )

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
        <Row gutter={[16, 16]}>
          {projects.map(p => (
            <Col key={p.id} xs={24} sm={12} md={8} lg={6}>
              {renderCard(p)}
            </Col>
          ))}
        </Row>
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
          // visual_style 故意不给默认值(风格没有一个"大多数人都想要"的默认,强制用户
          // 显式选择);initValues 类型要求完整 Values,故用 Partial 断言仅带 genre。
          initValues={{ genre: 'drama' } as CreateValues}
          labelPosition="top"
        >
          <Form.Input
            field="title" label="剧名" placeholder="为你的短剧起一个名字"
            rules={[{ required: true, message: '请输入剧名' }]}
          />
          <Form.Select field="genre" label="故事类型">
            {GENRES.map(g => <Form.Select.Option key={g.value} value={g.value}>{g.label}</Form.Select.Option>)}
          </Form.Select>
          <Form.Select
            field="visual_style"
            label="视觉风格"
            placeholder="选择整体画风，后续每一集都会遵循这个风格"
            rules={[{ required: true, message: '请选择视觉风格' }]}
          >
            {VISUAL_STYLES.map(s => <Form.Select.Option key={s.value} value={s.value}>{s.label}</Form.Select.Option>)}
          </Form.Select>
        </Form>
      </Modal>
    </PageShell>
  )
}
