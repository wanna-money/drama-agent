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

  const handleSubmit = async (values: { title: string; genre: string }) => {
    setLoading(true)
    try {
      const data: CreateProjectData = { title: values.title.trim(), genre: values.genre }
      const project = await projectsApi.create(data)
      Toast.success('项目已创建，去添加第一集')
      navigate(`/projects/${project.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <PageShell
      title="新建短剧项目"
      description="先建项目，再逐集创作（一个项目可含多集）"
      breadcrumb={[{ label: '作品列表', href: '/' }, { label: '新建项目' }]}
    >
      <Card>
        <Form
          initValues={{ genre: 'drama' }}
          onSubmit={handleSubmit}
          onValueChange={(v) => setDirty(!!(v.title && v.title.trim()))}
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
          <Space>
            <Button colorful theme="solid" htmlType="submit" type="primary" loading={loading}>创建项目</Button>
            <Text type="tertiary">创建后进入项目，逐集添加故事内容</Text>
          </Space>
        </Form>
      </Card>
    </PageShell>
  )
}
