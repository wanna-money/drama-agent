import { useEffect, useRef, useState } from 'react'
import { Banner, Button, Card, Col, Divider, Empty, Input, List, Modal, Row, Space, Spin, Tag, Toast, Typography, Upload } from '@douyinfe/semi-ui'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconUpload, IconPlus, IconClose, IconHome, IconImage } from '@douyinfe/semi-icons'
import { filesApi, assetsApi, Asset, ReferenceEntry, ReferenceType } from '../services/api'
import PreviewImage from './PreviewImage'

const { Text } = Typography

/**
 * 一条参考图 = 后端下发的 ReferenceEntry + 纯前端的瞬时上传态。
 * key 是身份(后端保证唯一);ref_type 一律来自后端,前端不推断。
 */
export interface RefEntry extends ReferenceEntry {
  localPreview: string   // 上传中的本地预览(服务器确认前顶上)
  uploading: boolean
}

const toRefEntry = (r: ReferenceEntry, prev?: RefEntry): RefEntry => ({
  ...r,
  localPreview: prev?.localPreview ?? '',
  uploading: prev?.uploading ?? false,
})

/** 服务端清单覆盖本地,保住正在上传的瞬时态(刷新不该抹掉进行中的预览)。 */
export const mergeServerRefs = (server: ReferenceEntry[], local: RefEntry[]): RefEntry[] => {
  if (!Array.isArray(server)) return local   // 接口边界:形状不对时保留现状,不把面板刷崩
  const byKey = new Map(local.map(e => [e.key, e]))
  return server.map(r => toRefEntry(r, byKey.get(r.key)))
}

// 只有背景 —— 角色形象在「角色」页配置造型(Look),不在这里传第二份。
// 两个入口管同一件事正是"角色管理和参考图对不上"的成因。
const GROUPS: { refType: ReferenceType; label: string; icon: JSX.Element; addHint: string }[] = [
  { refType: 'background', label: '背景参考图', icon: <IconHome />, addHint: '输入场景地点' },
]

interface ReferencesPanelProps {
  projectId: string
  entries: RefEntry[]
  /** 整表提交给后端并用返回值刷新(所有增删改都走这里,保证类型与清单只有一个权威)。 */
  onPersist: (next: RefEntry[]) => Promise<void>
  /** 只改瞬时上传态,不落库。 */
  onPatch: (key: string, patch: Partial<RefEntry>) => void
}

