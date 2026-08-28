import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, List, Modal, Space, Tag, Toast, Typography } from '@douyinfe/semi-ui'
import { IconDelete } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import { scriptsApi, Script } from '../services/api'
import { GENRES } from '../constants/genres'

const { Text } = Typography

const GENRE_LABEL: Record<string, string> = Object.fromEntries(
  GENRES.map(g => [g.value, g.label])
)

export default function ScriptsPage() {
  const navigate = useNavigate()
  const [scripts, setScripts] = useState<Script[]>([])
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    scriptsApi.list()
      .then(setScripts)
      .catch(() => Toast.error('加载失败'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const onDelete = (s: Script) => {
    Modal.confirm({
      title: '删除剧本',
      content: `删除「${s.title}」？已用它创作的剧集不受影响。`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try { await scriptsApi.delete(s.id); Toast.success('已删除'); load() }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const renderItem = (s: Script) => (
    <List.Item
      key={s.id}
      main={
        <Space vertical align="start">
          <Space wrap>
            <Text strong>{s.title}</Text>
            <Tag color="blue" shape="circle">{GENRE_LABEL[s.genre] || s.genre}</Tag>
            {s.project_title && <Tag shape="circle">{s.project_title}</Tag>}
          </Space>
          <Text type="tertiary">{s.source_text || '—'}</Text>
        </Space>
      }
      extra={
        <Space>
          <Button onClick={() => navigate(`/scripts/${s.id}`)}>查看</Button>
          <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDelete(s)} />
        </Space>
      }
    />
  )

  return (
    <PageShell
      title="剧本库"
      description="全局可复用的剧本。剧集的剧本审核通过后可存入这里,创作新集时直接选用"
    >
      {loading ? (
        <PageLoading />
      ) : scripts.length === 0 ? (
        <PageEmpty
          title="还没有剧本"
          description="在剧集页完成剧本审核后,可将其存入剧本库,供其它集复用"
        />
      ) : (
        <Card>
          <List dataSource={scripts} renderItem={renderItem} />
        </Card>
      )}
    </PageShell>
  )
}
