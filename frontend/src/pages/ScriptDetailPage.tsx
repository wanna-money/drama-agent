import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Banner, Button, Card, Chat, Col, Descriptions, Form, MarkdownRender, Modal, Row, Select, Space, Spin, Tag,
  TextArea, Toast, Typography,
} from '@douyinfe/semi-ui'
import { IconArrowUp } from '@douyinfe/semi-icons'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import type { Message, RenderInputAreaProps } from '@douyinfe/semi-ui/lib/es/chat/interface'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { scriptsApi, ScriptStatus } from '../services/api'
import { SCRIPT_ACTIVE_STATUSES, SCRIPT_STATUS_COLOR, SCRIPT_STATUS_LABEL } from '../constants/scriptStatus'

let messageSeq = 0
const nextMessageId = () => `m${++messageSeq}`

const ROLE_CONFIG = { user: { name: '我' }, assistant: { name: '编剧助手' } }

/** 用 Semi 原生 TextArea 替换 Chat 默认的单行胶囊输入框(与左侧剧本编辑区风格一致)。
 * RenderInputAreaProps 不带 canSend/disabled,故由调用方(ScriptDetailPage)把 chatSending 状态
 * 通过工厂函数闭包传入,而非依赖 Chat 自身早已被完全替换掉的内置发送按钮禁用逻辑。*/
function ChatTextAreaInput({ onSend, disabled }: RenderInputAreaProps & { disabled: boolean }) {
  const [value, setValue] = useState('')
  const send = () => {
    const text = value.trim()
    if (!text || disabled) return
    onSend?.(text, [])
    setValue('')
  }
  return (
    <Row gutter={[0, 8]}>
      <Col span={24}>
        <TextArea
          value={value}
          onChange={setValue}
          onEnterPress={e => { e.preventDefault(); send() }}
          placeholder="和编剧助手说说想怎么改…"
          rows={3}
          disabled={disabled}
        />
      </Col>
      <Col span={24}>
        <Button type="primary" theme="solid" icon={<IconArrowUp />} disabled={disabled} onClick={send}>发送</Button>
      </Col>
    </Row>
  )
}
const makeChatInputRenderer = (disabled: boolean) =>
  (props?: RenderInputAreaProps) => <ChatTextAreaInput {...props} disabled={disabled} />

const { Title, Text, Paragraph } = Typography

const POLL_INTERVAL_MS = 3000

interface EditFormValues {
  title?: string
  content?: string
}

