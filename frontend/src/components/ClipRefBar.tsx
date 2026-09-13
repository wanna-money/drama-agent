import { Button, Select, Space, Tag, Typography } from '@douyinfe/semi-ui'
import { IconClose } from '@douyinfe/semi-icons'
import { ClipRefKind } from '../services/api'
import PreviewImage from './PreviewImage'

const { Text } = Typography

/** 参考图语义的展示名。取值枚举与后端 video_refs.RefKind 同源。 */
export const KIND_LABEL: Record<ClipRefKind, string> = {
  first_frame: '首帧',
  last_frame: '尾帧',
  subject: '主体参考',
}

/** AIChatInput 的 Reference。图片带 kind(用途可改);视频没有 kind ——
 *  它的用途由任务类型决定,不由每条引用自己声明(手册里 @video1/@video2
 *  只是编号,不带首帧/尾帧这类语义)。
 *  label 是编号后的展示文案(如「@图1」「@video1」),供 `screen.getByText` 之类
 *  的场景与 prompt 里的 @ 编号对上。 */
export interface ClipReference {
  type: 'image' | 'video'
  id: string
  label: string
  url: string
  kind?: ClipRefKind
  subjectName?: string | null
  promptSummary?: string
}

interface Props {
  reference: ClipReference
  onKindChange: (kind: ClipRefKind) => void
  onDelete: () => void
}

/**
 * AIChatInput 的 renderReference 实现。
 *
 * 编号(label)必须与提交时数组顺序一致 —— 手册的 prompt 写法是
 * "@video1 中加一些小动物",编号错位会让"改视频1"作用到另一支上;
 * 编号的分配住在 ClipCreateForm(它知道完整列表的顺序),这里只展示。
 */
export default function ClipRefBar({ reference, onKindChange, onDelete }: Props) {
  return (
    <Space align="center" wrap>
      {reference.type === 'image' ? (
        <PreviewImage src={reference.url} alt={reference.label} width={40} height={40} />
      ) : (
        <Tag>{reference.label}</Tag>
      )}
      <Text>{reference.label}</Text>
      {reference.type === 'image' && (
        <Select
          value={reference.kind} onChange={(v) => onKindChange(v as ClipRefKind)}
        >
          {(Object.keys(KIND_LABEL) as ClipRefKind[]).map(k => (
            <Select.Option key={k} value={k}>{KIND_LABEL[k]}</Select.Option>
          ))}
        </Select>
      )}
      {reference.type === 'video' && reference.promptSummary && (
        <Text type="tertiary">{reference.promptSummary}</Text>
      )}
      <Button
        size="small" type="danger" theme="borderless" icon={<IconClose />}
        onClick={onDelete}
      >移除</Button>
    </Space>
  )
}
