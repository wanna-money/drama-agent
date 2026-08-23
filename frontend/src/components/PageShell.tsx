import { ReactNode } from 'react'
import { Row, Col, Empty, Spin } from '@douyinfe/semi-ui'
import {
  IllustrationNoContent, IllustrationNoContentDark,
  IllustrationNoResult, IllustrationNoResultDark,
} from '@douyinfe/semi-illustrations'
import PageHeader, { BreadcrumbItem } from './PageHeader'

interface PageShellProps {
  title?: ReactNode          // 列表页页头:主标题(不传则不渲染页头,详情页自带标题行时用)
  description?: ReactNode     // 页头副标题
  headerExtra?: ReactNode     // 页头右上角操作区(如「新建」按钮)
  breadcrumb?: BreadcrumbItem[]  // 页头面包屑
  children?: ReactNode        // 页面主体
}

interface PageEmptyProps {
  variant?: 'empty' | 'error'  // empty=无内容(默认),error=加载失败
  title?: string
  description?: ReactNode
  children?: ReactNode        // 空态下的操作(如「立即创作」/「重试」按钮)
}

/**
 * 统一页面外壳:全宽垂直容器 + 统一页头(PageHeader:面包屑 + 标题行右上角操作)+ 统一间距。
 * 详情页不传 title,只借外层容器统一宽度/间距,自渲染标题行。
 * 全 Semi 原生、零内联 style(规范 8)。
 */
export default function PageShell({ title, description, headerExtra, breadcrumb, children }: PageShellProps) {
  return (
    <Row gutter={[0, 16]}>
      {(title != null || (breadcrumb && breadcrumb.length > 0)) && (
        <Col span={24}>
          <PageHeader breadcrumb={breadcrumb} title={title} description={description} extra={headerExtra} />
        </Col>
      )}
      <Col span={24}>{children}</Col>
    </Row>
  )
}

/** 统一空态:带插画、水平居中。列表页无数据(empty)或加载失败(error)时用。 */
export function PageEmpty({ variant = 'empty', title, description, children }: PageEmptyProps) {
  const image = variant === 'error' ? <IllustrationNoResult /> : <IllustrationNoContent />
  const darkImage = variant === 'error' ? <IllustrationNoResultDark /> : <IllustrationNoContentDark />
  return (
    <Row type="flex" justify="center">
      <Col>
        <Empty image={image} darkModeImage={darkImage} title={title} description={description}>
          {children}
        </Empty>
      </Col>
    </Row>
  )
}

/** 统一加载态:水平居中的 Spin。 */
export function PageLoading() {
  return (
    <Row type="flex" justify="center">
      <Col><Spin size="large" /></Col>
    </Row>
  )
}
