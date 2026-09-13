import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import {
  Button, Card, Empty, Form, ImagePreview, List, Modal, Space, Tag, Toast, Typography, Upload,
} from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconPlus, IconDelete, IconUpload, IconAIImageLevel1 } from '@douyinfe/semi-icons'
import {
  charactersApi, configApi, assetsApi, projectsApi,
  Character, Look, CharacterViewName, ImageModelOption, Asset,
} from '../services/api'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import PreviewImage from '../components/PreviewImage'
import FourViewCropper from '../components/FourViewCropper'

const { Text } = Typography

const VIEWS: CharacterViewName[] = ['front', 'side', 'back', 'face']
const VIEW_LABEL: Record<CharacterViewName, string> = {
  front: '正面', side: '侧面', back: '背面', face: '面部特写',
}

const VIEW_KEY: Record<CharacterViewName, keyof Look> = {
  front: 'front_key', side: 'side_key', back: 'back_key', face: 'face_key',
}

interface CharacterFormValues {
  name?: string
  description?: string
}

interface LookFormValues {
  name?: string
  is_default?: boolean
}

export default function CharactersPage() {
  const { id: projectId } = useParams<{ id: string }>()
  const [characters, setCharacters] = useState<Character[]>([])
  const [looksByCharacter, setLooksByCharacter] = useState<Record<string, Look[]>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [projectTitle, setProjectTitle] = useState<string>('')

  useEffect(() => {
    if (projectId) projectsApi.get(projectId).then(p => setProjectTitle(p.title)).catch(() => {})
  }, [projectId])

  const [charModalOpen, setCharModalOpen] = useState(false)
  const charFormApiRef = useRef<FormApi<CharacterFormValues> | null>(null)

  const [lookModalOpen, setLookModalOpen] = useState(false)
  const [lookTarget, setLookTarget] = useState<Character | null>(null)
  const lookFormApiRef = useRef<FormApi<LookFormValues> | null>(null)

  const [genOpen, setGenOpen] = useState(false)
  const [genTarget, setGenTarget] = useState<{ character: Character; look: Look } | null>(null)
  const [imageModels, setImageModels] = useState<ImageModelOption[]>([])
  const [genModel, setGenModel] = useState('')
  const [genCharDesc, setGenCharDesc] = useState('')
  const [genLookDesc, setGenLookDesc] = useState('')
  const [genViews, setGenViews] = useState<Record<CharacterViewName, string> | null>(null)
  const [genSheet, setGenSheet] = useState<string>('')
  const [genBusy, setGenBusy] = useState(false)

  const [importTarget, setImportTarget] = useState<{ character: Character; look: Look } | null>(null)
  const [charAssets, setCharAssets] = useState<Asset[]>([])
  const [importing, setImporting] = useState(false)
  // 人工裁切:自动识别留白分界失败(或用户主动想改切法)时的出口。
  // target 记住要落到哪个 Look,src 是待裁的整张 sheet。
  const [cropState, setCropState] = useState<
    { character: Character; look: Look; src: string } | null>(null)
  const [cropSaving, setCropSaving] = useState(false)
  const [pv, setPv] = useState<{ srcs: string[]; index: number; visible: boolean }>(
    { srcs: [], index: 0, visible: false })

  const loadLooks = (cid: string) => {
    if (!projectId) return
    charactersApi.listLooks(projectId, cid)
      .then(ls => setLooksByCharacter(prev => ({ ...prev, [cid]: ls })))
      .catch(() => Toast.error('加载造型失败'))
  }

  const load = () => {
    if (!projectId) return
    setLoading(true)
    charactersApi.list(projectId)
      .then(cs => {
        setCharacters(cs)
        cs.forEach(c => loadLooks(c.id))
      })
      .catch(() => Toast.error('加载角色失败'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [projectId])

  const openCreateCharacter = () => setCharModalOpen(true)

  const saveCharacter = async () => {
    if (!projectId) return
    const values = (charFormApiRef.current?.getValues?.() || {}) as CharacterFormValues
    const name = values.name?.trim()
    if (!name) { Toast.error('请输入角色名'); return }
    setSaving(true)
    try {
      await charactersApi.create(projectId, { name, description: values.description?.trim() || undefined })
      Toast.success('已创建角色')
      setCharModalOpen(false)
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setSaving(false) }
  }

  const onDeleteCharacter = (c: Character) => {
    Modal.confirm({
      title: '删除角色',
      content: `删除「${c.name}」将同时删除其所有造型与四视图,确定继续?`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        if (!projectId) return
        try { await charactersApi.remove(projectId, c.id); Toast.success('已删除'); load() }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const uploadVoice = async (c: Character, file: File) => {
    if (!projectId) return
    try {
      await charactersApi.uploadVoice(projectId, c.id, file)
      Toast.success('已上传音色')
      load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('上传失败: ' + (err?.response?.data?.detail || '请传 2–15 秒的 wav/mp3'))
    }
  }

  const removeVoice = (c: Character) => {
    Modal.confirm({
      title: '删除音色', content: `删除「${c.name}」的音色?`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        if (!projectId) return
        try { await charactersApi.deleteVoice(projectId, c.id); Toast.success('已删除'); load() }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const openCreateLook = (c: Character) => { setLookTarget(c); setLookModalOpen(true) }
  const saveLook = async () => {
    if (!projectId || !lookTarget) return
    const values = (lookFormApiRef.current?.getValues?.() || {}) as LookFormValues
    const name = values.name?.trim()
    if (!name) { Toast.error('请输入造型名'); return }
    setSaving(true)
    try {
      await charactersApi.createLook(projectId, lookTarget.id, { name, is_default: !!values.is_default })
      Toast.success('已创建造型')
      setLookModalOpen(false)
      loadLooks(lookTarget.id)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('创建失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setSaving(false) }
  }

  const onDeleteLook = (c: Character, lk: Look) => {
    Modal.confirm({
      title: '删除造型',
      content: `删除「${lk.name}」及其四视图?`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        if (!projectId) return
        try { await charactersApi.removeLook(projectId, c.id, lk.id); Toast.success('已删除'); loadLooks(c.id) }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const uploadOneView = async (c: Character, lk: Look, view: CharacterViewName, file: File) => {    if (!projectId) return
    try {
      await charactersApi.uploadView(projectId, c.id, lk.id, view, file)
      Toast.success(`已上传${VIEW_LABEL[view]}`)
      loadLooks(c.id)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('上传失败: ' + (err?.response?.data?.detail || '请重试'))
    }
  }

  const openGenerate = (c: Character, lk: Look) => {
    setGenTarget({ character: c, look: lk })
    setGenViews(null)
    // 提示词以 AI 抽的外貌为主:退化成只有角色名时,生成的图会完全丢掉外貌特征
    // (发色/发型/衣着…),角色形象与剧本脱钩。
    setGenCharDesc(c.appearance || c.description || c.name)
    setGenLookDesc(lk.name)
    setGenOpen(true)
    configApi.listImageModels()
      .then(r => {
        setImageModels(r.models)
        if (r.default) setGenModel(r.default)
      })
      .catch(() => Toast.error('加载图片模型失败'))
  }

  const doGenerate = async () => {
    if (!projectId || !genTarget) return
    if (!genModel) { Toast.error('请选择模型'); return }
    setGenBusy(true)
    try {
      const r = await charactersApi.generateSheet(projectId, genTarget.character.id, genTarget.look.id, {
        model_id: genModel,
        character_desc: genCharDesc.trim() || undefined,
        look_desc: genLookDesc.trim() || undefined,
      })
      setGenSheet(r.sheet_b64)
      setGenViews(r.views)
      // views 为 null = 后端自动识别留白分界失败(生成本身成功)。直接转人工裁切,
      // 不让用户为一张切不开的图重新烧一次生成。
      if (r.views === null) {
        setGenOpen(false)
        setCropState({
          character: genTarget.character, look: genTarget.look,
          src: `data:image/png;base64,${r.sheet_b64}`,
        })
        Toast.warning('未能自动识别四视图分界，请手动裁切')
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('生成失败: ' + (err?.response?.data?.detail || '请稍后重试'))
    } finally { setGenBusy(false) }
  }

  /** 人工裁切结果落库,复用既有 views-from-generated 端点(与 AI 生成保存同一条路)。 */
  const saveCropped = async (views: Record<CharacterViewName, string>) => {
    if (!projectId || !cropState) return
    setCropSaving(true)
    try {
      await charactersApi.saveGeneratedViews(projectId, cropState.character.id, cropState.look.id, {
        front_b64: views.front, side_b64: views.side,
        back_b64: views.back, face_b64: views.face,
      })
      Toast.success('已保存四视图')
      const cid = cropState.character.id
      setCropState(null)
      loadLooks(cid)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || '请重试'))
    } finally { setCropSaving(false) }
  }

  const saveGenerated = async () => {
    if (!projectId || !genTarget || !genViews) return
    setGenBusy(true)
    try {
      await charactersApi.saveGeneratedViews(projectId, genTarget.character.id, genTarget.look.id, {
        front_b64: genViews.front, side_b64: genViews.side, back_b64: genViews.back,
        face_b64: genViews.face,
      })
      Toast.success('已保存四视图')
      setGenOpen(false)
      loadLooks(genTarget.character.id)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || '请重试'))
    } finally { setGenBusy(false) }
  }

  const openImport = (character: Character, look: Look) => {
    setImportTarget({ character, look })
    assetsApi.list('character').then(setCharAssets).catch(() => setCharAssets([]))
  }

  const doImport = async (asset: Asset) => {
    if (!projectId || !importTarget) return
    setImporting(true)
    try {
      await charactersApi.importFromAsset(projectId, importTarget.character.id, importTarget.look.id, asset.id)
      Toast.success('已从素材库导入四视图')
      setImportTarget(null)
      loadLooks(importTarget.character.id)
    } catch (e: unknown) {
      const err = e as { response?: { status?: number; data?: { detail?: string } } }
      // 422 = 图切不开/不是图片(内容问题),不是数据缺失 → 转人工裁切,用素材原图当底图
      if (err?.response?.status === 422) {
        const { character, look } = importTarget
        setImportTarget(null)
        setCropState({ character, look, src: asset.url })
        Toast.warning(err.response?.data?.detail || '未能自动识别四视图分界，请手动裁切')
        return
      }
      Toast.error('导入失败: ' + (err?.response?.data?.detail || '请重试'))
    } finally { setImporting(false) }
  }

  const renderLook = (c: Character, lk: Look) => (
    <Card
      key={lk.id}
      title={
        <Space>
          <Text strong>{lk.name}</Text>
          {lk.is_default ? <Tag color="green" shape="circle">默认</Tag> : null}
        </Space>
      }
      headerExtraContent={
        <Space>
          <Button icon={<IconAIImageLevel1 />} onClick={() => openGenerate(c, lk)}>AI 生成四视图</Button>
          <Button onClick={() => openImport(c, lk)}>从素材库导入</Button>
          <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDeleteLook(c, lk)} />
        </Space>
      }
    >
      <Space wrap align="start">
        {VIEWS.map(v => {
          const key = lk[VIEW_KEY[v]] as string | null | undefined
          return (
            <Space vertical align="start" key={v}>
              <Text type="tertiary">{VIEW_LABEL[v]}</Text>
              {key
                ? <PreviewImage src={`/api/characters/view/${key}`} alt={`${lk.name}-${VIEW_LABEL[v]}`} height={120}
                    preview={false}
                    onClick={() => {
                      const srcs = VIEWS.filter(vw => lk[VIEW_KEY[vw]])
                        .map(vw => `/api/characters/view/${lk[VIEW_KEY[vw]]}`)
                      setPv({ srcs, index: srcs.indexOf(`/api/characters/view/${key}`), visible: true })
                    }} />
                : <Text type="tertiary">暂无图</Text>}
              <Upload
                action=""
                accept="image/*"
                showUploadList={false}
                beforeUpload={({ file: f }: { file: FileItem }) => {
                  if (f.fileInstance) uploadOneView(c, lk, v, f.fileInstance)
                  return { autoRemove: false, status: 'validateFail', shouldUpload: false }
                }}
              >
                <Button icon={<IconUpload />}>上传{VIEW_LABEL[v]}</Button>
              </Upload>
            </Space>
          )
        })}
      </Space>
    </Card>
  )

  const renderCharacter = (c: Character) => {
    const looks = looksByCharacter[c.id] || []
    return (
      <List.Item
        key={c.id}
        main={
          <Space vertical align="start">
            <Space>
              <Text strong>{c.name}</Text>
              {/* 优先展示 AI 抽的外貌:那是角色的实际形象依据(生成 Look 也用它)。
                  只读 description 会让确认角色后的页面全是「—」—— 外貌明明已入库。 */}
              <Text type="tertiary">{c.appearance || c.description || '—'}</Text>
            </Space>
            <Space align="center">
              <Text type="tertiary">音色</Text>
              {c.voice_key ? (
                <Space align="center">
                  <audio controls src={`/api/characters/voice/${c.voice_key}`} />
                  <Upload
                    action="" accept="audio/*" showUploadList={false}
                    beforeUpload={({ file: f }: { file: FileItem }) => {
                      if (f.fileInstance) uploadVoice(c, f.fileInstance)
                      return { autoRemove: false, status: 'validateFail', shouldUpload: false }
                    }}
                  >
                    <Button icon={<IconUpload />}>替换音色</Button>
                  </Upload>
                  <Button type="danger" theme="borderless" icon={<IconDelete />}
                          onClick={() => removeVoice(c)} />
                </Space>
              ) : (
                <Upload
                  action="" accept="audio/*" showUploadList={false}
                  beforeUpload={({ file: f }: { file: FileItem }) => {
                    if (f.fileInstance) uploadVoice(c, f.fileInstance)
                    return { autoRemove: false, status: 'validateFail', shouldUpload: false }
                  }}
                >
                  <Button icon={<IconUpload />}>上传音色(2–15s wav/mp3)</Button>
                </Upload>
              )}
            </Space>
            {looks.length
              ? <Space vertical align="start">{looks.map(lk => renderLook(c, lk))}</Space>
              : <Text type="tertiary">暂无造型</Text>}
          </Space>
        }
        extra={
          <Space>
            <Button icon={<IconPlus />} onClick={() => openCreateLook(c)}>新建造型</Button>
            <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDeleteCharacter(c)} />
          </Space>
        }
      />
    )
  }

  return (
    <PageShell
      title="角色"
      description="本项目共享的角色与造型,每套造型可有正 / 侧 / 背 / 面部特写四视图;可从素材库人物一键导入,供分镜参考"
      breadcrumb={[
        { label: '作品列表', href: '/' },
        { label: projectTitle || '作品', href: `/projects/${projectId}` },
        { label: '角色' },
      ]}
      headerExtra={
        <Button colorful theme="solid" type="primary" icon={<IconPlus />} onClick={openCreateCharacter}>新建角色</Button>
      }
    >
      {loading ? (
        <PageLoading />
      ) : characters.length === 0 ? (
        <PageEmpty title="还没有角色" description="点击右上角「新建角色」，或从素材库人物导入" />
      ) : (
        <Card>
          <List dataSource={characters} renderItem={renderCharacter} />
        </Card>
      )}

      <Modal
        title="新建角色"
        visible={charModalOpen}
        onCancel={() => setCharModalOpen(false)}
        onOk={saveCharacter}
        okText="保存" cancelText="取消" confirmLoading={saving} width={560}
      >
        <Form<CharacterFormValues>
          key={charModalOpen ? 'char-open' : 'char-closed'}
          getFormApi={api => (charFormApiRef.current = api)}
          labelPosition="top"
        >
          <Form.Input
            field="name" label="角色名" placeholder="如 林夏"
            rules={[{ required: true, message: '请输入角色名' }]}
          />
          <Form.TextArea field="description" label="描述(可选)" placeholder="外貌 / 性格 / 设定等" />
        </Form>
      </Modal>

      <Modal
        title="新建造型"
        visible={lookModalOpen}
        onCancel={() => setLookModalOpen(false)}
        onOk={saveLook}
        okText="保存" cancelText="取消" confirmLoading={saving} width={560}
      >
        <Form<LookFormValues>
          key={lookTarget?.id ?? 'look-closed'}
          getFormApi={api => (lookFormApiRef.current = api)}
          initValues={{ name: '默认造型', is_default: false }}
          labelPosition="top"
        >
          <Form.Input
            field="name" label="造型名" placeholder="如 日常装"
            rules={[{ required: true, message: '请输入造型名' }]}
          />
          <Form.Switch field="is_default" label="设为默认造型" />
        </Form>
      </Modal>

      <Modal
        title="AI 生成四视图"
        visible={genOpen}
        onCancel={() => setGenOpen(false)}
        footer={
          genViews ? (
            <Space>
              <Button onClick={() => setGenViews(null)}>重新生成</Button>
              {/* 自动裁切成功也允许改切法 —— 留白检测切对了但切得不合意时的出口 */}
              {genSheet && genTarget && (
                <Button onClick={() => {
                  setGenOpen(false)
                  setCropState({
                    character: genTarget.character, look: genTarget.look,
                    src: `data:image/png;base64,${genSheet}`,
                  })
                }}>手动裁切</Button>
              )}
              <Button type="primary" theme="solid" loading={genBusy} onClick={saveGenerated}>保存</Button>
            </Space>
          ) : (
            <Button type="primary" theme="solid" loading={genBusy} onClick={doGenerate}>生成</Button>
          )
        }
        width={640}
      >
        <Form
          key={genOpen ? 'gen-open' : 'gen-closed'}
          initValues={{ model: genModel, character_desc: genCharDesc, look_desc: genLookDesc }}
          labelPosition="top"
        >
          <Form.Select
            field="model" label="模型" placeholder="选择图片模型"
            onChange={v => setGenModel(v as string)}
          >
            {imageModels.map(m => (
              <Form.Select.Option key={m.value} value={m.value}>{m.label}</Form.Select.Option>
            ))}
          </Form.Select>
          <Form.TextArea
            field="character_desc" label="角色描述"
            placeholder="如:二十岁女性,短发,清瘦"
            onChange={v => setGenCharDesc(v)}
          />
          <Form.TextArea
            field="look_desc" label="造型 / 服饰描述"
            placeholder="如:白衬衫 + 牛仔裤,帆布鞋"
            onChange={v => setGenLookDesc(v)}
          />
        </Form>
        {genViews ? (
          <Space wrap align="start">
            {VIEWS.map(v => (
              <Space vertical align="start" key={v}>
                <Text type="tertiary">{VIEW_LABEL[v]}</Text>
                <PreviewImage src={`data:image/png;base64,${genViews[v]}`} alt={`${VIEW_LABEL[v]}预览`} height={200} />
              </Space>
            ))}
          </Space>
        ) : null}
      </Modal>

      <Modal
        title="从素材库导入四视图"
        visible={!!importTarget}
        onCancel={() => setImportTarget(null)}
        footer={null}
        width={560}
      >
        {charAssets.length === 0 ? (
          <Empty description="素材库暂无人物素材,可去素材库生成后再导入" />
        ) : (
          <List
            dataSource={charAssets}
            renderItem={(a: Asset) => (
              <List.Item
                header={<PreviewImage src={a.url} alt={a.name} height={64} />}
                main={<Text>{a.name}</Text>}
                extra={<Button loading={importing} onClick={() => doImport(a)}>选它</Button>}
              />
            )}
          />
        )}
      </Modal>

      <FourViewCropper
        visible={!!cropState}
        src={cropState?.src ?? ''}
        saving={cropSaving}
        onCancel={() => setCropState(null)}
        onDone={saveCropped}
      />

      <ImagePreview
        src={pv.srcs}
        visible={pv.visible}
        currentIndex={pv.index}
        onVisibleChange={v => setPv(p => ({ ...p, visible: v }))}
        onChange={i => setPv(p => ({ ...p, index: i }))}
      />
    </PageShell>
  )
}
