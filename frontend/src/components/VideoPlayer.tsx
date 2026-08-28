import { Button, Card, Col, Row } from '@douyinfe/semi-ui'
import { VideoPlayer as SemiVideoPlayer } from '@douyinfe/semi-ui'
import { IconDownload } from '@douyinfe/semi-icons'

/**
 * 统一视频展示:Semi 原生 VideoPlayer(自带播放/进度/音量/全屏/画中画),
 * 下载不在其控件栏内,单独给一个按钮。
 */
export default function VideoPlayer({ src, title }: { src: string; title?: string }) {
  return (
    <Card title={title}>
      <Row gutter={[0, 8]}>
        <Col span={24}>
          <SemiVideoPlayer
            src={src}
            height={320}
            theme="dark"
            autoPlay={false}
            muted={false}
            clickToPlay
            volume={0.6}
            defaultPlaybackRate={1}
            playbackRateList={[
              { label: '0.5x', value: 0.5 },
              { label: '1.0x', value: 1 },
              { label: '1.5x', value: 1.5 },
              { label: '2.0x', value: 2 },
            ]}
          />
        </Col>
        <Col span={24}>
          <Button
            theme="borderless" type="tertiary" icon={<IconDownload />}
            onClick={() => {
              const a = document.createElement('a')
              a.href = src
              a.download = title || 'video.mp4'
              a.click()
            }}
          >下载</Button>
        </Col>
      </Row>
    </Card>
  )
}