export default function ReferencesPanel({ projectId, entries, onPersist, onPatch }: ReferencesPanelProps) {
  const [addingType, setAddingType] = useState<ReferenceType | null>(null)
  const [newKey, setNewKey] = useState('')
  const [pickingType, setPickingType] = useState<ReferenceType | null>(null)
  const [libAssets, setLibAssets] = useState<Asset[]>([])
  const [libLoading, setLibLoading] = useState(false)
  const [picking, setPicking] = useState(false)
  // 异步回调里要拿到最新清单,避免闭包读到过期值
  const entriesRef = useRef(entries)
  useEffect(() => { entriesRef.current = entries }, [entries])

  const replace = (key: string, patch: Partial<ReferenceEntry>) =>
    onPersist(entriesRef.current.map(e => e.key === key ? { ...e, ...patch } : e))

  const handleUpload = async (entry: RefEntry, file: File) => {
    const preview = URL.createObjectURL(file)
    onPatch(entry.key, { uploading: true, localPreview: preview })
    try {
      const result = await filesApi.uploadImage(projectId, file, entry.ref_type)
      await replace(entry.key, { image_url: result.url })
    } catch {
      Toast.error('上传失败')
    } finally {
      onPatch(entry.key, { uploading: false, localPreview: '' })
    }
  }

  const handleAddEntry = async () => {
    const key = newKey.trim()
    if (!key || !addingType) return
    if (entriesRef.current.some(e => e.key === key)) {
      Toast.warning('该名称已存在')
      return
    }
    setNewKey('')
    setAddingType(null)
    // 立即落库:清单的权威在后端,本地新增若不提交会被下一次刷新抹掉
    await onPersist([...entriesRef.current, {
      key, ref_type: addingType, image_url: '', localPreview: '', uploading: false,
    }])
  }

  const openLibrary = (refType: ReferenceType) => {
    setPickingType(refType)
    setLibLoading(true)
    assetsApi.list(refType)
      .then(setLibAssets)
      .catch(() => Toast.error('素材库加载失败'))
      .finally(() => setLibLoading(false))
  }

  // 从库选择:先拷贝一份进本项目(拿到与 upload 同形状的 url),再走同一条整表提交流程。
  const handlePickAsset = async (asset: Asset) => {
    if (!pickingType) return
    setPicking(true)
    try {
      const result = await filesApi.copyFromAsset(projectId, asset.id, pickingType)
      const existing = entriesRef.current.find(e => e.key === asset.name)
      const next: RefEntry[] = existing
        ? entriesRef.current.map(e => e.key === asset.name
          ? { ...e, ref_type: pickingType, image_url: result.url } : e)
        : [...entriesRef.current, {
          key: asset.name, ref_type: pickingType, image_url: result.url,
          localPreview: '', uploading: false,
        }]
      await onPersist(next)
      Toast.success('已从素材库添加')
      setPickingType(null)
    } catch {
      Toast.error('添加失败')
    } finally {
      setPicking(false)
    }
  }

  const renderEntry = (entry: RefEntry) => (
    <List.Item
      key={entry.key}
      main={
        <Space align="center">
          <Upload
            action=""
            accept="image/*"
            showUploadList={false}
            beforeUpload={({ file }: { file: FileItem }) => {
              if (file.fileInstance) handleUpload(entry, file.fileInstance)
              return { autoRemove: false, status: 'validateFail', shouldUpload: false }
            }}
          >
            {entry.uploading ? (
              <Spin size="small" />
            ) : entry.localPreview || entry.image_url ? (
              <PreviewImage src={entry.localPreview || entry.image_url} alt={entry.key} width={40} height={40} />
            ) : (
              <Button size="small" type="tertiary" icon={<IconUpload />} />
            )}
          </Upload>
          <Text>{entry.key}</Text>
          {entry.image_url
            ? <Tag color="green">已绑定</Tag>
            : <Tag color="grey">待上传</Tag>}
        </Space>
      }
      extra={
        <Space align="center">
          {entry.image_url && (
            <Button
              size="small" type="tertiary" theme="borderless"
              onClick={() => replace(entry.key, { image_url: '' })}
            >清除图片</Button>
          )}
          {/* 能不能删由后端下发的 removable 决定:探测出来的占位删了会被重新探测出来,
              所以不给入口(判断在后端,前端不自算) */}
          {entry.removable !== false && (
            <Button
              size="small" type="tertiary" theme="borderless" icon={<IconClose />}
              onClick={() => onPersist(entriesRef.current.filter(e => e.key !== entry.key))}
            />
          )}
        </Space>
      }
    />
  )

  const renderGroup = ({ refType, label, icon, addHint }: typeof GROUPS[number]) => {
    const group = entries.filter(e => e.ref_type === refType)
    return (
      <Row gutter={[0, 8]}>
        <Col span={24}>
          <Space align="center" wrap>
            {icon}
            <Text strong>{label}</Text>
            <Button
              size="small" type="tertiary" icon={<IconPlus />}
              onClick={() => { setAddingType(refType); setNewKey('') }}
            >添加</Button>
            <Button
              size="small" type="tertiary" icon={<IconImage />}
              onClick={() => openLibrary(refType)}
            >从库选择</Button>
          </Space>
        </Col>
        <Col span={24}>
          <List
            dataSource={group}
            renderItem={renderEntry}
            emptyContent={<Text type="tertiary">暂无{label}，点击「添加」新增</Text>}
          />
        </Col>
        {addingType === refType && (
          <Col span={24}>
            <Space align="center" wrap>
              <Input
                placeholder={addHint}
                value={newKey}
                onChange={setNewKey}
                onEnterPress={handleAddEntry}
                size="small"
                autoFocus
              />
              <Button size="small" type="primary" onClick={handleAddEntry} disabled={!newKey.trim()}>确认</Button>
              <Button size="small" type="tertiary" onClick={() => { setAddingType(null); setNewKey('') }}>取消</Button>
            </Space>
          </Col>
        )}
      </Row>
    )
  }

  return (
    <Row gutter={[0, 16]}>
      <Col span={24}>
        <Banner
          type="info" fullMode={false} closeIcon={null}
          description="角色形象请在「角色」页为角色配置造型，分镜会自动取用；这里只管背景。"
        />
      </Col>
      {GROUPS.map((g, i) => (
        <Col span={24} key={g.refType}>
          {i > 0 && <Divider />}
          {renderGroup(g)}
        </Col>
      ))}

      <Modal
        title={pickingType === 'character' ? '从素材库选择人物' : '从素材库选择背景'}
        visible={!!pickingType}
        onCancel={() => setPickingType(null)}
        footer={null}
        width={640}
      >
        {libLoading ? (
          <Spin />
        ) : (
          <List
            grid={{ gutter: 12, span: 6 }}
            dataSource={libAssets}
            emptyContent={<Empty description="素材库暂无该分类素材" />}
            renderItem={(a: Asset) => (
              <List.Item>
                <Card
                  shadows="hover"
                  cover={<PreviewImage src={a.url} alt={a.name} width={120} height={120} />}
                  footer={
                    <Button
                      size="small" type="primary" theme="borderless" loading={picking}
                      onClick={() => handlePickAsset(a)}
                    >选择</Button>
                  }
                >
                  <Card.Meta title={a.name} description={a.description || undefined} />
                </Card>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </Row>
  )
}
