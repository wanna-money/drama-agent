import { useState } from 'react'
import { AIChatInput, Input, Typography } from '@douyinfe/semi-ui'
import { ClipTaskType, VideoModelOption } from '../services/api'
import { DEFAULT_ASPECT_RATIOS, DEFAULT_RESOLUTIONS, durationRangeOf, modelOptions } from './VideoModelFields'

const { Text } = Typography

// Configure 是 AIChatInput 的**静态属性**,不是独立命名导出 ——
// import { Configure } from '@douyinfe/semi-ui' 会拿到 undefined。
const { Select: ConfigureSelect, Button: ConfigureButton } = AIChatInput.Configure

/** 模式的展示名。取值权威在后端 db.enums.ClipTaskType。 */
const TASK_TYPE_LABEL: Record<ClipTaskType, string> = {
  reference: '参考生成',
  edit: '视频编辑',
  extend: '视频延长',
}

interface Props {
  models: VideoModelOption[]
  /** 当前所选模型的 value(与 VideoModelOption.value 对应)。 */
  picked: string
  taskType: ClipTaskType
  /** 分辨率 / 画面比例 / 时长的**当前值**,由调用方持有(ClipCreateForm)——
   *  换模型时的重置/夹取逻辑要读"当前值",而 Configure 的值只活在 AIChatInput
   *  内部的 context 里,这里读不到,故由调用方另外管一份。 */
  resolution: string
  aspectRatio: string
  duration: number
  negativePrompt: string
  storageAvailable: boolean
  /** 是否已选了首帧/尾帧图 —— forces_adaptive_ratio 只在真有首尾帧时收紧比例
   *  (一刀切会让纯参考生成也丢掉竖屏能力)。 */
  hasFrameRef: boolean
  onModelChange: (value: string) => void
  onTaskTypeChange: (taskType: ClipTaskType) => void
  onResolutionChange: (v: string) => void
  onAspectRatioChange: (v: string) => void
  onDurationChange: (v: number) => void
  onNegativePromptChange: (v: string) => void
}

/**
 * 底部五项参数条:模式 / 视频模型 / 分辨率 / 画面比例 / 时长。
 *
 * 取值区间/选项全部读模型声明(复用 VideoModelFields 的纯函数,规范 4);
 * 模式的可选项随 max_reference_videos 变 —— 平台不支持参考视频的模型
 * 没有编辑/延长这两种任务,不是禁用了它们。
 *
 * 分辨率/比例/时长三项按 `picked` 加 key:model 声明的 Select 只在**挂载时**把
 * initValue 写进 context(getConfigureItem 的注册只在 mount 那次 effect 跑),
 * 换模型要让新默认值生效,就得让它们随 picked 变化重新挂载 —— 而"该填什么值"
 * (重置成默认 / 时长夹到新区间)是调用方在 onModelChange 里决定好、经 props 传入的。
 */
