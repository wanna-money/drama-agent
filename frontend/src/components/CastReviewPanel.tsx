import { useState } from 'react'
import { Banner, Button, Card, Col, List, Row, Select, Space, Typography } from '@douyinfe/semi-ui'
import { CastPending } from '../services/api'

const { Text } = Typography

/** 每个待确认角色的决策:关联到已有角色(带 character_id)或新建。 */
export type CastDecision =
  | { action: 'link'; character_id: string }
  | { action: 'create' }

interface CastReviewPanelProps {
  pending: CastPending[]
  loading?: boolean
  onConfirm: (cast: Record<string, CastDecision>) => void
}

/**
 * 确认剧本人物 → 作品角色的身份对应。
 *
 * 放在写剧本之前:确认后剧本正文直接用规范名,分镜/造型/音色/参考图全部自然对齐。
 * 候选角色由后端随 pending 一并下发(suggestions),前端不再自己拉一次角色列表(规范 4)。
 */
export default function CastReviewPanel({ pending, loading = false, onConfirm }: CastReviewPanelProps) {
  // 默认全部"新建":剧本里出场的角色不该被悄悄丢掉,宁可建一个可见可改的空壳
  const [choices, setChoices] = useState<Record<string, string>>({})

  const pick = (name: string, value: string) =>
    setChoices(prev => ({ ...prev, [name]: value }))

  const handleConfirm = () => {
    const cast: Record<string, CastDecision> = {}
    for (const p of pending) {
      const chosen = choices[p.name]
      cast[p.name] = chosen
        ? { action: 'link', character_id: chosen }
        : { action: 'create' }
    }
    onConfirm(cast)
  }

  return (
    <Card
      title="确认角色"
      headerExtraContent={
        <Button type="primary" theme="solid" loading={loading} onClick={handleConfirm}>
          确认，继续写剧本
        </Button>
      }
    >
      <Row gutter={[0, 12]}>
        <Col span={24}>
          <Banner
            type="info" fullMode={false} closeIcon={null}
            description="剧本里出现了作品角色库之外的人物。请指定它们各自的身份 —— 确认后剧本与后续分镜、造型都会使用这里的角色。"
          />
        </Col>
        <Col span={24}>
          <List
            dataSource={pending}
            renderItem={(p: CastPending) => (
              <List.Item
                key={p.name}
                main={
                  <Space vertical align="start">
                    <Text strong>{p.name}</Text>
                    {p.appearance && <Text type="tertiary">{p.appearance}</Text>}
                  </Space>
                }
                extra={
                  <Select
                    value={choices[p.name] ?? ''}
                    onChange={v => pick(p.name, String(v ?? ''))}
                    optionList={[
                      { value: '', label: '新建为新角色' },
                      ...p.suggestions.map(s => ({ value: s.character_id, label: `关联到「${s.name}」` })),
                    ]}
                  />
                }
              />
            )}
          />
        </Col>
      </Row>
    </Card>
  )
}
