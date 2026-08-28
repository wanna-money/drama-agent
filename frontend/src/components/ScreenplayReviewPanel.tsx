import { useState } from 'react'
import {
  Banner, Button, Card, Chat, Col, MarkdownRender, Row, Select, Space, TextArea, Toast,
} from '@douyinfe/semi-ui'
import { IconArrowUp } from '@douyinfe/semi-icons'
import type { Message, RenderInputAreaProps } from '@douyinfe/semi-ui/lib/es/chat/interface'
import { workflowApi, scriptsApi, ScreenplayVersion } from '../services/api'

let messageSeq = 0
const nextMessageId = () => `m${++messageSeq}`
const ROLE_CONFIG = { user: { name: '我' }, assistant: { name: '编剧助手' } }

/** 用 Semi 原生 TextArea 替换 Chat 默认单行输入,与左侧剧本编辑区风格一致。 */
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

interface ScreenplayReviewPanelProps {
  episodeId: string
  screenplay: string
  versions?: ScreenplayVersion[]
  current?: number
  isReviewing: boolean
  reviewLoading: boolean
  /** 通过 → onApprove(true)。修改(退回重写)走 onReject 由父页弹意见框。 */
  onApprove: (approved: boolean) => void
  onReject: () => void
  /** AI 改写 / 手动编辑 / 版本回退落库后,请父页刷新 status。 */
  onApplied: () => void
}

/** 剧本审核面板(剧集页):版本树 + AI 对话式改写 + 手动编辑 + 通过/修改。
 * 审核动作打到剧集维度的 workflowApi(revise/edit/revert),approve/reject 交父页统一处理。 */
export default function ScreenplayReviewPanel({
  episodeId, screenplay, versions = [], current = 0, isReviewing, reviewLoading,
  onApprove, onReject, onApplied,
}: ScreenplayReviewPanelProps) {
  const [chatMessages, setChatMessages] = useState<Message[]>([])
  const [chatSending, setChatSending] = useState(false)
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState('')
  const [savingEdit, setSavingEdit] = useState(false)
  const [savingToLibrary, setSavingToLibrary] = useState(false)

  const viewVersionIdx = selectedVersion ?? current
  const viewingCurrent = viewVersionIdx === current
  const viewScreenplay = versions[viewVersionIdx]?.screenplay ?? screenplay

  const handleChatSend = async (content: string) => {
    if (chatSending) return
    const history = chatMessages.map(m => ({ role: String(m.role), content: String(m.content ?? '') }))
    const payload = [...history, { role: 'user', content }]
    const userMsg: Message = { id: nextMessageId(), role: 'user', content, status: 'complete' }
    const loadingMsg: Message = { id: nextMessageId(), role: 'assistant', content: '', status: 'loading' }
    setChatMessages(prev => [...prev, userMsg, loadingMsg])
    setChatSending(true)
    try {
      const res = await workflowApi.reviseEpisode(episodeId, payload)
      setChatMessages(prev => prev.map(m =>
        m.id === loadingMsg.id ? { ...m, content: res.reply, status: 'complete' } : m))
      if (res.action === 'apply') {
        setSelectedVersion(null)
        setEditing(false)
        onApplied()
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      const detail = err?.response?.data?.detail || err?.message || '未知错误'
      setChatMessages(prev => prev.map(m =>
        m.id === loadingMsg.id ? { ...m, content: `改写失败: ${detail}`, status: 'error' } : m))
    } finally {
      setChatSending(false)
    }
  }

  const handleSaveEdit = async () => {
    if (savingEdit) return
    setSavingEdit(true)
    try {
      await workflowApi.editEpisode(episodeId, editText)
      Toast.success('已保存修改')
      setEditing(false)
      onApplied()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSavingEdit(false)
    }
  }

  /** 存入剧本库(全局可复用素材)。审核中与审核后都可存 —— 后端只要求正文非空。 */
  const handleSaveToLibrary = async () => {
    if (savingToLibrary) return
    setSavingToLibrary(true)
    try {
      await scriptsApi.saveFromEpisode(episodeId)
      Toast.success('已存入剧本库')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('存入失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSavingToLibrary(false)
    }
  }

  const handleRevert = async (versionIndex: number) => {
    try {
      await workflowApi.revertEpisode(episodeId, versionIndex)
      Toast.success('已恢复到该版本')
      setSelectedVersion(null)
      onApplied()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('恢复失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    }
  }

  return (
    <Row gutter={16}>
      <Col xs={24} lg={isReviewing ? 14 : 24}>
        <Card
          title="剧本"
          headerExtraContent={
            <Space wrap>
              {/* 存入剧本库不受 isReviewing 门控 —— 剧本库页承诺的正是"审核通过后可存入",
                  而通过后本面板仍渲染、isReviewing 已为 false。编辑未保存时不给入口。 */}
              {!editing && (
                <Button loading={savingToLibrary} onClick={handleSaveToLibrary}>存入剧本库</Button>
              )}
              {isReviewing && versions.length > 0 && (
                <Select
                  value={viewVersionIdx}
                  disabled={editing}
                  onChange={v => {
                    const idx = Number(v)
                    setSelectedVersion(idx === current ? null : idx)
                  }}
                  optionList={versions.map((ver, i) => ({ value: i, label: `版本${i + 1}·${ver.label}` }))}
                />
              )}
              {isReviewing && (editing ? (
                <>
                  <Button onClick={() => setEditing(false)}>取消</Button>
                  <Button type="primary" loading={savingEdit} onClick={handleSaveEdit}>保存</Button>
                </>
              ) : !viewingCurrent ? (
                <Button onClick={() => handleRevert(viewVersionIdx)}>恢复到此版本</Button>
              ) : (
                <>
                  <Button onClick={() => { setEditText(viewScreenplay); setEditing(true) }}>编辑</Button>
                  <Button type="primary" loading={reviewLoading} onClick={() => onApprove(true)}>通过</Button>
                  <Button type="warning" loading={reviewLoading} onClick={onReject}>修改</Button>
                </>
              ))}
            </Space>
          }
        >
          <Row gutter={[0, 8]}>
            {isReviewing && (
              <Col span={24}>
                <Banner
                  type="info" fullMode={false} closeIcon={null}
                  description="等待您审核剧本，确认内容后点击「通过」，或提交修改意见"
                />
              </Col>
            )}
            <Col span={24}>
              {editing
                ? <TextArea value={editText} onChange={setEditText} rows={20} />
                : <MarkdownRender raw={viewScreenplay} />}
            </Col>
          </Row>
        </Card>
      </Col>
      {isReviewing && (
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
      )}
    </Row>
  )
}