export default function ScriptDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [status, setStatus] = useState<ScriptStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [reviewLoading, setReviewLoading] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [chatMessages, setChatMessages] = useState<Message[]>([])
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [chatSending, setChatSending] = useState(false)
  const formApiRef = useRef<FormApi<EditFormValues> | null>(null)

  const refresh = useCallback(async () => {
    if (!id) return
    const s = await scriptsApi.status(id).catch(() => null)
    if (s) setStatus(s)
  }, [id])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  // 非终态时轮询进度,直到 completed / failed 或卸载
  useEffect(() => {
    if (!status || !SCRIPT_ACTIVE_STATUSES.includes(status.status)) return
    const timer = setInterval(() => { refresh() }, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [status, refresh])

  const handleStart = async () => {
    if (!id || starting) return
    setStarting(true)
    try {
      await scriptsApi.start(id)
      Toast.info('已入队，开始生成正文')
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('启动失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally { setStarting(false) }
  }

  const handleRetry = async () => {
    if (!id || starting) return
    setStarting(true)
    try {
      await scriptsApi.retry(id)
      Toast.info('已重置，正在从头重新生成')
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('重试失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally { setStarting(false) }
  }

  const handleApprove = async () => {
    if (!id || reviewLoading) return
    setReviewLoading(true)
    try {
      await scriptsApi.resume(id, { approved: true })
      Toast.success('剧本已通过')
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('操作失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally { setReviewLoading(false) }
  }

  const handleSaveEdit = async () => {
    if (!id) return
    const values = (formApiRef.current?.getValues?.() || {}) as EditFormValues
    const title = values.title?.trim()
    if (!title) { Toast.error('请输入标题'); return }
    setSaving(true)
    try {
      await scriptsApi.update(id, { title, content: values.content ?? '' })
      Toast.success('已保存')
      setEditOpen(false)
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setSaving(false) }
  }

  const handleChatSend = async (content: string) => {
    if (!id || chatSending) return
    const history = chatMessages.map(m => ({ role: String(m.role), content: String(m.content ?? '') }))
    const payload = [...history, { role: 'user', content }]

    const userMsg: Message = { id: nextMessageId(), role: 'user', content, status: 'complete' }
    const loadingMsg: Message = { id: nextMessageId(), role: 'assistant', content: '', status: 'loading' }
    setChatMessages(prev => [...prev, userMsg, loadingMsg])
    setChatSending(true)
    try {
      const res = await scriptsApi.revise(id, payload)
      setChatMessages(prev => prev.map(m =>
        m.id === loadingMsg.id ? { ...m, content: res.reply, status: 'complete' } : m
      ))
      if (res.action === 'apply') {
        setSelectedVersion(null)
        setEditing(false)
        await refresh()
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      const detail = err?.response?.data?.detail || err?.message || '未知错误'
      setChatMessages(prev => prev.map(m =>
        m.id === loadingMsg.id ? { ...m, content: `改写失败: ${detail}`, status: 'error' } : m
      ))
    } finally {
      setChatSending(false)
    }
  }

  const handleStartEdit = (text: string) => {
    setEditText(text)
    setEditing(true)
  }

  const handleSaveScreenplayEdit = async () => {
    if (!id || savingEdit) return
    setSavingEdit(true)
    try {
      await scriptsApi.editScreenplay(id, editText)
      Toast.success('已保存修改')
      setEditing(false)
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSavingEdit(false)
    }
  }

  const handleRevert = async (versionIndex: number) => {
    if (!id) return
    try {
      await scriptsApi.revert(id, versionIndex)
      Toast.success('已恢复到该版本')
      setSelectedVersion(null)
      await refresh()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('恢复失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    }
  }

  if (loading) return <PageLoading />
  if (!status) return <PageEmpty variant="error" title="剧本未找到" />

  const isAtReview = status.paused_at === 'screenplay_review'
  const isDraft = status.status === 'created'
  const isFailed = status.status === 'failed'
  const isRunning = status.status === 'queued' || status.status === 'running'
  const isStuck = !!status.paused_at && !status.content
  const canEdit = status.status === 'completed'

  const versions = status.screenplay_versions || []
  const currentVersionIdx = status.screenplay_version_current ?? 0
  const viewVersionIdx = selectedVersion ?? currentVersionIdx
  const viewingCurrent = viewVersionIdx === currentVersionIdx
  const viewScreenplay = versions[viewVersionIdx]?.screenplay ?? status.content ?? ''

  return (
    <PageShell
      breadcrumb={[{ label: '剧本库', href: '/scripts' }, { label: status.title }]}
      title={
        <Space wrap align="center">
          <Title heading={3}>{status.title}</Title>
          <Tag color={SCRIPT_STATUS_COLOR[status.status] || 'grey'}>
            {SCRIPT_STATUS_LABEL[status.status] || status.status}
          </Tag>
        </Space>
      }
    >
      <Row gutter={[0, 16]}>
        {status.error_message && (
          <Col span={24}>
            <Banner type="danger" fullMode={false} closeIcon={null} description={status.error_message} />
          </Col>
        )}

        {isDraft && (
          <Col span={24}>
            <Card title="草稿">
              <Row gutter={[0, 8]}>
                <Col span={24}>
                  <Banner
                    type="info" fullMode={false} closeIcon={null}
                    description="草稿尚未生成正文，点击「生成正文」开始创作"
                  />
                </Col>
                <Col span={24}>
                  <Button type="primary" theme="solid" loading={starting} onClick={handleStart}>生成正文</Button>
                </Col>
              </Row>
            </Card>
          </Col>
        )}

        {isFailed && (
          <Col span={24}>
            <Card title="生成失败">
              <Row gutter={[0, 8]}>
                <Col span={24}>
                  <Banner
                    type="warning" fullMode={false} closeIcon={null}
                    description="上次生成正文失败，请检查所选模型的凭证与可用性后重试"
                  />
                </Col>
                <Col span={24}>
                  <Button type="primary" theme="solid" loading={starting} onClick={handleStart}>重新生成</Button>
                </Col>
              </Row>
            </Card>
          </Col>
        )}

        {isRunning && !status.content && (
          <Col span={24}>
            <Card title="生成中">
              <Space align="center">
                <Spin />
                <Text type="tertiary">正在生成剧本，请稍候…（本页自动刷新，完成后可在此审核）</Text>
              </Space>
            </Card>
          </Col>
        )}

        {isStuck && (
          <Col span={24}>
            <Card title="生成中断">
              <Row gutter={[0, 8]}>
                <Col span={24}>
                  <Banner
                    type="warning" fullMode={false} closeIcon={null}
                    description="生成未产出剧本内容(上次可能因模型 / 凭证问题失败)。点击「重试生成」清空并从头重跑。"
                  />
                </Col>
                <Col span={24}>
                  <Button type="primary" theme="solid" loading={starting} onClick={handleRetry}>重试生成</Button>
                </Col>
              </Row>
            </Card>
          </Col>
        )}

        {status.story_analysis && (
          <Col span={24}>
            <Card title="故事分析">
              <Row gutter={[0, 8]}>
                <Col span={24}>
                  <Descriptions
                    data={[
                      { key: '类型', value: status.story_analysis.genre || '-' },
                      { key: '基调', value: status.story_analysis.tone || '-' },
                      { key: '主题', value: status.story_analysis.themes?.join('、') || '-' },
                    ]}
                  />
                </Col>
                {status.story_analysis.plot_summary && (
                  <Col span={24}>
                    <Row gutter={[0, 8]}>
                      <Col span={24}>
                        <Text type="tertiary" strong>故事梗概</Text>
                      </Col>
                      <Col span={24}>
                        <Paragraph type="tertiary">{status.story_analysis.plot_summary}</Paragraph>
                      </Col>
                    </Row>
                  </Col>
                )}
              </Row>
            </Card>
          </Col>
        )}

        {status.content && !isAtReview && (
          <Col span={24}>
            <Card
              title="剧本"
              headerExtraContent={canEdit && (
                <Button size="small" onClick={() => setEditOpen(true)}>编辑</Button>
              )}
            >
              <MarkdownRender raw={status.content} />
            </Card>
          </Col>
        )}

        {status.content && isAtReview && (
          <Col span={24}>
            <Row gutter={16}>
              <Col xs={24} lg={14}>
                <Card
                  title="剧本"
                  headerExtraContent={
                    <Space>
                      {versions.length > 0 && (
                        <Select
                          value={viewVersionIdx}
                          disabled={editing}
                          onChange={v => {
                            const idx = Number(v)
                            setSelectedVersion(idx === currentVersionIdx ? null : idx)
                          }}
                          optionList={versions.map((ver, i) => ({
                            value: i, label: `版本${i + 1}·${ver.label}`,
                          }))}
                        />
                      )}
                      {editing ? (
                        <>
                          <Button size="small" onClick={() => setEditing(false)}>取消</Button>
                          <Button type="primary" size="small" loading={savingEdit} onClick={handleSaveScreenplayEdit}>保存</Button>
                        </>
                      ) : viewingCurrent ? (
                        <>
                          <Button size="small" onClick={() => handleStartEdit(viewScreenplay)}>编辑</Button>
                          <Button type="primary" size="small" loading={reviewLoading} onClick={handleApprove}>通过</Button>
                        </>
                      ) : (
                        <Button size="small" onClick={() => handleRevert(viewVersionIdx)}>恢复到此版本</Button>
                      )}
                    </Space>
                  }
                >
                  <Row gutter={[0, 8]}>
                    <Col span={24}>
                      <Banner
                        type="info" fullMode={false} closeIcon={null}
                        description="等待您审核剧本，右侧对话让 AI 改写，或点「编辑」直接改，满意后点「通过」"
                      />
                    </Col>
                    <Col span={24}>
                      {editing ? (
                        <TextArea value={editText} onChange={setEditText} rows={20} />
                      ) : (
                        <MarkdownRender raw={viewScreenplay} />
                      )}
                    </Col>
                  </Row>
                </Card>
              </Col>
              <Col xs={24} lg={10}>
                <Card title="AI 改写助手">
                  <Chat
                    chats={chatMessages}
                    onMessageSend={handleChatSend}
                    roleConfig={ROLE_CONFIG}
                    enableUpload={false}
                    renderInputArea={makeChatInputRenderer(chatSending)}
                  />
                </Card>
              </Col>
            </Row>
          </Col>
        )}

        <Col span={24}>
          <Modal
            title="编辑剧本"
            visible={editOpen}
            onCancel={() => setEditOpen(false)}
            onOk={handleSaveEdit}
            okText="保存" cancelText="取消" confirmLoading={saving}
          >
            <Form<EditFormValues>
              key={editOpen ? 'open' : 'closed'}
              getFormApi={api => (formApiRef.current = api)}
              initValues={{ title: status.title, content: status.content || '' }}
              labelPosition="top"
            >
              <Form.Input field="title" label="标题" rules={[{ required: true, message: '请输入标题' }]} />
              <Form.TextArea field="content" label="正文" rows={16} />
            </Form>
          </Modal>
        </Col>
      </Row>
    </PageShell>
  )
}
