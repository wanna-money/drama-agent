import { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Row, Col, Space, Typography, Breadcrumb } from '@douyinfe/semi-ui'

const { Title, Text } = Typography

export interface BreadcrumbItem {
  label: string
  href?: string
}

interface PageHeaderProps {
  breadcrumb?: BreadcrumbItem[]
  title?: ReactNode
  description?: ReactNode
  extra?: ReactNode
}

/** 全站统一页面头:面包屑 + 标题行(左标题/副标题,右操作)。全 Semi 原生,零内联 style。 */
export default function PageHeader({ breadcrumb, title, description, extra }: PageHeaderProps) {
  const navigate = useNavigate()
  return (
    <Row gutter={[0, 8]}>
      {breadcrumb && breadcrumb.length > 0 && (
        <Col span={24}>
          <Breadcrumb>
            {breadcrumb.map((b, i) => (
              <Breadcrumb.Item
                key={i}
                onClick={b.href ? () => navigate(b.href as string) : undefined}
              >
                {b.label}
              </Breadcrumb.Item>
            ))}
          </Breadcrumb>
        </Col>
      )}
      <Col span={24}>
        <Row type="flex" justify="space-between" align="middle">
          <Col>
            <Space vertical align="start">
              {typeof title === 'string' ? <Title heading={3}>{title}</Title> : title}
              {description != null && <Text type="tertiary">{description}</Text>}
            </Space>
          </Col>
          {extra != null && <Col>{extra}</Col>}
        </Row>
      </Col>
    </Row>
  )
}
