import { Button, Card, Col, Modal, Row, Space, Tag, Toast, Typography } from '@douyinfe/semi-ui'
import type { TagColor } from '@douyinfe/semi-ui/lib/es/tag'
import { clipsApi, Clip } from '../services/api'
import { PageEmpty } from './PageShell'
import VideoPlayer from './VideoPlayer'

const { Text, Paragraph } = Typography

const STATUS_COLOR: Record<string, TagColor> = {
  created: 'grey', queued: 'blue', running: 'blue',
  completed: 'green', failed: 'red',
}
const STATUS_LABEL: Record<string, string> = {
  created: '待处理', queued: '排队中', running: '生成中',
  completed: '已完成', failed: '失败',
}

/** 散片画廊。状态文案与色值按后端下发的 LifecycleStatus 映射,前端不自推状态。 */
export default function ClipGallery(
  { projectId, clips, onRefresh }: { projectId: string; clips: Clip[]; onRefresh: () => void }
) {
  if (clips.length === 0) {
    return <PageEmpty title="还没有散片" description="写一段提示词，提交后结果会出现在这里" />
  }
  const remove = (clip: Clip) => Modal.confirm({
    title: '删除该散片', content: '删除后无法恢复，确定继续?',
    okType: 'danger', okText: '删除', cancelText: '取消',
    onOk: async () => {
      try { await clipsApi.delete(projectId, clip.id); Toast.success('已删除'); onRefresh() }
      catch { Toast.error('删除失败') }
    },
  })
  return (
    <Row gutter={[16, 16]}>
      {clips.map(clip => (
        <Col span={24} key={clip.id}>
          <Card
            title={
              <Space>
                <Tag color={STATUS_COLOR[clip.status] || 'grey'}>
                  {STATUS_LABEL[clip.status] || clip.status}
                </Tag>
                <Text type="tertiary">{clip.duration} 秒 · {clip.resolution} · {clip.aspect_ratio}</Text>
              </Space>
            }
            headerExtraContent={
              <Button type="danger" theme="borderless" onClick={() => remove(clip)}>删除</Button>
            }
          >
            <Row gutter={[0, 8]}>
              <Col span={24}><Paragraph>{clip.prompt}</Paragraph></Col>
              {/* 失败必须显示原因:只显示"失败"用户无从判断该改什么 */}
              {clip.status === 'failed' && clip.error_message && (
                <Col span={24}><Text type="danger">{clip.error_message}</Text></Col>
              )}
              {clip.status === 'completed' && clip.video_url && (
                <Col span={24}>
                  <VideoPlayer src={`/api/projects/${projectId}/clips/${clip.id}/file`} />
                </Col>
              )}
            </Row>
          </Card>
        </Col>
      ))}
    </Row>
  )
}
