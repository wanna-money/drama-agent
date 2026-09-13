import { useEffect, useState } from 'react'
import {
  Button, Col, Empty, Modal, Row, Space, Spin, Tabs, Toast, Typography, Upload,
} from '@douyinfe/semi-ui'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconUpload } from '@douyinfe/semi-icons'
import { filesApi, assetsApi, Asset } from '../services/api'
import PreviewImage from './PreviewImage'

const { Text } = Typography

interface ImagePickerProps {
  projectId: string
  visible: boolean
  onClose: () => void
  /** 三条来源都只回一个 url(形如 /api/projects/{id}/images/{type}/{name})。 */
  onPick: (url: string) => void
}

interface ProjectImage {
  filename: string
  url: string
  size_bytes: number
  type?: string
}

/**
 * 公共选图:上传 / 素材库 / 本项目已有,三条来源汇成同一个 url 形态。
 *
 * 从素材库选走 copyFromAsset(拷贝快照)而非直接引用其 url:引用会让使用方
 * 依赖素材库那张图 —— 之后它被改或删,重跑就复现不出原样。
 */
export default function ImagePicker({ projectId, visible, onClose, onPick }: ImagePickerProps) {
  const [assets, setAssets] = useState<Asset[]>([])
  const [images, setImages] = useState<ProjectImage[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!visible) return
    setLoading(true)
    Promise.all([
      assetsApi.list().catch(() => [] as Asset[]),
      filesApi.listImages(projectId),
    ]).then(([as, imgs]) => { setAssets(as); setImages(imgs) })
      .finally(() => setLoading(false))
  }, [visible, projectId])

  const handleUpload = async (file: File) => {
    setBusy(true)
    try {
      const r = await filesApi.uploadImage(projectId, file, 'reference')
      onPick(r.url)
    } catch {
      Toast.error('上传失败')
    } finally {
      setBusy(false)
    }
  }

  const handlePickAsset = async (asset: Asset) => {
    setBusy(true)
    try {
      const r = await filesApi.copyFromAsset(projectId, asset.id, 'reference')
      onPick(r.url)
    } catch {
      Toast.error('添加失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="选择图片" visible={visible} onCancel={onClose} footer={null}>
      <Tabs type="line">
        <Tabs.TabPane tab="上传" itemKey="upload">
          <Upload
            action="" accept="image/*" showUploadList={false}
            beforeUpload={({ file }: { file: FileItem }) => {
              if (file.fileInstance) handleUpload(file.fileInstance)
              return { autoRemove: false, status: 'validateFail', shouldUpload: false }
            }}
          >
            <Button icon={<IconUpload />} loading={busy}>选择本地图片</Button>
          </Upload>
        </Tabs.TabPane>
        <Tabs.TabPane tab="素材库" itemKey="library">
          {loading ? <Spin /> : assets.length === 0 ? (
            <Empty title="素材库还没有图片" />
          ) : (
            <Row gutter={[8, 8]}>
              {assets.map(a => (
                <Col span={8} key={a.id}>
                  <Space vertical align="start">
                    <PreviewImage src={a.url} alt={a.name} width={80} height={80} />
                    <Text>{a.name}</Text>
                    <Button size="small" loading={busy} onClick={() => handlePickAsset(a)}>
                      使用
                    </Button>
                  </Space>
                </Col>
              ))}
            </Row>
          )}
        </Tabs.TabPane>
        <Tabs.TabPane tab="本项目已有" itemKey="existing">
          {loading ? <Spin /> : images.length === 0 ? (
            <Empty title="本项目还没有图片" />
          ) : (
            <Row gutter={[8, 8]}>
              {images.map(img => (
                <Col span={8} key={img.url}>
                  {/* 已在本项目目录里,直接用它的 url —— 再拷一次只会多一份同样的文件。
                      preview={false} 必需:PreviewImage 默认 preview=true,
                      点击会打开放大预览而 onClick 不生效(选不中图)。 */}
                  <PreviewImage
                    src={img.url} alt={img.filename} width={80} height={80}
                    preview={false} onClick={() => onPick(img.url)}
                  />
                </Col>
              ))}
            </Row>
          )}
        </Tabs.TabPane>
      </Tabs>
    </Modal>
  )
}
