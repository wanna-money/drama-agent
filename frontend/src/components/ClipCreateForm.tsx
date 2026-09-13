import { useEffect, useState } from 'react'
import { AIChatInput, Card, Toast } from '@douyinfe/semi-ui'
import type { MessageContent, Skill } from '@douyinfe/semi-ui/lib/es/aiChatInput'
import {
  assetsApi, clipsApi, configApi, filesApi, Asset, Clip, ClipRefImage, ClipRefKind,
  ClipRefVideo, ClipTaskType, VideoModelOption,
} from '../services/api'
import ClipConfigureBar from './ClipConfigureBar'
import ClipRefBar, { ClipReference } from './ClipRefBar'
import { clampDuration, durationRangeOf, splitVideoModel, videoInitValues } from './VideoModelFields'

/** 本项目已有图(与 ImagePicker 的「本项目已有」tab 同源)。 */
interface ProjectImage {
  filename: string
  url: string
}

/** 一条待提交的图片引用。累加 id 供 @ 引用条与提交定位,不复用 url 作 key ——
 *  同一张图可能被以不同用途(首帧/主体)引用两次。 */
interface PendingImageRef extends ClipRefImage {
  id: string
}

interface PendingVideoRef extends ClipRefVideo {
  id: string
  /** 该视频引用来自哪支散片(用于展示摘要);上传得来的没有。 */
  promptSummary?: string
}

let refSeq = 0
const nextRefId = (prefix: string) => `${prefix}-${++refSeq}`

interface ClipCreateFormProps {
  projectId: string
  onCreated: (clip: Clip) => void
  /** 视频模型清单 + 默认值。由 NewCreationPage 在页面级统一加载一次并下发 ——
   *  组件挂载那一刻数据就要可用,自己异步拉取会在首次渲染时拿到空值。 */
  models: VideoModelOption[]
  videoDefault: string
  /** @ 候选散片来源。由 NewCreationPage 下发 —— 它本来就在维护这份列表。
   *  只有 storage_key 非空的才会进入候选(见 buildSkills):没同步到对象存储
   *  的散片列出来选中即报错,那是"界面说的与实际不一致"。 */
  clips: Clip[]
}

/**
 * 直接生成:用户手写实际发给视频模型的 prompt,自己挑参考图 / 参考视频与参数。
 * 不过 LLM、不分镜、无审核卡点。
 *
 * 用 AIChatInput 承载,而非传统 Form:任务模式(参考生成/编辑/延长)与参考图/
 * 参考视频是同一件事的两面 —— @ 引用决定了"改哪支视频",底部参数条决定"怎么改",
 * 两者需要共享同一块输入区域,拆成分离的表单字段会割裂这层关联。
 */
