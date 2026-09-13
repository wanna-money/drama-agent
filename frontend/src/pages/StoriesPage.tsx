import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Form, List, Modal, Row, Space, Tag, Toast, Typography,
} from '@douyinfe/semi-ui'
import { IconDelete, IconPlus } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { storiesApi, projectsApi, Project, Story } from '../services/api'
import { GENRES } from '../constants/genres'

const { Text } = Typography

const GENRE_LABEL: Record<string, string> = Object.fromEntries(
  GENRES.map(g => [g.value, g.label])
)

/** 散稿分组键(project_id 为空的原文)。用常量而非空串,避免与真实 id 混淆。 */
const LOOSE = 'loose'

interface Group {
  key: string
  title: string
  items: Story[]
}

/** 按所属作品分组,保持后端下发的顺序。
 *
 * 散稿(不属于任何作品)排到最后:它们是零散素材,不该插在成组的作品之间。
 */
export function groupByProject(stories: Story[]): Group[] {
  const order: string[] = []
  const bucket = new Map<string, Story[]>()
  for (const s of stories) {
    const key = s.project_id || LOOSE
    if (!bucket.has(key)) { bucket.set(key, []); order.push(key) }
    bucket.get(key)!.push(s)
  }
  const keys = order.filter(k => k !== LOOSE).concat(order.includes(LOOSE) ? [LOOSE] : [])
  return keys.map(key => ({
    key,
    title: key === LOOSE ? '未归属作品' : (bucket.get(key)![0].project_title || '未命名作品'),
    items: bucket.get(key)!,
  }))
}

/** 一组的简述:列前几个故事名,超出用省略号收尾。
 *
 * 卡片上要能看出"这组里大概有什么",否则只剩标题 + 数量,还得点进去才知道是不是想找的那组。
 */
function summarize(items: Story[], max = 3): string {
  const names = items.slice(0, max).map(s => s.title)
  return items.length > max ? `${names.join('、')}…` : names.join('、')
}

/** 一条原文已有的产出:切了几段、改出几个方案。
 *
 * 这是 1:N 在列表上唯一看得见的地方 —— 没有它,用户分不出"还没动过的故事"与
 * "已经改编过好几版的故事",而这决定了他点进去要做什么。
 */
function derivedTags(s: Story) {
  return (
    <Space>
      {!!s.segment_count && <Tag color="violet" shape="circle">{`${s.segment_count} 段`}</Tag>}
      {!!s.script_count && <Tag color="green" shape="circle">{`${s.script_count} 个方案`}</Tag>}
    </Space>
  )
}

