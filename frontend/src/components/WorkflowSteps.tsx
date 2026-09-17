import { Typography } from '@douyinfe/semi-ui'
import { IconTickCircle, IconAlertTriangle, IconClose } from '@douyinfe/semi-icons'

const { Text } = Typography

export type WorkflowStepStatus = 'process' | 'finish' | 'error' | 'warning' | undefined

export interface WorkflowStepItem {
  key: string
  label: string
  /** 已定价/未定价的费用文案,如 fmtCost(...) 的输出 */
  description?: string
  status: WorkflowStepStatus
  /** undefined = 该步不可点(尚未推进到) */
  onClick?: () => void
}

interface WorkflowStepsProps {
  items: WorkflowStepItem[]
}

const WARN_TYPE: Record<'warning' | 'error', 'warning' | 'danger'> = {
  warning: 'warning',
  error: 'danger',
}
const WARN_LABEL: Record<'warning' | 'error', string> = {
  warning: '待审核',
  error: '失败',
}

/** 单集制作流程的竖向时间轴。取代 Semi <Steps>,视觉贴合整体重构后的圆角/主色语言,
 *  但状态语义与可点性完全由调用方通过 status/onClick 决定 —— 本组件只管渲染。
 *  样式定义在 index.css 的 .workflow-steps 规则里(Semi 无等价自绘时间轴组件,
 *  按规范 8 例外走 class,不写内联 style)。 */
export default function WorkflowSteps({ items }: WorkflowStepsProps) {
  return (
    <div className="workflow-steps" role="list" data-testid="steps">
      {items.map((item, i) => {
        const isLast = i === items.length - 1
        const clickable = item.onClick != null
        const dotContent =
          item.status === 'finish' ? <IconTickCircle size="small" />
          : item.status === 'warning' ? <IconAlertTriangle size="small" />
          : item.status === 'error' ? <IconClose size="small" />
          : String(i + 1)

        return (
          <div
            key={item.key}
            className="workflow-step"
            role="listitem"
            data-testid="step"
            data-status={item.status ?? 'wait'}
            data-clickable={clickable}
            onClick={clickable ? item.onClick : undefined}
          >
            {!isLast && <span className="workflow-step-connector" aria-hidden />}
            <span className="workflow-step-dot">{dotContent}</span>
            <div>
              <span className="workflow-step-title" data-testid="step-title">
                <Text type={item.status === undefined ? 'tertiary' : undefined}>{item.label}</Text>
              </span>
              {item.description && (
                <div><Text type="tertiary" size="small">{item.description}</Text></div>
              )}
              {(item.status === 'warning' || item.status === 'error') && (
                <div>
                  <Text type={WARN_TYPE[item.status]} size="small">{WARN_LABEL[item.status]}</Text>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
