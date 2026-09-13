import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Banner, Button, Card, Col, List, Row, Space, Spin, Tag, Toast, Typography } from '@douyinfe/semi-ui'
import { adaptationApi, projectsApi, AdaptationState, Script } from '../services/api'
import StoryTextPanel from './StoryTextPanel'
import CastReviewPanel, { CastDecision } from './CastReviewPanel'

const { Text } = Typography
const POLL_MS = 3000

interface Props {
  projectId: string
  /** 建集成功后通知父页刷新剧集列表 */
  onCommitted: () => void
  /** 待建集的剧本数下发给父页 —— 父页的空态要据此指向「建出 N 集」而非「新建一集」 */
  onPendingScripts?: (count: number) => void
}

/** 同一时刻只允许一个动作在跑:转圈只落在被点的那个按钮上,其余置灰。 */
type PendingAction = 'start' | 'confirmCast' | 'commit' | 'reload'

/** 作品级「小说改编 → 切成 N 个剧本 → 建集」面板。
 *
 * 切分产出「片段原文 + 它的方案」,故本面板只展示切出了哪些 + 建集入口;
 * 逐条修改去片段的故事页(内容的家在那,不在此再放一套编辑器)。
 * 状态/守卫都由后端决定,前端只按 adaptation_status 渲染对应形态。 */
