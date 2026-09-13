import { useState } from 'react'
import {
  AIChatDialogue, AIChatInput, Button, Card, Col, Row, Space, Tag, TextArea, Toast, Typography,
} from '@douyinfe/semi-ui'
import type { Message } from '@douyinfe/semi-ui/lib/es/aiChatDialogue'
import type { Attachment, MessageContent } from '@douyinfe/semi-ui/lib/es/aiChatInput'
import { IconEdit } from '@douyinfe/semi-icons'
import { storyTextApi, ParsedAttachment, TextKind } from '../services/api'

const { Text, Paragraph } = Typography

let messageSeq = 0
const nextMessageId = () => `sm${++messageSeq}`
const ROLE_CONFIG = {
  user: { name: '我' },
  assistant: { name: '编剧助手' },
}

/** 助手输入框上方的建议气泡。
 *
 * 它们只是**预置的第一句话**,不是独立功能 —— 点完仍在对话里,可继续说"再紧凑一点"。
 * 放进助手而不是卡片头:摆成按钮会让人以为"优化""扩写""聊天"是三件事,实际是一件。 */
const SUGGESTIONS: Record<TextKind, string[]> = {
  story: [
    '帮我优化这段文字，让它更适合改编成短剧：情绪落到动作上、删掉说教和总结，长度大致不变',
    '帮我把这段扩写成完整的故事，有开场、转折和结局；每一处新增都要能拍出来',
    '这段里哪些地方拍不出来？逐条指出来',
  ],
  screenplay: [
    '帮我把这段改成可拍的剧本：场景标题、动作、对白分明，删掉不可拍的心理描写',
    '按这段故事写出完整剧本',
    '对白太像书面语，帮我改口语一些，并删掉角色自报动机的句子',
  ],
}

interface StoryTextPanelProps {
  /** 文本内容。空串表示尚未填写 —— 此时仍可用,让 AI 从想法写起。 */
  text: string
  /** 文体:决定下发哪套创作规则与格式要求(后端 TextKind)。 */
  kind?: TextKind
  /** 能不能改。开拍/改编后冻结。 */
  editable?: boolean
  /** 落库。由调用方决定写哪张表(原文写 Story.content / 剧本正文写 Script.content)。
   *  editable=false 时可省 —— 只读展示没有可保存的东西。 */
  onSave?: (next: string) => Promise<void>
  title?: string
  /** 不可编辑时的说明(如「已开拍，如需调整请在剧本审核阶段改写」)。 */
  lockedHint?: string
}

/**
 * 文本卡片:查看 / 编辑 / 与编剧助手对话式改写。
 *
 * 编辑态是**左右分栏**:左编辑框、右助手。助手的 apply 结果直接填进左侧编辑框 ——
 * 编辑框本身就是预览,用户可在其上继续手改,不满意点「取消」。这比弹一个预览窗更直接:
 * 那样"采纳"之后想再动一个字还得重新进编辑。
 *
 * 用的是与剧集页剧本审核**同一个 agent**(后端 text_revise_service):意图不明确时它先问,
 * 明确后才整份改写。
 */
