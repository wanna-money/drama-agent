import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Button, Card, Form, List, Modal, Space, Tag, Toast, Typography, Upload,
} from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconPlus, IconDelete, IconUpload } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { scriptsApi, configApi, Script, LLMModelOption } from '../services/api'
import { GENRES } from '../constants/genres'
import { SCRIPT_STATUS_LABEL, SCRIPT_STATUS_COLOR } from '../constants/scriptStatus'

const { Text } = Typography

const GENRE_LABEL: Record<string, string> = Object.fromEntries(
  GENRES.map(g => [g.value, g.label])
)

interface ScriptFormValues {
  title?: string
  genre?: string
  source_text?: string
  llm_model?: string
}

export default function ScriptsPage() {
  const navigate = useNavigate()
  const [scripts, setScripts] = useState<Script[]>([])
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [llmModels, setLlmModels] = useState<LLMModelOption[]>([])
  const [llmDefault, setLlmDefault] = useState<string>('')
  const formApiRef = useRef<FormApi<ScriptFormValues> | null>(null)

  const load = () => {
    setLoading(true)
    scriptsApi.list()
      .then(setScripts)
      .catch(() => Toast.error('加载失败'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  useEffect(() => {
    configApi.listModels()
      .then(r => { setLlmModels(r.models); setLlmDefault(r.default || '') })
      .catch(() => { setLlmModels([]); setLlmDefault('') })
  }, [])

  const create = async () => {
    const values = (formApiRef.current?.getValues?.() || {}) as ScriptFormValues
    const title = values.title?.trim()
    const sourceText = values.source_text?.trim()
    if (!title) { Toast.error('请输入标题'); return }
    if (!sourceText) { Toast.error('请输入故事原文'); return }
    setSaving(true)
    try {
      const created = await scriptsApi.create({
        title,
        genre: values.genre || 'drama',
        source_text: sourceText,
        llm_model: values.llm_model,
      })
      Toast.success('已创建，正在生成正文')
      setModalOpen(false)
      load()
      navigate(`/scripts/${created.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setSaving(false) }
  }

  const onDelete = (s: Script) => {
    Modal.confirm({
      title: '删除剧本',
      content: `删除「${s.title}」？已用它创作的剧集不受影响。`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try { await scriptsApi.delete(s.id); Toast.success('已删除'); load() }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const renderItem = (s: Script) => (
    <List.Item
      key={s.id}
      main={
        <Space vertical align="start">
          <Space wrap>
            <Text strong>{s.title}</Text>
            <Tag color="blue" shape="circle">{GENRE_LABEL[s.genre] || s.genre}</Tag>
            <Tag color={SCRIPT_STATUS_COLOR[s.status] || 'grey'} shape="circle">
              {SCRIPT_STATUS_LABEL[s.status] || s.status}
            </Tag>
          </Space>
          <Text type="tertiary">{s.source_text || '—'}</Text>
        </Space>
      }
      extra={
        <Space>
          <Button onClick={() => navigate(`/scripts/${s.id}`)}>查看</Button>
          <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDelete(s)} />
        </Space>
      }
    />
  )

  return (
    <PageShell
      title="剧本库"
      description="全局可复用的剧本，创作视频时可直接选用"
      headerExtra={
        <Button
          colorful theme="solid" type="primary" icon={<IconPlus />}
          onClick={() => setModalOpen(true)}
        >新建剧本</Button>
      }
    >
      {loading ? (
        <PageLoading />
      ) : scripts.length === 0 ? (
        <PageEmpty title="还没有剧本" description="点击「新建剧本」输入故事，AI 将据此创作剧本正文" />
      ) : (
        <Card>
          <List dataSource={scripts} renderItem={renderItem} />
        </Card>
      )}

      <Modal
        title="新建剧本"
        visible={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={create}
        okText="创建" cancelText="取消" confirmLoading={saving}
      >
        <Form<ScriptFormValues>
          key={modalOpen ? 'open' : 'closed'}
          getFormApi={api => (formApiRef.current = api)}
          initValues={{ genre: 'drama', llm_model: llmDefault }}
          labelPosition="top"
        >
          <Form.Input
            field="title" label="标题" placeholder="如 夏日重逢"
            rules={[{ required: true, message: '请输入标题' }]}
          />
          <Form.Select field="genre" label="类型" placeholder="选择故事类型">
            {GENRES.map(g => (
              <Form.Select.Option key={g.value} value={g.value}>{g.label}</Form.Select.Option>
            ))}
          </Form.Select>
          <Form.Select field="llm_model" label="文本模型（LLM）" placeholder="选择生成剧本的模型">
            {llmModels.map(m => (
              <Form.Select.Option key={m.value} value={m.value}>{m.label}</Form.Select.Option>
            ))}
          </Form.Select>
          <Upload
            action=""
            accept=".txt,.md"
            showUploadList={false}
            beforeUpload={({ file }: { file: FileItem }) => {
              const f = file.fileInstance
              if (f) {
                if (f.size > 1024 * 1024) {
                  Toast.error('文件过大（>1MB），请精简后再传或直接粘贴')
                } else {
                  const reader = new FileReader()
                  reader.onload = () => {
                    formApiRef.current?.setValue('source_text', String(reader.result || ''))
                  }
                  reader.onerror = () => Toast.error('文件读取失败')
                  reader.readAsText(f)
                }
              }
              return { autoRemove: false, status: 'validateFail', shouldUpload: false }
            }}
          >
            <Button icon={<IconUpload />}>上传 .txt / .md 文件</Button>
          </Upload>
          <Form.TextArea
            field="source_text" label="故事原文" placeholder="粘贴或输入故事文本，也可上传 .txt / .md 文件；AI 将据此创作剧本"
            rules={[{ required: true, message: '请输入故事原文' }]}
          />
        </Form>
      </Modal>
    </PageShell>
  )
}