export default function ClipConfigureBar({
  models, picked, taskType, resolution, aspectRatio, duration,
  negativePrompt, storageAvailable, hasFrameRef,
  onModelChange, onTaskTypeChange, onResolutionChange, onAspectRatioChange,
  onDurationChange, onNegativePromptChange,
}: Props) {
  const [negativeOpen, setNegativeOpen] = useState(false)
  const model = models.find(m => m.value === picked)
  const supportsVideoRef = (model?.max_reference_videos ?? 0) > 0
  const { min, max } = durationRangeOf(model)
  const durationOptions = Array.from(
    { length: max - min + 1 }, (_, i) => min + i,
  ).map(s => ({ value: s, label: `${s} 秒` }))

  // 编辑/延长还依赖对象存储(平台的参考视频只接受公网 URL);存储不可用时
  // 这两项禁用而非移除 —— 移除会让用户以为模型本就不支持,补好存储后又要
  // 重新找一遍这两个选项在哪。
  const taskTypeOptions = [
    { value: 'reference', label: TASK_TYPE_LABEL.reference },
    ...(supportsVideoRef
      ? [
        { value: 'edit', label: TASK_TYPE_LABEL.edit, disabled: !storageAvailable },
        { value: 'extend', label: TASK_TYPE_LABEL.extend, disabled: !storageAvailable },
      ]
      : []),
  ]

  const ratioForcedByFrameRef = !!model?.forces_adaptive_ratio && hasFrameRef
  const ratioDisabled = taskType !== 'reference' || ratioForcedByFrameRef
  const ratioHint = taskType !== 'reference'
    ? '由原视频决定' : ratioForcedByFrameRef ? '由首帧图决定' : undefined
  const durationDisabled = taskType === 'edit'
  const durationHint = durationDisabled ? '与原视频一致' : undefined

  const videoModelOptions = models.map(m => ({
    value: m.value,
    label: m.credential_configured === false ? `${m.label}(未配置凭证)` : m.label,
    disabled: m.credential_configured === false,
  }))

  return (
    <>
      <ConfigureSelect
        field="task_type" data-testid="configure-task_type"
        initValue={taskType} optionList={taskTypeOptions}
        onChange={(v: string) => onTaskTypeChange(v as ClipTaskType)}
      />
      {!storageAvailable && (
        <Text type="tertiary">需先配置对象存储,才能使用视频编辑 / 延长</Text>
      )}
      <ConfigureSelect
        field="video_provider" data-testid="configure-video_provider"
        initValue={picked} optionList={videoModelOptions}
        onChange={(v: string) => onModelChange(v)}
      />
      <ConfigureSelect
        key={`resolution-${picked}`}
        field="resolution" data-testid="configure-resolution"
        initValue={resolution}
        optionList={modelOptions(model, 'resolutions', DEFAULT_RESOLUTIONS)
          .map(r => ({ value: r, label: r }))}
        onChange={onResolutionChange}
      />
      <ConfigureSelect
        key={`aspect_ratio-${picked}`}
        field="aspect_ratio" data-testid="configure-aspect_ratio"
        initValue={aspectRatio}
        optionList={modelOptions(model, 'aspect_ratios', DEFAULT_ASPECT_RATIOS)
          .map(r => ({ value: r, label: r }))}
        disabled={ratioDisabled}
        onChange={onAspectRatioChange}
      />
      {ratioHint && <Text type="tertiary">{ratioHint}</Text>}
      {/* 列全区间(min..max 每个整数),不裁剪成常用档位 —— 裁剪会把"平台收区间内
          任意整数"这个事实藏起来,用户想要 7 秒却发现只能选 5 或 8。 */}
      <ConfigureSelect
        key={`duration-${picked}`}
        field="duration" data-testid="configure-duration"
        initValue={duration} optionList={durationOptions}
        disabled={durationDisabled}
        onChange={(v: number) => onDurationChange(Number(v))}
      />
      {durationHint && <Text type="tertiary">{durationHint}</Text>}
      {/* 手册用词是"建议遵循""降低报错概率",是概率而非契约 —— 硬拦会挡掉
          "把 @video1 的天空换成夜空"这类没有字面关键词的合法表达,只提示不拦。 */}
      {taskType === 'edit' && (
        <Text type="tertiary">
          提示词需含「增加/删除/修改/替换」等意图,例:把 @video1 的天空换成夜空
        </Text>
      )}
      {taskType === 'extend' && (
        <Text type="tertiary">
          提示词需含「延长/延续/续写」等意图,例:向后延长 @video1,镜头缓慢拉远
        </Text>
      )}
      {/* 负向提示词是低频项,收进这个小开关弹出的输入,不占与 prompt 同等大小的位置。
          它不是 Configure 的一项值(不进 setup)—— 由父组件按普通受控输入管理。 */}
      <ConfigureButton field="__negative_open" onClick={() => setNegativeOpen(o => !o)}>
        负向提示词
      </ConfigureButton>
      {negativeOpen && (
        <Input
          value={negativePrompt} onChange={onNegativePromptChange}
          placeholder="不希望出现的元素"
        />
      )}
    </>
  )
}