export default function StoryTextPanel({
  text, kind = 'story', editable = true, onSave, title = '故事原文', lockedHint,
}: StoryTextPanelProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [sending, setSending] = useState(false)
  // 已解析的附件在多轮对话里复用 —— 用户上传一份资料后每轮都该带着它,不必重传
  const [attachments, setAttachments] = useState<ParsedAttachment[]>([])

  const send = async (content: string) => {
    if (sending || !content.trim()) return
    const history = messages.map(m => ({
      role: String(m.role), content: String(m.content ?? ''),
    }))
    const userMsg: Message = {
      id: nextMessageId(), role: 'user', content, status: 'complete',
    }
    const loading: Message = {
      id: nextMessageId(), role: 'assistant', content: '', status: 'loading',
    }
    setMessages(prev => [...prev, userMsg, loading])
    setSending(true)
    try {
      const r = await storyTextApi.revise({
        kind, text: draft,
        messages: [...history, { role: 'user', content }],
        attachments,
      })
      setMessages(prev => prev.map(m =>
        m.id === loading.id ? { ...m, content: r.reply, status: 'complete' } : m))
      // apply 才有改写结果 → 直接填进左侧编辑框(它就是预览);ask 时助手还在问意图
      if (r.action === 'apply' && r.text) setDraft(r.text)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      const detail = err?.response?.data?.detail || err?.message || '未知错误'
      setMessages(prev => prev.map(m =>
        m.id === loading.id ? { ...m, content: `改写失败: ${detail}`, status: 'error' } : m))
    } finally { setSending(false) }
  }

  /** 附件即传即解析。失败在对话里说明原因(如"暂不支持视频"),不静默丢掉。 */
  const handleUpload = async (files: Attachment[]) => {
    const pending = files.map(f => f.fileInstance).filter((f): f is File => !!f)
    for (const f of pending) {
      if (attachments.some(a => a.filename === f.name)) continue
      try {
        const parsed = await storyTextApi.parseAttachment(f)
        setAttachments(prev => [...prev, parsed])
      } catch (e: unknown) {
        const err = e as { response?: { data?: { detail?: string } } }
        Toast.error(err?.response?.data?.detail || `无法读取「${f.name}」`)
      }
    }
  }

  const save = async () => {
    // 清空后不提交:空正文会让下游(分析/分镜)无从下手,而用户多半是误删而非有意清空。
    if (!draft.trim()) { Toast.error(`${title}不能为空`); return }
    setSaving(true)
    try {
      await onSave?.(draft)
      setEditing(false)
      Toast.success('已保存')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally { setSaving(false) }
  }

  const openEdit = () => {
    setDraft(text)
    setMessages([])
    setAttachments([])
    setEditing(true)
  }

  return (
    <Card
      title={title}
      headerExtraContent={
        !editable ? (lockedHint ? <Text type="tertiary">{lockedHint}</Text> : null)
          : editing ? (
            <Space>
              <Button onClick={() => setEditing(false)}>取消</Button>
              <Button type="primary" theme="solid" loading={saving} onClick={save}>保存</Button>
            </Space>
          ) : (
            <Button icon={<IconEdit />} onClick={openEdit}>编辑</Button>
          )
      }
    >
      {!editing ? (
        text ? <Paragraph>{text}</Paragraph> : <Text type="tertiary">（暂无内容）</Text>
      ) : (
        // 左编辑框 / 右助手。窄屏(xs)竖排 —— 分栏在手机上会把两边都挤到不可用。
        <Row gutter={[16, 16]}>
          <Col xs={24} lg={13}>
            <TextArea
              value={draft} onChange={setDraft} rows={20}
              placeholder="粘贴内容，或写几句点子后让右侧助手铺开"
            />
          </Col>
          <Col xs={24} lg={11}>
            <Row gutter={[0, 8]}>
              <Col span={24}>
                <AIChatDialogue
                  chats={messages}
                  roleConfig={ROLE_CONFIG}
                  mode="userBubble"
                  showReset={false}
                />
              </Col>
              {attachments.length > 0 && (
                <Col span={24}>
                  {/* 已读入的附件常驻显示:它们每轮都会带给助手,用户要能看出"它记着什么" */}
                  <Space wrap>
                    <Text type="tertiary">已读入</Text>
                    {attachments.map(a => (
                      <Tag key={a.filename} closable
                        onClose={() => setAttachments(
                          prev => prev.filter(x => x.filename !== a.filename))}>
                        {a.filename}
                      </Tag>
                    ))}
                  </Space>
                </Col>
              )}
              <Col span={24}>
                <AIChatInput
                  placeholder="说说想怎么改，或上传图片 / 文档让助手参考…"
                  generating={sending}
                  suggestions={SUGGESTIONS[kind].map(content => ({ content }))}
                  uploadProps={{ action: '', accept: 'image/*,.txt,.md,.json,.pdf,.docx' }}
                  onUploadChange={({ fileList }) => { void handleUpload(fileList) }}
                  onMessageSend={(c: MessageContent) => {
                    const t = (c.inputContents ?? [])
                      .map(i => String(i.text ?? '')).join('').trim()
                    void send(t)
                  }}
                  // 点建议 = 直接发出这一句。
                  // 不能靠 AIChatInput 的 onSuggestClick:那个 prop 只存在于类型声明里,
                  // 实现从不调用它(内部走 handleSuggestionSelect → editor.setContent(suggestion),
                  // 而 suggestion 是 {content} 对象、不是 tiptap 文档 → 控制台报
                  // "Invalid input for Fragment.fromJSON",于是点了没有任何反应)。
                  // 故自渲染选项、自己接管点击。
                  renderSuggestionItem={({ suggestion, className }) => {
                    const t = typeof suggestion === 'string'
                      ? suggestion
                      : Array.isArray(suggestion)
                        ? suggestion.join('')
                        : String(suggestion?.content ?? '')
                    return (
                      <div className={className} onClick={() => void send(t)}>{t}</div>
                    )
                  }}
                />
              </Col>
            </Row>
          </Col>
        </Row>
      )}
    </Card>
  )
}
