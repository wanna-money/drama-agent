import { useState } from 'react'
import { useNavigate, useBlocker } from 'react-router-dom'
import { Button, Toast, Form, Card, Typography, Space, Modal } from '@douyinfe/semi-ui'
import { projectsApi, CreateProjectData } from '../services/api'
import { GENRES } from '../constants/genres'
import PageShell from '../components/PageShell'

const { Text } = Typography

export default function NewProjectPage() {
  const [loading, setLoading] = useState(false)
  const [dirty, setDirty] = useState(false)
  const navigate = useNavigate()

  const blocker = useBlocker(dirty && !loading)
  if (blocker.state === 'blocked') {
    Modal.confirm({
      title: '离开页面', content: '您已输入内容，离开后将丢失，确定离开？',
      okText: '离开', cancelText: '继续编辑',
      onOk: () => blocker.proceed(), onCancel: () => blocker.reset(),
    })
  }

  const handleSubmit = async (values: {
    title: string
    genre: string
    source_text?: string
    target_episodes?: number
    target_seconds_per_episode?: number
  }) => {
    setLoading(true)
    try {
      // 仅在有值时带上小说字段:空串/0 会让后端「有正文时切分依据恰好二选一」误判。
      const sourceText = values.source_text?.trim()
      const data: CreateProjectData = {
        title: values.title.trim(),
        genre: values.genre,
        ...(sourceText ? { source_text: sourceText } : {}),
        ...(values.target_episodes ? { target_episodes: Number(values.target_episodes) } : {}),
        ...(values.target_seconds_per_episode
          ? { target_seconds_per_episode: Number(values.target_seconds_per_episode) } : {}),
      }
      const project = await projectsApi.create(data)
      Toast.success(sourceText ? '项目已创建，去改编分集' : '项目已创建，去添加第一集')
      navigate(`/projects/${project.id}`)
    } catch (e: unknown) {
      // 「切分依据恰好二选一」的唯一权威在后端,这里只把它的中文 detail 原样透出。
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageShell
      title="新建短剧项目"
      description="贴入小说可自动改编分集，留空则逐集创作（一个项目可含多集）"
      breadcrumb={[{ label: '作品列表', href: '/' }, { label: '新建项目' }]}
    >
      <Card>
        <Form
          initValues={{ genre: 'drama' }}
          onSubmit={handleSubmit}
          onValueChange={(v) => setDirty(!!(v.title?.trim() || v.source_text?.trim()))}
          labelPosition="top"
        >
          <Form.Input
            field="title"
            label="剧名"
            placeholder="为你的短剧起一个名字"
            rules={[{ required: true, message: '请输入剧名' }]}
          />
          <Form.Select field="genre" label="故事类型">
            {GENRES.map(g => <Form.Select.Option key={g.value} value={g.value}>{g.label}</Form.Select.Option>)}
          </Form.Select>
          <Form.TextArea
            field="source_text"
            label="小说正文（可选）"
            rows={8}
            placeholder="粘贴小说全文；留空则该作品按「短故事，每集单独输入」的方式创作"
          />
          <Form.InputNumber
            field="target_episodes"
            label="期望集数"
            placeholder="期望集数，例如 6"
          />
          <Form.InputNumber
            field="target_seconds_per_episode"
            label="每集时长（秒）"
            placeholder="与集数二选一，例如 90"
          />
          <Space>
            <Button colorful theme="solid" htmlType="submit" type="primary" loading={loading}>创建项目</Button>
            <Text type="tertiary">填了小说正文就去改编分集，否则逐集添加故事内容</Text>
          </Space>
        </Form>
      </Card>
    </PageShell>
  )
}
