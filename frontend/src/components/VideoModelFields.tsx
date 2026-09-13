import { Form } from '@douyinfe/semi-ui'
import { VideoModelOption } from '../services/api'

// 模型未声明能力时的兜底清单(自定义 provider 常见:用户只填了模型名)。
// 这只是让下拉不至于无选项可选;真实能力应在「模型管理」里补全声明。
export const DEFAULT_RESOLUTIONS = ['768P', '1080p']
export const DEFAULT_ASPECT_RATIOS = ['9:16', '16:9', '1:1']
// 模型未声明时长区间时的兜底(自定义 provider 常见:用户只填了模型名)。
// 这只是让输入框有个可用范围;真实能力应在「模型管理」按模型声明。
export const DEFAULT_MIN_DURATION = 4
export const DEFAULT_MAX_DURATION = 15

export interface PickedVideoModel {
  video_provider: string
  video_model: string
}

/**
 * 从表单值拆出后端要的两样:video_provider(**协议名**)+ video_model(模型 id)。
 *
 * 界面上是**一个**下拉(选"哪个视频模型"),两者都由后端下发的 provider_id / model_id
 * 给出 —— 不从 value 猜、不写死映射表。把 model id 或 "provider/model" 复合值填进
 * video_provider,开拍即报 "Unknown video provider",而上游网关的拒绝信息会指向权限。
 *
 * 这是**唯一权威**:两种创作模式共用它,不各写一份(规范 4)。
 */
export function splitVideoModel(
  values: { video_provider?: string }, models: VideoModelOption[]
): PickedVideoModel {
  const picked = models.find(m => m.value === values.video_provider)
  return {
    video_provider: picked?.provider_id || values.video_provider || '',
    video_model: picked?.model_id || '',
  }
}

/** 视频三项的初始值。默认只认后端下发的 default(唯一权威),前端不写死模型名。 */
export function videoInitValues(models: VideoModelOption[], defaultValue: string) {
  const m = models.find(x => x.value === defaultValue)
  return {
    video_provider: defaultValue || '',
    resolution: m?.default_resolution || '768P',
    aspect_ratio: m?.default_aspect_ratio || '9:16',
  }
}

/** 模型声明的选项(分辨率 / 画面比例);为空数组时用兜底。
 *
 * 必须判空数组而非只用 ?? —— 接口对未声明能力的模型回传的是 `[]`(非 nullish),
 * ?? 不会触发,下拉就渲染成「暂无数据」:值显示着 768P 却一个选项都没有,改不了。
 *
 * 两种创作模式共用它(规范 4):Form 版(VideoModelFields 组件内)与
 * 无 Form 版(ClipConfigureBar)算的是同一条规则。 */
export function modelOptions(
  model: VideoModelOption | undefined,
  key: 'resolutions' | 'aspect_ratios',
  fallback: string[],
): string[] {
  const list = model?.[key]
  return list && list.length > 0 ? list : fallback
}

/** 所选模型的时长闭区间(秒)。是区间而非档位 —— 平台按区间收
 *  (Seedance 2.5 是 4-30,2.0 与 MiniMax H3 是 4-15)。未声明时用兜底,
 *  否则区间会拿到 min=max=0。 */
export function durationRangeOf(model: VideoModelOption | undefined) {
  return {
    min: model?.min_duration || DEFAULT_MIN_DURATION,
    max: model?.max_duration || DEFAULT_MAX_DURATION,
  }
}

/** 把时长**夹**到新区间内,而不是重置成下限。
 *
 * 夹取而非重置:从 30 秒的模型切到 15 秒上限的模型,20 → 15 保住了用户
 * "想要长一点"的意图;重置成区间下限会丢掉这个意图。 */
export function clampDuration(current: number, range: { min: number; max: number }): number {
  return Math.min(range.max, Math.max(range.min, current))
}

const groupBy = (items: VideoModelOption[]) =>
  items.reduce<Record<string, VideoModelOption[]>>(
    (acc, m) => { ;(acc[m.provider] ??= []).push(m); return acc }, {})

/**
 * 视频模型 + 分辨率 + 画面比例三项。选项与默认值全部读后端下发的声明,
 * 前端不自带写死的列表(规范 4)。
 */
export default function VideoModelFields(
  { formApi, models, onModelChange }: {
    formApi: any
    models: VideoModelOption[]
    /** 换模型时上报新值。参考图上限/时长清单这类"随模型变"的东西住在调用方,
     *  而它们的读取点可能在 Form 的 render prop 之外(拿不到 formApi)。 */
    onModelChange?: (value: string) => void
  }
) {
  const currentModel = () => models.find(x => x.value === formApi?.getValue('video_provider'))
  const groups = groupBy(models)
  return (
    <>
      <Form.Select
        field="video_provider" label="视频模型"
        onChange={(val) => {
          const m = models.find(x => x.value === val)
          if (m?.default_resolution) formApi.setValue('resolution', m.default_resolution)
          if (m?.default_aspect_ratio) formApi.setValue('aspect_ratio', m.default_aspect_ratio)
          // 时长要跟着模型走:各模型的区间不同(Seedance 2.5 是 4-30,2.0 与
          // MiniMax H3 是 4-15)。不夹的话,从 2.5 的 20 秒切到 2.0 后表单仍留着 20,
          // 而 InputNumber 的 max 已降到 15 —— 界面看不出异常,请求发出去才被拒。
          const range = durationRangeOf(m)
          const cur = Number(formApi.getValue('duration'))
          if (!(cur >= range.min && cur <= range.max)) {
            formApi.setValue('duration', clampDuration(cur || range.min, range))
          }
          onModelChange?.(val as string)
        }}
      >
        {Object.entries(groups).map(([provider, opts]) => (
          <Form.Select.OptGroup key={provider} label={provider}>
            {opts.map(m => (
              <Form.Select.Option
                key={m.value} value={m.value}
                disabled={m.credential_configured === false}
              >
                {m.credential_configured === false ? `${m.label}(未配置凭证)` : m.label}
              </Form.Select.Option>
            ))}
          </Form.Select.OptGroup>
        ))}
      </Form.Select>
      <Form.Select field="resolution" label="分辨率">
        {modelOptions(currentModel(), 'resolutions', DEFAULT_RESOLUTIONS).map(r => (
          <Form.Select.Option key={r} value={r}>{r}</Form.Select.Option>
        ))}
      </Form.Select>
      <Form.Select field="aspect_ratio" label="画面比例">
        {modelOptions(currentModel(), 'aspect_ratios', DEFAULT_ASPECT_RATIOS).map(r => (
          <Form.Select.Option key={r} value={r}>{r}</Form.Select.Option>
        ))}
      </Form.Select>
    </>
  )
}

