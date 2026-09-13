import { useEffect, useRef, useState } from 'react'
import { Button, Form, Modal, Space, Toast, Typography } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form'
import { configApi, ImageModelOption, promptApi } from '../services/api'
import PreviewImage from './PreviewImage'

const { Text } = Typography

/** 一次生成请求。size 可能为空(模型未声明尺寸时后端按其默认处理)。 */
export interface GenerateRequest {
  prompt: string
  modelId: string
  size: string
}

interface GenerateFromScriptModalProps {
  visible: boolean
  /** 提炼对象:角色名 或 场景地点。同时作为弹窗标题。 */
  subjectKey: string
  subject: 'character' | 'background'
  /** 提炼原料的位置,二选一(后端据此自取剧本正文 / 分镜) */
  episodeId?: string
  projectId?: string
  /** 已有 prompt(如背景条目存下来的):有则填入让用户改,不重新提炼 */
  initialPrompt?: string
  /** 生成一张图,返回可预览的 base64。人物走四视图 sheet、背景走普通文生图 —— 差异在此注入。 */
  onGenerate: (req: GenerateRequest) => Promise<string>
  /** 把预览图落库(绑到角色造型 / 场景参考图)。抛错则留在预览态让用户重试。 */
  onSave: (req: GenerateRequest & { imageB64: string }) => Promise<void>
  onCancel: () => void
}

/**
 * 「从剧本提炼 → 生成图 → 落库」的公共弹窗。
 *
 * 人物与背景共用:两侧的交互完全一致(提炼 → 可改 → 生成 → 预览 → 落库),不同的只有
 * 生成方式与绑定去处,故经 onGenerate/onSave 注入,弹窗内不按 subject 分流(规范 4)。
 * 生成是同步 HTTP(与素材库一致):一次十几秒,用户在弹窗里等得起,不引入任务队列。
 */
export default function GenerateFromScriptModal({
  visible, subjectKey, subject, episodeId, projectId, initialPrompt,
  onGenerate, onSave, onCancel,
}: GenerateFromScriptModalProps) {
  const formApiRef = useRef<FormApi | null>(null)
  const [models, setModels] = useState<ImageModelOption[]>([])
  const [model, setModel] = useState('')
  const [size, setSize] = useState('')
  const [prompt, setPrompt] = useState('')
  const [imageB64, setImageB64] = useState('')
  const [busy, setBusy] = useState(false)
  const [extracting, setExtracting] = useState(false)

  const applyModel = (val: string, list: ImageModelOption[]) => {
    setModel(val)
    formApiRef.current?.setValue?.('model', val)
    const res = list.find(m => m.value === val)?.default_resolution ?? ''
    setSize(res)                    // 选模型即带出其默认尺寸(前端零规则,后端声明驱动)
    formApiRef.current?.setValue?.('size', res)
  }

  const doExtract = async () => {
    setExtracting(true)
    try {
      const r = await promptApi.extract({
        subject, key: subjectKey, episode_id: episodeId, project_id: projectId })
      setPrompt(r.prompt)
      formApiRef.current?.setValue?.('prompt', r.prompt)
    } catch (e: unknown) {
      // 后端把"不支持提炼"与"原料不足"都映射成 422 且 detail 可读,直接展示即可
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.warning(err?.response?.data?.detail || '提炼失败，请手写描述')
    } finally { setExtracting(false) }
  }

  // 打开时载入模型;已有 prompt 直接填,否则自动提炼一次 —— 用户点开就是为了拿到描述,
  // 让他对着空框再点一次按钮是多余的一步。
  useEffect(() => {
    if (!visible) return
    setImageB64('')
    setPrompt(initialPrompt || '')
    formApiRef.current?.setValue?.('prompt', initialPrompt || '')
    configApi.listImageModels()
      .then(r => {
        setModels(r.models)
        if (r.default) applyModel(r.default, r.models)
      })
      .catch(() => Toast.error('加载图片模型失败'))
    if (!initialPrompt) void doExtract()
    // subjectKey 变化即换了提炼对象,要重新提炼
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, subjectKey])

  const req = (): GenerateRequest => ({ prompt: prompt.trim(), modelId: model, size })

  const doGenerate = async () => {
    if (!model) { Toast.error('请选择模型'); return }
    if (!prompt.trim()) { Toast.error('请输入或提炼描述'); return }
    setBusy(true)
    try {
      const b64 = await onGenerate(req())
      if (b64) setImageB64(b64)
      else Toast.error('未生成图片')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('生成失败: ' + (err?.response?.data?.detail || '请稍后重试'))
    } finally { setBusy(false) }
  }

  const doSave = async () => {
    setBusy(true)
    try {
      await onSave({ ...req(), imageB64 })
    } catch {
      // 具体错误由 onSave 提示;这里只保住预览,不让用户丢掉刚生成的图
    } finally { setBusy(false) }
  }

  return (
    <Modal
      title={`生成「${subjectKey}」的形象`}
      visible={visible}
      onCancel={onCancel}
      maskClosable={false}
      footer={
        <Space>
          <Button onClick={onCancel}>取消</Button>
          {imageB64 ? (
            <>
              <Button onClick={doGenerate} loading={busy}>重新生成</Button>
              <Button type="primary" theme="solid" onClick={doSave} loading={busy}>保存</Button>
            </>
          ) : (
            <Button type="primary" theme="solid" onClick={doGenerate} loading={busy}>生成</Button>
          )}
        </Space>
      }
    >
      <Form getFormApi={api => (formApiRef.current = api)} labelPosition="top">
        <Form.Select
          field="model" label="图片模型"
          onChange={v => applyModel(String(v ?? ''), models)}
          optionList={models.map(m => ({ value: m.value, label: m.label }))}
        />
        <Form.Select
          field="size" label="尺寸"
          onChange={v => setSize(String(v ?? ''))}
          optionList={(models.find(m => m.value === model)?.resolutions ?? [])
            .map(r => ({ value: r, label: r }))}
        />
        <Form.TextArea
          field="prompt" label="画面描述" rows={6}
          onChange={v => setPrompt(String(v ?? ''))}
          placeholder="从剧本自动提炼；可继续修改"
        />
        <Space>
          <Button theme="borderless" loading={extracting} onClick={doExtract}>
            重新从剧本提炼
          </Button>
          <Text type="tertiary">描述会随图一起存下，重新生成时改它即可</Text>
        </Space>
        {imageB64 && <PreviewImage src={`data:image/png;base64,${imageB64}`} alt={subjectKey} />}
      </Form>
    </Modal>
  )
}
