import { Image } from '@douyinfe/semi-ui'

interface PreviewImageProps {
  src: string
  alt?: string
  width?: number
  height?: number
  // 单图默认自带点击放大(preview=true)。作为「预览组」的一员时,传 preview={false} + onClick,
  // 由外层受控 ImagePreview(src 数组)统一放大 + 左右切换(见 AssetsPage/CharactersPage)。
  preview?: boolean
  onClick?: () => void
}

// 统一图片展示组件:Semi Image(点击放大预览),objectFit contain 保证按原图比例缩放、不拉伸失真。
// 唯一必要的样式让步(objectFit)收在此一处——Semi 默认 width+height 会拉伸。
export default function PreviewImage({ src, alt, width, height, preview = true, onClick }: PreviewImageProps) {
  return (
    <Image
      src={src}
      alt={alt}
      width={width}
      height={height}
      preview={preview}
      onClick={onClick}
      imgStyle={{ objectFit: 'contain' }}
    />
  )
}
