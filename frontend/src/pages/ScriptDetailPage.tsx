import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Descriptions, Modal, Row, Select, Space, Tag, Toast, Typography,
} from '@douyinfe/semi-ui'
import { IconDelete } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import StoryTextPanel from '../components/StoryTextPanel'
import { scriptsApi, projectsApi, Project, Script } from '../services/api'
import { GENRES } from '../constants/genres'

const { Title, Text, Paragraph } = Typography

const GENRE_LABEL: Record<string, string> = Object.fromEntries(GENRES.map(g => [g.value, g.label]))

/** 方案详情:一段原文的一个改编方案,剧本正文在此编辑。
 *
 * 没有独立的列表页 —— 方案在它所属原文的详情页里列(故事详情的「改编方案」区块),
 * 故本页从那里、改编面板、剧集页的「源剧本」三处进入,面包屑一律回溯到原文。
 * 制作流程里的审核/AI 改写在剧集页(那条路有版本树)。此处改正文不影响在制作中的集 ——
 * 集建立时已把正文快照进自己的版本树。 */
export default function ScriptDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [script, setScript] = useState<Script | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [movingOpen, setMovingOpen] = useState(false)
  const [projects, setProjects] = useState<Project[]>([])
  // '' 表示散稿(解绑);与"未选择"区分靠 Modal 自己的确认动作
  const [nextProject, setNextProject] = useState<string>('')

  const refresh = useCallback(async () => {
    if (!id) return
    const s = await scriptsApi.get(id).catch(() => null)
    if (s) setScript(s)
  }, [id])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])
  useEffect(() => { projectsApi.list().then(setProjects).catch(() => {}) }, [])

  /** 改归属:移到别的作品,或解绑成散稿(下拉留空)。 */
  const move = async () => {
    if (!id || saving) return
    setSaving(true)
    try {
      // 空串是"解绑"的显式表达 —— 后端据此区分"不改归属"(不传)与"改成散稿"
      const s = await scriptsApi.update(id, { project_id: nextProject })
      setScript(s)
      setMovingOpen(false)
      Toast.success('归属已更新')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('更新失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSaving(false)
    }
  }

  /** 删除本条剧本。后端挡住"还有集在用"(409),把它的说明直接展示 ——
   *  用户据此知道要先删剧集,而不是以为删除坏了。 */
  const remove = () => {
    Modal.confirm({
      title: '删除剧本',
      content: `删除「${script?.title}」？已用它创作的剧集不受影响。`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        if (!id) return
        try {
          await scriptsApi.delete(id)
          Toast.success('已删除')
          navigate(script?.story_id ? `/stories/${script.story_id}` : '/stories')
        } catch (e: unknown) {
          const err = e as { response?: { data?: { detail?: string } }; message?: string }
          Toast.error(err?.response?.data?.detail || err?.message || '删除失败')
        }
      },
    })
  }

  if (loading) return <PageLoading />
  if (!script) return <PageEmpty variant="error" title="剧本未找到" />

  return (
    <PageShell
      breadcrumb={[
        { label: '故事库', href: '/stories' },
        // 方案总属于某段原文,故经它回溯 —— 剧本没有独立的列表页可回
        ...(script.story_id
          ? [{ label: script.story_title || '原文', href: `/stories/${script.story_id}` }]
          : []),
        { label: script.title },
      ]}
      title={
        <Space wrap align="center">
          <Title heading={3}>{script.title}</Title>
          <Tag color="blue">{GENRE_LABEL[script.genre] || script.genre}</Tag>
          <Tag>{script.project_title || '未归属'}</Tag>
          <Button size="small" onClick={() => {
            setNextProject(script.project_id || '')
            setMovingOpen(true)
          }}>改归属</Button>
          <Button size="small" type="danger" icon={<IconDelete />} onClick={remove}>删除</Button>
        </Space>
      }
    >
      <Modal title="修改归属" visible={movingOpen} onCancel={() => setMovingOpen(false)}
        onOk={move} okText="保存" cancelText="取消" confirmLoading={saving}>
        <Space vertical align="start">
          <Text type="tertiary">留空 = 散稿（不属于任何作品）。剧本是全局可复用的内容。</Text>
          <Select value={nextProject} onChange={v => setNextProject((v as string) ?? '')}
            placeholder="选择作品，或留空作为散稿">
            <Select.Option value="">（散稿）</Select.Option>
            {projects.map(p => (
              <Select.Option key={p.id} value={p.id}>{p.title}</Select.Option>
            ))}
          </Select>
        </Space>
      </Modal>
      <Row gutter={[0, 16]}>
        {/* 原文与剧本是两个实体:原文是这个方案改编自的素材(住在 Story 上,可能被
            多个方案共用),剧本是本方案的成稿。故此处的原文**只读** —— 改它要去故事页,
            在这里改会让同一段原文的别的方案跟着变,而用户以为只动了眼前这一个。 */}
        {script.source_text && (
          <Col span={24}>
            <StoryTextPanel
              title={script.story_title ? `改编自《${script.story_title}》` : '故事原文'}
              text={script.source_text}
              editable={false}
              lockedHint="原文由故事页维护（同一段原文可能被多个方案共用）"
            />
          </Col>
        )}
        {script.story_analysis && (
          <Col span={24}>
            <Card title="故事分析">
              <Row gutter={[0, 8]}>
                <Col span={24}>
                  <Descriptions
                    data={[
                      { key: '类型', value: script.story_analysis.genre || '-' },
                      { key: '基调', value: script.story_analysis.tone || '-' },
                      { key: '主题', value: script.story_analysis.themes?.join('、') || '-' },
                    ]}
                  />
                </Col>
                {script.story_analysis.plot_summary && (
                  <Col span={24}>
                    <Row gutter={[0, 8]}>
                      <Col span={24}><Text type="tertiary" strong>故事梗概</Text></Col>
                      <Col span={24}><Paragraph type="tertiary">{script.story_analysis.plot_summary}</Paragraph></Col>
                    </Row>
                  </Col>
                )}
              </Row>
            </Card>
          </Col>
        )}
        {/* 剧本正文也用同一个助手改(kind=screenplay) —— 与原文的差别只是文体规则。
            制作流程里在审的剧本走剧集页(那条路有版本树)。 */}
        <Col span={24}>
          <StoryTextPanel
            title="剧本"
            kind="screenplay"
            text={script.content || ''}
            onSave={async next => {
              const s = await scriptsApi.update(script.id, { content: next })
              setScript(s)
            }}
          />
        </Col>
      </Row>
    </PageShell>
  )
}
