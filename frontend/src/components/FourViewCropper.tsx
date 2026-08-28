import { useRef, useState } from 'react'
import {
  Banner, Button, Col, Cropper, Modal, Row, Space, Steps, Toast, Typography,
} from '@douyinfe/semi-ui'
import { CharacterViewName } from '../services/api'

const { Text } = Typography

const VIEWS: CharacterViewName[] = ['front', 'side', 'back', 'face']
const VIEW_LABEL: Record<CharacterViewName, string> = {
  front: '正面', side: '侧面', back: '背面', face: '面部特写',
}

/** dataURL → 纯 base64(后端 views-from-generated 收的是不带前缀的 base64)。 */
const stripDataUrl = (dataUrl: string) => dataUrl.replace(/^data:[^;]+;base64,/, '')

interface FourViewCropperProps {
  visible: boolean
  /** 待裁切的整张 sheet(dataURL 或 http URL 均可)。 */
  src: string
  saving?: boolean
  onCancel: () => void
  /** 四张都裁完后回调,值为不带 data URI 前缀的 base64。 */
  onDone: (views: Record<CharacterViewName, string>) => void
}

/**
 * 人工裁切四视图:一张 sheet 上依次框选正/侧/背/面部特写。
 *
 * 后端自动识别留白分界失败时走这里(见 services/character_gen_service.CropFailed)——
 * 自动裁切宁可报错也不返回猜出来的切法,人工裁切是那条路的出口。
 *
 * Semi 的 Cropper 根容器只有 position:relative、无默认尺寸,不给宽高则整个裁切区不可见,
 * 且组件未提供任何尺寸 prop。这是本仓库"全 Semi 原生、零内联 style"约定下确实无对应
 * 组件能力的场景,故此处保留唯一一处尺寸 style,并收敛在本组件内不外扩。
 */
export default function FourViewCropper({
  visible, src, saving = false, onCancel, onDone,
}: FourViewCropperProps) {
  const cropperRef = useRef<Cropper | null>(null)
  const [stepIndex, setStepIndex] = useState(0)
  const [cropped, setCropped] = useState<Partial<Record<CharacterViewName, string>>>({})

  const currentView = VIEWS[stepIndex]
  const isLast = stepIndex === VIEWS.length - 1

  const reset = () => { setStepIndex(0); setCropped({}) }

  const handleCancel = () => { reset(); onCancel() }

  const captureCurrent = (): string | null => {
    const canvas = cropperRef.current?.getCropperCanvas()
    if (!canvas) {
      Toast.error('裁切区尚未就绪，请稍候重试')
      return null
    }
    return stripDataUrl(canvas.toDataURL('image/png'))
  }

  const handleNext = () => {
    const b64 = captureCurrent()
    if (!b64) return
    const next = { ...cropped, [currentView]: b64 }
    setCropped(next)
    if (!isLast) {
      setStepIndex(i => i + 1)
      return
    }
    // 四张齐了才提交 —— front 是后端必填,缺任何一张都不该走保存
    const missing = VIEWS.filter(v => !next[v])
    if (missing.length) {
      Toast.error(`还差${missing.map(v => VIEW_LABEL[v]).join('、')}未裁切`)
      return
    }
    onDone(next as Record<CharacterViewName, string>)
    reset()
  }

  return (
    <Modal
      title="手动裁切四视图"
      visible={visible}
      onCancel={handleCancel}
      width={860}
      footer={
        <Space>
          {stepIndex > 0 && (
            <Button onClick={() => setStepIndex(i => i - 1)}>上一步</Button>
          )}
          <Button onClick={handleCancel}>取消</Button>
          <Button type="primary" theme="solid" loading={saving} onClick={handleNext}>
            {isLast ? '完成并保存' : `确认${VIEW_LABEL[currentView]}，下一张`}
          </Button>
        </Space>
      }
    >
      <Row gutter={[0, 12]}>
        <Col span={24}>
          <Banner
            type="info" fullMode={false} closeIcon={null}
            description={`拖动 / 缩放选框，框出「${VIEW_LABEL[currentView]}」后点击右下按钮`}
          />
        </Col>
        <Col span={24}>
          <Steps type="basic" current={stepIndex} size="small">
            {VIEWS.map(v => (
              <Steps.Step key={v} title={VIEW_LABEL[v]} status={cropped[v] ? 'finish' : undefined} />
            ))}
          </Steps>
        </Col>
        <Col span={24}>
          {/* 见组件顶部注释:Cropper 无尺寸 prop 且无默认高度,此处为必要的唯一例外 */}
          <div style={{ height: 420 }}>
            <Cropper ref={cropperRef} src={src} />
          </div>
        </Col>
        <Col span={24}>
          <Text type="tertiary">
            已裁切 {VIEWS.filter(v => cropped[v]).length} / {VIEWS.length}
          </Text>
        </Col>
      </Row>
    </Modal>
  )
}
