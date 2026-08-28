import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Row, Space, Toast } from '@douyinfe/semi-ui'
import { artifactsApi, VideoArtifact, ActionOption } from '../services/api'
import ActionParamForm from './ActionParamForm'

/** 单镜头的产物版本树:选一版 → 列出该版可用动作 → 按 schema 渲染参数表单执行。 */
export default function ShotArtifactPanel(
  { episodeId, projectId, shotId }: { episodeId: string; projectId: string; shotId: string }
) {
  const [artifacts, setArtifacts] = useState<VideoArtifact[]>([])
  const [actions, setActions] = useState<ActionOption[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [activeAction, setActiveAction] = useState<ActionOption | null>(null)
  const [running, setRunning] = useState(false)

  const load = useCallback(() => {
    artifactsApi.listByShot(episodeId, shotId).then(setArtifacts).catch(() => setArtifacts([]))
  }, [episodeId, shotId])

  useEffect(() => { load() }, [load])

  const pick = (aid: string) => {
    setSelected(aid); setActiveAction(null)
    artifactsApi.listActions(episodeId, aid).then(setActions).catch(() => setActions([]))
  }

  const run = (values: Record<string, unknown>) => {
    if (!selected || !activeAction) return
    setRunning(true)
    artifactsApi.runAction(episodeId, selected, activeAction.id, values)
      .then(() => { Toast.success('已生成新版本'); setActiveAction(null); load() })
      .catch((e: { response?: { data?: { detail?: string } }; message?: string }) =>
        Toast.error('执行失败: ' + (e?.response?.data?.detail || e?.message || '')))
      .finally(() => setRunning(false))
  }

  if (artifacts.length === 0) return null
  return (
    <Card title="版本树">
      <Row gutter={[0, 8]}>
        <Col span={24}>
          <Space wrap>
            {artifacts.map(a => (
              <Button key={a.id} size="small" theme={selected === a.id ? 'solid' : 'light'} onClick={() => pick(a.id)}>
                {a.action} · {a.provider} · {a.resolution}
              </Button>
            ))}
          </Space>
        </Col>
        {selected && actions.length > 0 && (
          <Col span={24}>
            <Space wrap>
              {actions.map(act => (
                <Button key={act.id} size="small" type="tertiary" onClick={() => setActiveAction(act)}>{act.label}</Button>
              ))}
            </Space>
          </Col>
        )}
        {activeAction && (
          <Col span={24}>
            <ActionParamForm schema={activeAction.param_schema} onSubmit={run} submitting={running} projectId={projectId} />
          </Col>
        )}
      </Row>
    </Card>
  )
}
