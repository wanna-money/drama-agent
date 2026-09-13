import { useState } from 'react'
import { Banner, Button, Card, Col, List, Row, Select, Space, Tooltip, Typography } from '@douyinfe/semi-ui'
import { IconImage } from '@douyinfe/semi-icons'
import { CastPending } from '../services/api'

const { Text } = Typography

/** 每个待确认角色的决策:关联到已有角色(带 character_id)或新建。 */
export type CastDecision =
  | { action: 'link'; character_id: string }
  | { action: 'create' }

interface CastReviewPanelProps {
  pending: CastPending[]
  /** 已对齐的身份(角色名 → Character.id),后端下发。有 id 才能把生成的形象落到该角色。 */
  cast?: Record<string, string>
  loading?: boolean
  onConfirm: (cast: Record<string, CastDecision>) => void
  /** 打开"从剧本提炼 → 生成形象"流程;仅在该项身份已定(有 character_id)时给出。 */
  onGenerateLook?: (name: string, characterId: string) => void
}

/**
 * 确认剧本人物 → 作品角色的身份对应。
 *
 * 放在写剧本之前:确认后剧本正文直接用规范名,分镜/造型/音色/参考图全部自然对齐。
 * 候选角色由后端随 pending 一并下发(suggestions),前端不再自己拉一次角色列表(规范 4)。
 */
export default function CastReviewPanel({
  pending, cast, loading = false, onConfirm, onGenerateLook,
}: CastReviewPanelProps) {
  // 默认全部"新建":剧本里出场的角色不该被悄悄丢掉,宁可建一个可见可改的空壳
  const [choices, setChoices] = useState<Record<string, string>>({})

  const pick = (name: string, value: string) =>
    setChoices(prev => ({ ...prev, [name]: value }))

  /** 该项当前指向的 Character.id:用户选的关联 > 后端已匹配上的。
   *
   * 生成的形象要落成某个角色的造型(Look),Look 挂在 character_id 上 —— 拿不到 id 就
   * 只能生成一张无处安放的图。选"新建为新角色"时角色实体尚未创建,故此处为空。
   */
  const resolvedId = (name: string): string => choices[name] || (cast || {})[name] || ''

  const handleConfirm = () => {
    const decisions: Record<string, CastDecision> = {}
    for (const p of pending) {
      const chosen = choices[p.name]
      decisions[p.name] = chosen
        ? { action: 'link', character_id: chosen }
        : { action: 'create' }
    }
    onConfirm(decisions)
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
            renderItem={(p: CastPending) => {
              const cid = resolvedId(p.name)
              return (
                <List.Item
                  key={p.name}
                  main={
                    <Space vertical align="start">
                      <Text strong>{p.name}</Text>
                      {p.appearance && <Text type="tertiary">{p.appearance}</Text>}
                    </Space>
                  }
                  extra={
                    <Space>
                      <Select
                        value={choices[p.name] ?? ''}
                        onChange={v => pick(p.name, String(v ?? ''))}
                        optionList={[
                          { value: '', label: '新建为新角色' },
                          ...p.suggestions.map(s => ({ value: s.character_id, label: `关联到「${s.name}」` })),
                        ]}
                      />
                      {onGenerateLook && (
                        // 素材库里没有该角色参考图时,从剧本提炼 prompt 直接生成四视图。
                        // 身份未定(选"新建")时不可用:生成的形象要落成 Look,而 Look 挂在
                        // Character 上 —— 那时实体还没建出来,图无处安放。
                        <Tooltip content={cid
                          ? '从剧本提炼描述并生成角色形象'
                          : '先关联到已有角色，或确认后到「角色」页生成'}>
                          <Button
                            theme="borderless" icon={<IconImage />} disabled={!cid}
                            onClick={() => onGenerateLook(p.name, cid)}
                          >生成形象</Button>
                        </Tooltip>
                      )}
                    </Space>
                  }
                />
              )
            }}
          />
        </Col>
      </Row>
    </Card>
  )
}
