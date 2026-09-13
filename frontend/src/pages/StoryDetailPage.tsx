import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Descriptions, List, Modal, Row, Select, Space, Tag, Toast, Typography,
} from '@douyinfe/semi-ui'
import { IconDelete } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import StoryTextPanel from '../components/StoryTextPanel'
import { storiesApi, scriptsApi, projectsApi, Project, Script, Story } from '../services/api'
import { GENRES } from '../constants/genres'

const { Text } = Typography

const GENRE_LABEL: Record<string, string> = Object.fromEntries(GENRES.map(g => [g.value, g.label]))

/** 故事详情:原文正文在此编辑,并列出由它派生的东西 —— 切出的片段与改编出的方案。
 *
 * 这是 1:N 唯一完整呈现的地方:同一段原文可以有多个方案(悬疑版/温情版),它们并列。
 * 改原文**不会**自动更新已有方案 —— 那些剧本是独立产出,要重新改编才会跟上,
 * 界面须说清这一点,否则用户以为改了原文剧本就同步了。 */
export default function StoryDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [story, setStory] = useState<Story | null>(null)
  const [scripts, setScripts] = useState<Script[]>([])
  const [segments, setSegments] = useState<Story[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [movingOpen, setMovingOpen] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  // '' 表示散稿(解绑);与"未选择"区分靠 Modal 自己的确认动作
  const [nextProject, setNextProject] = useState<string>('')

  const refresh = useCallback(async () => {
    if (!id) return
    const [st, scs, segs] = await Promise.all([
      storiesApi.get(id).catch(() => null),
      scriptsApi.list({ storyId: id }).catch(() => []),
      storiesApi.list({ parentId: id }).catch(() => []),
    ])
    if (st) setStory(st)
    setScripts(scs)
    setSegments(segs)
  }, [id])

  useEffect(() => { refresh().finally(() => setLoading(false)) }, [refresh])
  useEffect(() => { projectsApi.list().then(setProjects).catch(() => {}) }, [])

  /** 改归属:移到别的作品,或解绑成散稿(下拉留空)。 */
  const move = async () => {
    if (!id || saving) return
    setSaving(true)
    try {
      // 空串是"解绑"的显式表达 —— 后端据此区分"不改归属"(不传)与"改成散稿"
      setStory(await storiesApi.update(id, { project_id: nextProject }))
      setMovingOpen(false)
      Toast.success('归属已更新')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('更新失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  const onDelete = () => {
    if (!story) return
    Modal.confirm({
      title: '删除故事',
      content: `删除「${story.title}」？它切出的片段会一并删除，且不可恢复。`
        + (scripts.length ? `已有 ${scripts.length} 个改编方案在用它，需先删除那些剧本。` : ''),
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try {
          await storiesApi.delete(story.id)
          Toast.success('已删除')
          navigate('/stories')
        } catch (e: unknown) {
          const err = e as { response?: { data?: { detail?: string } }; message?: string }
          Toast.error(err?.response?.data?.detail || err?.message || '删除失败')
        }
      },
    })
  }

  if (loading) return <PageLoading />
  if (!story) {
    return (
      <PageShell title="故事" breadcrumb={[{ label: '故事库', href: '/stories' }]}>
        <PageEmpty variant="error" title="故事不存在" description="它可能已被删除">
          <Button onClick={() => navigate('/stories')}>返回故事库</Button>
        </PageEmpty>
      </PageShell>
    )
  }

  return (
    <PageShell
      title={story.title}
      description={story.project_title
        ? `属于作品「${story.project_title}」`
        : '散稿 · 不属于任何作品'}
      breadcrumb={[{ label: '故事库', href: '/stories' }, { label: story.title }]}
      headerExtra={
        <Space>
          <Tag color="blue" shape="circle">{GENRE_LABEL[story.genre] || story.genre}</Tag>
          <Button onClick={() => { setNextProject(story.project_id || ''); setMovingOpen(true) }}>
            改归属
          </Button>
          <Button type="danger" icon={<IconDelete />} onClick={onDelete}>删除</Button>
        </Space>
      }
    >
      <Modal
        title="改归属"
        visible={movingOpen}
        onOk={move}
        onCancel={() => setMovingOpen(false)}
        okText="保存"
        cancelText="取消"
        confirmLoading={saving}
      >
        <Space vertical align="start">
          <Text type="tertiary">留空即解绑成散稿；故事是全局可复用的内容。</Text>
          <Select value={nextProject} onChange={v => setNextProject(String(v ?? ''))}
            placeholder="选择作品，或留空作为散稿">
            <Select.Option value="">（散稿）</Select.Option>
            {projects.map(p => (
              <Select.Option key={p.id} value={p.id}>{p.title}</Select.Option>
            ))}
          </Select>
        </Space>
      </Modal>
      <Row gutter={[0, 16]}>
        <Col span={24}>
          <StoryTextPanel
            text={story.content || ''}
            onSave={async next => { setStory(await storiesApi.update(story.id, { content: next })) }}
          />
        </Col>
        {story.story_analysis && (
          <Col span={24}>
            <Card title="故事分析">
              <Descriptions
                data={[
                  { key: '类型', value: story.story_analysis.genre || '-' },
                  { key: '基调', value: story.story_analysis.tone || '-' },
                  { key: '主题', value: story.story_analysis.themes?.join('、') || '-' },
                ]}
              />
            </Card>
          </Col>
        )}
        {/* 片段(切分产出)。一本小说切出的 N 段是它的内部结构,故列在这里而非故事库总览。 */}
        {segments.length > 0 && (
          <Col span={24}>
            <Card title={`片段（${segments.length}）`}
              headerExtraContent={<Text type="tertiary">由改编切分产出，按剧情次序</Text>}>
              <List
                dataSource={segments}
                renderItem={seg => (
                  <List.Item
                    key={seg.id}
                    main={
                      <Space vertical align="start">
                        <Space wrap>
                          <Text strong>{seg.title}</Text>
                          {!!seg.script_count && (
                            <Tag color="green" shape="circle">{`${seg.script_count} 个方案`}</Tag>
                          )}
                        </Space>
                        <Text type="tertiary">{seg.content || '—'}</Text>
                      </Space>
                    }
                    extra={
                      <Button onClick={() => navigate(`/stories/${seg.id}`)}>查看</Button>
                    }
                  />
                )}
              />
            </Card>
          </Col>
        )}
        {/* 改编方案(1:N 的 N 侧)。并列存在 —— 同一段原文可以试多个方向。 */}
        <Col span={24}>
          <Card title={`改编方案（${scripts.length}）`}
            headerExtraContent={
              <Text type="tertiary">改原文不会自动更新已有方案，需重新改编</Text>
            }>
            {scripts.length === 0 ? (
              <Text type="tertiary">
                还没有方案。用这段原文开拍一集，剧本通过后可存回这里成为一个方案。
              </Text>
            ) : (
              <List
                dataSource={scripts}
                renderItem={sc => (
                  <List.Item
                    key={sc.id}
                    main={
                      <Space vertical align="start">
                        <Text strong>{sc.title}</Text>
                        <Text type="tertiary">{sc.content || '—'}</Text>
                      </Space>
                    }
                    extra={<Button onClick={() => navigate(`/scripts/${sc.id}`)}>查看</Button>}
                  />
                )}
              />
            )}
          </Card>
        </Col>
      </Row>
    </PageShell>
  )
}
