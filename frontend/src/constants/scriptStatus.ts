// 剧本生命周期状态文案与颜色(单一来源)。取值须与后端 LifecycleStatus 保持一致。
export const SCRIPT_STATUS_LABEL: Record<string, string> = {
  created: '草稿',
  queued: '生成中',
  running: '生成中',
  paused: '待审核',
  completed: '已完成',
  failed: '失败',
}

export const SCRIPT_STATUS_COLOR: Record<string, 'grey' | 'blue' | 'green' | 'red'> = {
  created: 'grey',
  queued: 'blue',
  running: 'blue',
  paused: 'blue',
  completed: 'green',
  failed: 'red',
}

// 非终态:详情页据此决定是否轮询
export const SCRIPT_ACTIVE_STATUSES = ['queued', 'running', 'paused']
