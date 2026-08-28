import { useCallback, useEffect, useRef, useState } from 'react'
import { Banner, Button, Card, Col, Row, Space, Spin, TextArea, Toast, Typography } from '@douyinfe/semi-ui'
import { adaptationApi, AdaptationDraftItem, AdaptationState } from '../services/api'

const { Text } = Typography
const POLL_MS = 3000

interface Props {
  projectId: string
  /** 建集成功后通知父页刷新剧集列表 */
  onCommitted: () => void
}

/** 同一时刻只允许一个动作在跑:转圈只落在被点的那个按钮上,其余置灰。 */
type PendingAction = 'start' | 'save' | 'commit' | 'reload'

/** 作品级「小说改编 → 分集预览(可编辑)→ 确认建集」面板。
 * 状态/守卫都由后端决定,前端只按 adaptation_status 渲染对应形态。 */
export default function AdaptationPanel({ projectId, onCommitted }: Props) {
  const [state, setState] = useState<AdaptationState | null>(null)
  const [draft, setDraft] = useState<AdaptationDraftItem[]>([])
  const [pending, setPending] = useState<PendingAction | null>(null)
  const [loadError, setLoadError] = useState(false)
  const dirty = useRef(false)          // 用户正在编辑时,轮询不许覆盖草稿

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
      if (!dirty.current) setDraft(s.adapted_draft || [])
    } catch {
      // 只记错误态,不清空已有数据:轮询中途的瞬时失败不该把已展示的草稿抹掉。
      setLoadError(true)
    }
  }, [projectId])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {                    // 改编中轮询到出草稿/失败为止
    if (state?.adaptation_status !== 'adapting') return
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
      Toast.info('已开始改编,完成后在此预览分集')
      dirty.current = false
      await refresh()
    } catch (e) { fail('改编启动失败')(e) } finally { setPending(null) }
  }

  const saveDraft = async () => {
    setPending('save')
    try {
      const s = await adaptationApi.saveDraft(projectId, draft)
      dirty.current = false
      setState(s); setDraft(s.adapted_draft || [])
      Toast.success('分集草稿已保存')
    } catch (e) { fail('保存失败')(e) } finally { setPending(null) }
  }

  const commit = async () => {
    setPending('commit')
    try {
      const r = await adaptationApi.commit(projectId)
      Toast.success(`已建 ${r.episodes.length} 集`)
      dirty.current = false
      await refresh()
      onCommitted()
    } catch (e) { fail('建集失败')(e) } finally { setPending(null) }
  }

  const reload = async () => {
    setPending('reload')
    try { await refresh() } finally { setPending(null) }
  }

  const patch = (i: number, key: 'title' | 'screenplay', v: string) => {
    dirty.current = true
    setDraft(d => d.map((x, j) => (j === i ? { ...x, [key]: v } : x)))
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

  return (
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
        {st === 'adapting' && (
          <Col span={24}>
            <Space align="center">
              <Spin />
              <Text type="tertiary">正在改编与切分,完成后自动展示分集…</Text>
            </Space>
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
        {st === 'draft_ready' && (
          <>
            <Col span={24}>
              <Banner type="info" fullMode={false} closeIcon={null}
                description={`AI 切出 ${draft.length} 集,可逐集修改标题与剧本,确认后一次建出全部集`} />
            </Col>
            {draft.map((item, i) => (
              <Col span={24} key={item.index}>
                <Card title={`第 ${item.index} 集`}>
                  <Row gutter={[0, 8]}>
                    <Col span={24}>
                      <TextArea value={item.title} rows={1}
                        onChange={v => patch(i, 'title', v)} />
                    </Col>
                    <Col span={24}>
                      <TextArea value={item.screenplay} rows={8}
                        onChange={v => patch(i, 'screenplay', v)} />
                    </Col>
                  </Row>
                </Card>
              </Col>
            ))}
            <Col span={24}>
              <Space wrap>
                <Button {...actionProps('save')} onClick={saveDraft}>保存分集草稿</Button>
                <Button type="primary" theme="solid" {...actionProps('commit')} onClick={commit}>
                  {`确认,建出 ${draft.length} 集`}
                </Button>
                <Button {...actionProps('start')} onClick={start}>重新改编</Button>
              </Space>
            </Col>
          </>
        )}
        {st === 'committed' && (
          <Col span={24}>
            <Text type="tertiary">已按分集草稿建出剧集,可在下方逐集开拍。</Text>
          </Col>
        )}
      </Row>
    </Card>
  )
}