export default function StoriesPage() {
  const navigate = useNavigate()
  // 有 groupKey 时是组内详情,否则是分组卡片总览(同一页两态,不另开路由组件)
  const { groupKey } = useParams<{ groupKey?: string }>()
  const [stories, setStories] = useState<Story[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [saving, setSaving] = useState(false)
  // 归属下拉的选项:原文可以不属于任何作品(散稿),故这里只是可选项
  const [projects, setProjects] = useState<Project[]>([])
  const createFormApi = useRef<any>(null)

  /** 只列顶层原文 —— 切出来的片段属于其父原文的内部结构,平铺在总览里会把一本小说的
   *  N 段和别的故事混在一起,用户分不出哪些是一组。片段在故事详情页里看。 */
  const load = () => {
    setLoading(true)
    storiesApi.list({ topLevelOnly: true })
      .then(setStories)
      .catch(() => Toast.error('加载失败'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])
  useEffect(() => { projectsApi.list().then(setProjects).catch(() => {}) }, [])

  /** 新建故事。归属可留空 —— 原文是全局可复用的内容,不必先有作品。 */
  const onCreate = async (values: any) => {
    if (saving) return
    setSaving(true)
    try {
      const st = await storiesApi.create({
        project_id: values.project_id || null,
        title: values.title.trim(),
        content: (values.content || '').trim(),
      })
      Toast.success('已创建')
      setCreating(false)
      navigate(`/stories/${st.id}`)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  /** 删一条原文。后端挡住"还有方案挂在下面"(409),把它的说明直接展示 ——
   *  那些剧本的 story_id 指向它,删掉会让它们再也取不到原文。 */
  const onDelete = (s: Story) => {
    Modal.confirm({
      title: '删除故事',
      content: `删除「${s.title}」？它切出的片段会一并删除。`
        + (s.script_count ? `已有 ${s.script_count} 个改编方案在用它，需先删除那些剧本。` : ''),
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try { await storiesApi.delete(s.id); Toast.success('已删除'); load() }
        catch (e: unknown) {
          const err = e as { response?: { data?: { detail?: string } }; message?: string }
          Toast.error(err?.response?.data?.detail || err?.message || '删除失败')
        }
      },
    })
  }

  const renderItem = (s: Story) => (
    <List.Item
      key={s.id}
      main={
        <Space vertical align="start">
          <Space wrap>
            <Text strong>{s.title}</Text>
            <Tag color="blue" shape="circle">{GENRE_LABEL[s.genre] || s.genre}</Tag>
            {derivedTags(s)}
          </Space>
          <Text type="tertiary">{s.content || '—'}</Text>
        </Space>
      }
      extra={
        <Space>
          <Button onClick={() => navigate(`/stories/${s.id}`)}>查看</Button>
          <Button type="danger" theme="borderless" icon={<IconDelete />}
            onClick={() => onDelete(s)} />
        </Space>
      }
    />
  )

  if (loading) return <PageLoading />

  const groups = groupByProject(stories)

  // ── 组内详情:只列这一组的故事 ────────────────────────────────────────
  if (groupKey) {
    const group = groups.find(g => g.key === groupKey)
    if (!group) {
      return (
        <PageShell
          title="故事"
          breadcrumb={[{ label: '故事库', href: '/stories' }, { label: '未找到' }]}
        >
          <PageEmpty variant="error" title="该作品不存在"
            description="它可能已被删除，返回故事库重新选择">
            <Button onClick={() => navigate('/stories')}>返回故事库</Button>
          </PageEmpty>
        </PageShell>
      )
    }
    return (
      <PageShell
        title={group.title}
        description={group.key === LOOSE
          ? `${group.items.length} 个故事 · 不属于任何作品的散稿`
          : `作品「${group.title}」下的 ${group.items.length} 个故事 · 点开任一故事可修改原文`}
        breadcrumb={[{ label: '故事库', href: '/stories' }, { label: group.title }]}
      >
        <Card>
          <List dataSource={group.items} renderItem={renderItem} />
        </Card>
      </PageShell>
    )
  }

  // ── 总览:一组一张卡片(标题 + 简述),点进去看列表 ──────────────────────
  return (
    <PageShell
      title="故事库"
      description="全局可复用的故事原文，按所属作品归类。一段原文可以改编出多个剧本方案"
      headerExtra={
        <Button colorful theme="solid" type="primary" icon={<IconPlus />}
          onClick={() => setCreating(true)}>
          新建故事
        </Button>
      }
    >
      {/* 按钮走 Modal 自带 footer(与「新建短剧项目」一致):表单内再摆一排按钮会
          与弹窗的操作区重复,且位置、间距都得自己对齐。 */}
      <Modal
        title="新建故事"
        visible={creating}
        onOk={() => createFormApi.current?.submitForm()}
        onCancel={() => setCreating(false)}
        okText="创建"
        cancelText="取消"
        confirmLoading={saving}
        maskClosable={false}
      >
        <Form
          getFormApi={(api) => (createFormApi.current = api)}
          onSubmit={onCreate}
          labelPosition="top"
        >
          <Form.Input
            field="title" label="故事标题" placeholder="给这个故事起个名字"
            rules={[{ required: true, message: '请输入故事标题' }]}
          />
          <Form.Select field="project_id" label="所属作品（可留空）"
            placeholder="不选则为散稿，之后可再归属">
            {projects.map(p => (
              <Form.Select.Option key={p.id} value={p.id}>{p.title}</Form.Select.Option>
            ))}
          </Form.Select>
          {/* 这里填的是**故事原文**(用户写的素材),不是剧本 ——
              剧本是它的改编方案,由制作流程产出或另存而来。 */}
          <Form.TextArea
            field="content" label="故事原文" rows={8}
            placeholder="粘贴故事，或写几句点子（之后可在详情页用 AI 扩写铺开）"
          />
        </Form>
      </Modal>
      {stories.length === 0 ? (
        <PageEmpty
          title="还没有故事"
          description="点右上角「新建故事」，或在作品里粘一段小说开始改编"
        />
      ) : (
        // 用 Row/Col 响应式栅格铺卡片,不用 CardGroup type="grid":后者把卡片挤成
        // 紧贴的一整行、读起来像表格而非卡片(卡片之间需要留白才成立)。
        <Row gutter={[16, 16]}>
          {groups.map(g => (
            <Col xs={24} sm={12} lg={8} xxl={6} key={g.key}>
              {/* Semi 的 Card 没有 onClick,故点击目标是标题上的 Text link;
                  shadows="hover" 提供"这张卡可点"的视觉暗示。 */}
              <Card
                shadows="hover"
                title={
                  <Text link onClick={() => navigate(`/stories/group/${g.key}`)}>{g.title}</Text>
                }
                headerExtraContent={<Text type="tertiary">{`${g.items.length} 个故事`}</Text>}
              >
                <Text type="tertiary">{summarize(g.items)}</Text>
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </PageShell>
  )
}