export default function ClipCreateForm(
  { projectId, onCreated, models, videoDefault, clips }: ClipCreateFormProps
) {
  const [imageRefs, setImageRefs] = useState<PendingImageRef[]>([])
  const [videoRefs, setVideoRefs] = useState<PendingVideoRef[]>([])
  const [submitting, setSubmitting] = useState(false)
  // 初值 false + 失败也置 false:拿不到结论时**当作不可用**。
  // 反过来(默认可用)会让界面放行编辑/延长,而它们必须有公网存储才能工作 ——
  // 用户选完、写完提示词、提交后才在后端失败。
  const [storageAvailable, setStorageAvailable] = useState(false)
  const [assets, setAssets] = useState<Asset[]>([])
  const [images, setImages] = useState<ProjectImage[]>([])

  const [picked, setPicked] = useState(videoDefault)
  const [taskType, setTaskType] = useState<ClipTaskType>('reference')
  const initVideo = videoInitValues(models, videoDefault)
  const [resolution, setResolution] = useState(initVideo.resolution)
  const [aspectRatio, setAspectRatio] = useState(initVideo.aspect_ratio)
  const [duration, setDuration] = useState(
    durationRangeOf(models.find(m => m.value === videoDefault)).min)
  const [negativePrompt, setNegativePrompt] = useState('')

  // 挂载时一次性拉:存储状态、素材库、本项目已有图。三者都是 @ 面板或提交前门禁
  // 要用的原料,不必等用户点开 @ 才拉(那样第一次点开会有明显延迟)。
  useEffect(() => {
    configApi.storageStatus()
      .then(r => setStorageAvailable(r.available))
      .catch(() => setStorageAvailable(false))
    assetsApi.list().then(setAssets).catch(() => setAssets([]))
    filesApi.listImages(projectId).then(setImages).catch(() => setImages([]))
  }, [projectId])

  const modelOf = (value: string) => models.find(x => x.value === value)
  const currentModel = modelOf(picked)
  const maxRefImages = currentModel?.max_reference_images || 9
  const maxRefVideos = currentModel?.max_reference_videos || 0
  const hasFrameRef = imageRefs.some(r => r.kind === 'first_frame' || r.kind === 'last_frame')

  const handleModelChange = (value: string) => {
    setPicked(value)
    const m = modelOf(value)
    if (m?.default_resolution) setResolution(m.default_resolution)
    if (m?.default_aspect_ratio) setAspectRatio(m.default_aspect_ratio)
    setDuration(cur => clampDuration(cur, durationRangeOf(m)))
  }

  const addImageRef = (url: string, kind: ClipRefKind = 'first_frame') => {
    if (imageRefs.length >= maxRefImages) {
      Toast.warning(`参考图最多 ${maxRefImages} 张`)
      return
    }
    setImageRefs(prev => [...prev, { id: nextRefId('img'), url, kind, subject_name: null, view: null }])
  }

  const addVideoRef = (url: string, promptSummary?: string, duration?: number | null) => {
    if (videoRefs.length >= maxRefVideos) {
      Toast.warning(`参考视频最多 ${maxRefVideos} 支`)
      return
    }
    setVideoRefs(prev => [
      ...prev, { id: nextRefId('vid'), url, subject_name: null, duration, promptSummary },
    ])
  }

  const removeRef = (ref: ClipReference) => {
    if (ref.type === 'image') setImageRefs(prev => prev.filter(r => r.id !== ref.id))
    else setVideoRefs(prev => prev.filter(r => r.id !== ref.id))
  }

  // @ 候选:素材库(未落进本项目)+ 本项目已有图 + 有 storage_key 的散片。
  // 三种来源统一成 Skill,选中后按 kind 分流去不同的落地方式(见 handleSkillChange)。
  const availableClips = clips.filter(c => !!c.storage_key)
  const skills: (Skill & { kind: 'asset' | 'project_image' | 'clip' })[] = [
    ...assets.map(a => ({ value: `asset:${a.id}`, label: a.name, kind: 'asset' as const })),
    ...images.map(img => ({ value: `image:${img.url}`, label: img.filename, kind: 'project_image' as const })),
    ...availableClips.map(c => ({
      value: `clip:${c.id}`, label: c.prompt, kind: 'clip' as const,
    })),
  ]

  const handleSkillChange = async (sk: any) => {
    if (sk.kind === 'asset') {
      const asset = assets.find(a => `asset:${a.id}` === sk.value)
      if (!asset) return
      try {
        const r = await filesApi.copyFromAsset(projectId, asset.id, 'reference')
        addImageRef(r.url)
      } catch {
        Toast.error('添加失败')
      }
    } else if (sk.kind === 'project_image') {
      const img = images.find(i => `image:${i.url}` === sk.value)
      if (img) addImageRef(img.url)
    } else if (sk.kind === 'clip') {
      const clip = availableClips.find(c => `clip:${c.id}` === sk.value)
      if (clip?.storage_key) addVideoRef(clip.storage_key, clip.prompt, clip.duration)
    }
  }

  // 上传即传即分流:mp4/mov 走参考视频通道(存本地+传公网),其余按图片处理 ——
  // 与已有的图片上传共用同一个入口,用户不必先选"我要传的是图还是视频"。
  const handleUploadChange = ({ fileList }: any) => {
    for (const item of fileList ?? []) {
      const file = item.fileInstance as File | undefined
      if (!file) continue
      const isVideo = /\.(mp4|mov)$/i.test(file.name) || file.type?.startsWith('video/')
      if (isVideo) {
        filesApi.uploadVideo(projectId, file).then(r => {
          if (r.warning) Toast.warning(r.warning)
          addVideoRef(r.storage_key, file.name, r.duration)
        }).catch(() => Toast.error('视频上传失败'))
      } else {
        filesApi.uploadImage(projectId, file, 'reference').then(r => {
          addImageRef(r.url)
        }).catch(() => Toast.error('图片上传失败'))
      }
    }
  }

  const references: ClipReference[] = [
    ...imageRefs.map((r, i) => ({
      type: 'image' as const, id: r.id, label: `图${i + 1}`, url: r.url,
      kind: r.kind, subjectName: r.subject_name,
    })),
    ...videoRefs.map((r, i) => ({
      type: 'video' as const, id: r.id, label: `video${i + 1}`, url: r.url,
      promptSummary: r.promptSummary,
    })),
  ]

  const handleMessageSend = async (content: MessageContent) => {
    const promptText = (content.inputContents ?? [])
      .filter((c: any) => c.type === 'text')
      .map((c: any) => String(c.text ?? '')).join('').trim()
    if (!promptText) return

    const setup = (content.setup ?? {}) as Record<string, unknown>
    const chosenTaskType = (setup.task_type as ClipTaskType) ?? taskType
    const modelValue = setup.video_provider != null ? String(setup.video_provider) : picked
    // 编辑任务的时长与原视频一致,平台只收 -1(规则权威见后端 _check_duration);
    // 界面上此项已禁用,这里再收一次是双重保险,防止禁用态被绕过。
    const resolvedDuration = chosenTaskType === 'edit'
      ? -1 : Number(setup.duration ?? duration)

    setSubmitting(true)
    try {
      const clip = await clipsApi.create(projectId, {
        prompt: promptText,
        negative_prompt: negativePrompt.trim() || undefined,
        duration: resolvedDuration,
        resolution: setup.resolution != null ? String(setup.resolution) : resolution,
        aspect_ratio: setup.aspect_ratio != null ? String(setup.aspect_ratio) : aspectRatio,
        ...splitVideoModel({ video_provider: modelValue }, models),
        references: imageRefs.map(r => (
          { url: r.url, kind: r.kind, subject_name: r.subject_name, view: r.view })),
        video_refs: videoRefs.map(r => (
          { url: r.url, subject_name: r.subject_name, duration: r.duration })),
        task_type: chosenTaskType,
      })
      onCreated(clip)
      setImageRefs([])
      setVideoRefs([])
      Toast.success('已提交生成')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      Toast.error('提交失败: ' + (err?.response?.data?.detail || err?.message || '未知错误'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Card>
      <AIChatInput
        placeholder="直接写你要发给视频模型的画面描述,用 @ 引用图片或散片"
        generating={submitting}
        references={references}
        renderReference={(ref: any) => (
          <ClipRefBar
            reference={ref}
            onKindChange={(kind) => setImageRefs(
              prev => prev.map(r => r.id === ref.id ? { ...r, kind } : r))}
            onDelete={() => removeRef(ref)}
          />
        )}
        onReferenceDelete={(ref: any) => removeRef(ref)}
        skills={skills}
        skillHotKey="@"
        onSkillChange={handleSkillChange}
        uploadProps={{ action: '', accept: 'image/*,video/mp4,video/quicktime' }}
        onUploadChange={handleUploadChange}
        onMessageSend={(c: MessageContent) => { void handleMessageSend(c) }}
        renderConfigureArea={() => (
          <ClipConfigureBar
            models={models}
            picked={picked}
            taskType={taskType}
            resolution={resolution}
            aspectRatio={aspectRatio}
            duration={duration}
            negativePrompt={negativePrompt}
            storageAvailable={storageAvailable}
            hasFrameRef={hasFrameRef}
            onModelChange={handleModelChange}
            onTaskTypeChange={setTaskType}
            onResolutionChange={setResolution}
            onAspectRatioChange={setAspectRatio}
            onDurationChange={setDuration}
            onNegativePromptChange={setNegativePrompt}
          />
        )}
      />
    </Card>
  )
}