export default function AdaptationPanel({ projectId, onCommitted, onPendingScripts }: Props) {
  const navigate = useNavigate()
  const [state, setState] = useState<AdaptationState | null>(null)
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [loadError, setLoadError] = useState(false)

  /** 被点的按钮转圈,其余置灰,避免并发重复提交。 */
  const actionProps = (a: PendingAction) => ({
    loading: pending === a,
    disabled: pending !== null && pending !== a,
  })

  const refresh = useCallback(async () => {
    try {
      const s = await adaptationApi.get(projectId)
      setState(s)
      setLoadError(false)
    } catch {
      // 只记错误态,不清空已有数据:轮询中途的瞬时失败不该把已展示的内容抹掉。
      setLoadError(true)
    }
  }, [projectId])

  useEffect(() => { refresh() }, [refresh])

  // 切出的剧本数上报父页:两处各自去拉一遍改编状态会分叉(规范 4)
  useEffect(() => {
    onPendingScripts?.(
      state?.adaptation_status === 'done' ? (state.scripts?.length ?? 0) : 0)
  }, [state?.adaptation_status, state?.scripts, onPendingScripts])

  useEffect(() => {                    // 改编中轮询到出草稿/失败为止
    const st = state?.adaptation_status
    if (st !== 'analyzing' && st !== 'adapting') return
    const t = setInterval(() => { refresh() }, POLL_MS)
    return () => clearInterval(t)
  }, [state?.adaptation_status, refresh])

  const fail = (prefix: string) => (e: unknown) => {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    Toast.error(`${prefix}: ` + (err?.response?.data?.detail || err?.message || '未知错误'))
  }

  const start = async () => {
    setPending('start')
    try {
      await adaptationApi.start(projectId)
      Toast.info('已开始改编,完成后在此展示切出的剧本')
      await refresh()
    } catch (e) { fail('改编启动失败')(e) } finally { setPending(null) }
  }

  const confirmCast = async (cast: Record<string, CastDecision>) => {
    setPending('confirmCast')
    try {
      await adaptationApi.confirmCast(projectId, cast)
      Toast.success('角色已确认,继续切分')
      await refresh()
    } catch (e) { fail('确认失败')(e) } finally { setPending(null) }
  }

  const commit = async () => {
    setPending('commit')
    try {
      const r = await adaptationApi.commit(projectId)
      Toast.success(`已建 ${r.episodes.length} 集`)
      await refresh()
      onCommitted()
    } catch (e) { fail('建集失败')(e) } finally { setPending(null) }
  }

  const reload = async () => {
    setPending('reload')
    try { await refresh() } finally { setPending(null) }
  }

  // 加载失败(还没拿到过数据)要与"非小说作品"区分开:前者给提示 + 重试入口,
  // 后者本就不该出现本面板。两者都白屏的话用户无从分辨。
  if (loadError && !state) {
    return (
      <Card title="小说改编 · 分集">
        <Row gutter={[0, 12]}>
          <Col span={24}>
            <Banner type="danger" fullMode={false} closeIcon={null}
              description="改编信息加载失败,请检查网络或稍后重试" />
          </Col>
          <Col span={24}>
            <Button type="primary" theme="solid" {...actionProps('reload')} onClick={reload}>
              重试
            </Button>
          </Col>
        </Row>
      </Card>
    )
  }
  if (!state || !state.source_text) return null    // 非小说作品不显示本面板
  const st = state.adaptation_status
  const scripts = state.scripts || []

  return (
    <Row gutter={[0, 16]}>
      {/* 小说正文是这部作品所有产出的源头,必须可见可改。
          只在改编开跑前可编辑(后端同样守着):切出的剧本从这段正文推导而来,
          开跑后改它会让剧本与源头不符,而剧本已是独立内容、不会随之更新。 */}
      <Col span={24}>
        <StoryTextPanel
          title="小说正文"
          text={state.source_text}
          editable={st === 'none'}
          lockedHint="已开始改编，如需修改请先重新改编"
          onSave={async next => {
            await projectsApi.update(projectId, { source_text: next })
            await refresh()
          }}
        />
      </Col>
      <Col span={24}>
    <Card title="小说改编 · 分集">
      <Row gutter={[0, 12]}>
        {st === 'none' && (
          <>
            <Col span={24}>
              <Banner type="info" fullMode={false} closeIcon={null}
                description="把小说改编成分集剧本,确认分集后一次建出多集" />
            </Col>
            <Col span={24}>
              <Button type="primary" theme="solid" {...actionProps('start')} onClick={start}>开始改编</Button>
            </Col>
          </>
        )}
        {(st === 'analyzing' || st === 'adapting') && (
          <Col span={24}>
            <Space align="center">
              <Spin />
              <Text type="tertiary">
                {st === 'analyzing' ? '正在识别小说里的角色…' : '角色已确定,正在切分分集…'}
              </Text>
            </Space>
          </Col>
        )}
        {/* 切分前的唯一卡点:角色身份要先定下来,各段才能用同一套名字
            (确认后由后端重新入队继续切分) */}
        {st === 'cast_review' && (
          <Col span={24}>
            <CastReviewPanel
              pending={state.cast_pending ?? []}
              loading={pending === 'confirmCast'}
              onConfirm={confirmCast}
            />
          </Col>
        )}
        {st === 'failed' && (
          <>
            <Col span={24}>
              <Banner type="warning" fullMode={false} closeIcon={null}
                description="改编失败,请检查所选模型的凭证与可用性后重试" />
            </Col>
            <Col span={24}>
              <Button type="primary" theme="solid" {...actionProps('start')} onClick={start}>重新改编</Button>
            </Col>
          </>
        )}
        {st === 'done' && (
          <>
            <Col span={24}>
              <Banner type="info" fullMode={false} closeIcon={null}
                description={`已切出 ${scripts.length} 段（还不是剧集）。点开任一段可修改原文与剧本，确认后点下方「建出 ${scripts.length} 集」`} />
            </Col>
            <Col span={24}>
              <List
                dataSource={scripts}
                emptyContent={<Text type="tertiary">还没有剧本</Text>}
                renderItem={(s: Script) => (
                  <List.Item
                    key={s.id}
                    main={
                      <Space vertical align="start">
                        {/* 切片标题是 LLM 起的「第 N 集 · xxx」,不标一下会被当成剧集 ——
                            此处列的是剧本,剧集要点下方「建出 N 集」才产生 */}
                        <Space align="center">
                          <Tag>剧本</Tag>
                          <Text strong>{s.title}</Text>
                        </Space>
                        <Text type="tertiary">{(s.content || '').slice(0, 80) || '（无正文）'}</Text>
                      </Space>
                    }
                    extra={
                      // 跳**片段原文**而非方案:切分产出的是「片段 + 它的方案」,
                      // 片段页能同时看到原文与它已有的方案,而方案页只有其中一个。
                      // 没有片段归属(未迁移的旧行)才退回方案页。
                      <Button onClick={() => navigate(
                        s.story_id ? `/stories/${s.story_id}` : `/scripts/${s.id}`)}>
                        查看 / 编辑
                      </Button>
                    }
                  />
                )}
              />
            </Col>
            <Col span={24}>
              <Space wrap>
                <Button type="primary" theme="solid" {...actionProps('commit')} onClick={commit}
                  disabled={scripts.length === 0 || (pending !== null && pending !== 'commit')}>
                  {`建出 ${scripts.length} 集`}
                </Button>
                <Button {...actionProps('start')} onClick={start}>重新改编</Button>
              </Space>
            </Col>
          </>
        )}
      </Row>
    </Card>
      </Col>
    </Row>
  )
}
