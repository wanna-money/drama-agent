import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card, Col, Descriptions, MarkdownRender, Row, Space, Tag, Typography } from '@douyinfe/semi-ui'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { scriptsApi, Script } from '../services/api'
import { GENRES } from '../constants/genres'

const { Title, Text, Paragraph } = Typography

const GENRE_LABEL: Record<string, string> = Object.fromEntries(GENRES.map(g => [g.value, g.label]))

/** 剧本详情:只读复用素材(剧本库瘦身后无生成/审核,审核流程在剧集页内)。 */
export default function ScriptDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [script, setScript] = useState<Script | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    if (!id) return
    const s = await scriptsApi.get(id).catch(() => null)
    if (s) setScript(s)
  }, [id])

  useEffect(() => {
    refresh().finally(() => setLoading(false))
  }, [refresh])

  if (loading) return <PageLoading />
  if (!script) return <PageEmpty variant="error" title="剧本未找到" />

  return (
    <PageShell
      breadcrumb={[{ label: '剧本库', href: '/scripts' }, { label: script.title }]}
      title={
        <Space wrap align="center">
          <Title heading={3}>{script.title}</Title>
          <Tag color="blue">{GENRE_LABEL[script.genre] || script.genre}</Tag>
          {script.project_title && <Tag>{script.project_title}</Tag>}
        </Space>
      }
    >
      <Row gutter={[0, 16]}>
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
        <Col span={24}>
          <Card title="剧本">
            {script.content ? <MarkdownRender raw={script.content} /> : <Text type="tertiary">（暂无正文）</Text>}
          </Card>
        </Col>
      </Row>
    </PageShell>
  )
}
