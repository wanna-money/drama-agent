import { useEffect, useRef, useState } from 'react'
import {
  Button, Card, Col, Divider, Form, ImagePreview, List, Modal, Row, Space, Tabs, Tag, Toast, Typography, Upload,
} from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import type { FileItem } from '@douyinfe/semi-ui/lib/es/upload'
import { IconPlus, IconDelete, IconUpload, IconAIImageLevel1 } from '@douyinfe/semi-icons'
import { assetsApi, configApi, promptApi, Asset, AssetCategory, ImageModelOption } from '../services/api'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import PreviewImage from '../components/PreviewImage'

const { Text } = Typography

const CATEGORY_LABEL: Record<AssetCategory, string> = {
  character: '人物',
  background: '背景',
  prop: '道具',
  costume: '服饰',
}

const CATEGORIES: AssetCategory[] = ['character', 'background', 'prop', 'costume']

const TAB_LIST = [
  { itemKey: 'all', tab: '全部' },
  ...CATEGORIES.map(c => ({ itemKey: c, tab: CATEGORY_LABEL[c] })),
]

// 各分类的推荐 prompt:选定分类后预填,用户可改 + AI 润色。
// 每条都按「主体 → 构图 → 材质光影 → 约束」的块序写,并带上该类的锁死项 ——
// 用户直接生成也能得到可复用的素材(锁死项的完整说明在后端 _SUBJECT_BLOCKS)。
const RECOMMENDED_PROMPT: Record<AssetCategory, string> = {
  character: '角色四视图设定板,从左到右:正面全身、侧面全身、背面全身、面部特写;同一角色,一致的五官/发型/妆容/服装,各视图服装细节不得变化;柔和均匀光,纯白背景,居中,无文字无水印无边框',
  background: '场景概念图,明确视角与尺度,写清时间与天气,材质与光源具体,电影感光影,层次丰富,画面无人物,高细节,无文字无水印',
  prop: '道具特写,单一主体居中,材质与工艺清晰(注明金属/塑料/皮革等),柔光棚拍,纯白背景,不带关联场景、不带手部,无文字无水印',
  costume: '服装展示图,平铺(或立体挂展,择一),面料/版型/缝线/配件细节清晰,柔和均匀光,纯白背景,画面无人物,无文字无水印',
}

interface AssetFormValues {
  category?: AssetCategory
  name?: string
  description?: string
}

export default function AssetsPage() {
  const [assets, setAssets] = useState<Asset[]>([])
  const [preview, setPreview] = useState<{ visible: boolean; index: number }>({ visible: false, index: 0 })
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<string>('all')
  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState<Asset | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const formApiRef = useRef<FormApi<AssetFormValues> | null>(null)
  const genFormApiRef = useRef<FormApi | null>(null)
  const editFormApiRef = useRef<FormApi | null>(null)
  const [genOpen, setGenOpen] = useState(false)
  const [imageModels, setImageModels] = useState<ImageModelOption[]>([])
  const [imageDefault, setImageDefault] = useState<string>('')
  const [genModel, setGenModel] = useState<string>('')
  const [genPrompt, setGenPrompt] = useState('')
  const [genSize, setGenSize] = useState<string>('')
  const [genPreview, setGenPreview] = useState<string>('')
  const [genName, setGenName] = useState('')
  const [genCategory, setGenCategory] = useState<AssetCategory | ''>('')
  const [genBusy, setGenBusy] = useState(false)
  const [optimizing, setOptimizing] = useState(false)

  const optimizePrompt = async (target: 'gen' | 'edit') => {
    const cur = genPrompt.trim()
    if (!cur) { Toast.error('请先输入描述'); return }
    const category = target === 'gen' ? genCategory : editing?.category
    // 四类都有各自的"锁死项"(后端 _SUBJECT_BLOCKS):背景不许出现人物、道具不许带手…
    // 只传 character 会让另外三类拿不到专项约束,生成出无法复用的素材。
    const subject = category || undefined
    setOptimizing(true)
    try {
      const r = await promptApi.optimize({ raw_prompt: cur, kind: 'image', subject })
      const optimized = r.optimized || cur
      setGenPrompt(optimized)
      if (target === 'gen') genFormApiRef.current?.setValue?.('prompt', optimized)
      else editFormApiRef.current?.setValue?.('aiPrompt', optimized)
      Toast.success('已优化,可继续编辑')
    } catch { Toast.error('优化失败') }
    finally { setOptimizing(false) }
  }

  const load = (category: string) => {
    setLoading(true)
    assetsApi.list(category === 'all' ? undefined : (category as AssetCategory))
      .then(setAssets)
      .catch(() => Toast.error('加载失败'))
      .finally(() => setLoading(false))
  }
  useEffect(() => { load(tab) }, [tab])

  const clearGenScratch = () => { setGenPreview(''); setGenPrompt(''); setGenName('') }

  const openCreate = () => { setEditing(null); setFile(null); clearGenScratch(); setModalOpen(true) }
  const openEdit = (a: Asset) => { setEditing(a); setFile(null); clearGenScratch(); setModalOpen(true) }

  const applyModel = (val: string, models: ImageModelOption[]) => {
    setGenModel(val)
    genFormApiRef.current?.setValue('model', val)
    const res = models.find(m => m.value === val)?.default_resolution ?? ''
    setGenSize(res)                                   // 选模型即带出其默认尺寸(前端零规则,后端声明驱动)
    genFormApiRef.current?.setValue('size', res)
  }

  const openGenerate = () => {
    clearGenScratch()
    setGenCategory('')
    setGenSize('')
    setGenOpen(true)
    configApi.listImageModels()
      .then(r => {
        setImageModels(r.models)
        setImageDefault(r.default || '')
        if (r.default) applyModel(r.default, r.models)
      })
      .catch(() => Toast.error('加载图片模型失败'))
  }

  const doGenerate = async () => {
    if (!genModel) { Toast.error('请选择模型'); return }
    if (!genPrompt.trim()) { Toast.error('请输入描述'); return }
    setGenBusy(true)
    try {
      const r = await assetsApi.generate({ model_id: genModel, prompt: genPrompt.trim(), size: genSize || undefined })
      if (r.images[0]) setGenPreview(r.images[0])
      else Toast.error('未生成图片')
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('生成失败: ' + (err?.response?.data?.detail || '请稍后重试'))
    } finally { setGenBusy(false) }
  }

  const saveGenerated = async () => {
    if (!genCategory) { Toast.error('请选择分类'); return }
    if (!genName.trim()) { Toast.error('请输入名称'); return }
    setGenBusy(true)
    try {
      await assetsApi.saveGenerated({ category: genCategory, name: genName.trim(), image_b64: genPreview })
      Toast.success('已保存到素材库')
      setGenOpen(false); load(tab)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setGenBusy(false) }
  }

  const onDelete = (a: Asset) => {
    Modal.confirm({
      title: '删除素材',
      content: `删除「${a.name}」?已引用它的剧集参考图不受影响。`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try { await assetsApi.delete(a.id); Toast.success('已删除'); load(tab) }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const save = async () => {
    const values = (formApiRef.current?.getValues?.() || {}) as AssetFormValues
    const name = values.name?.trim()
    if (!editing) {
      if (!values.category) { Toast.error('请选择分类'); return }
      if (!name) { Toast.error('请输入名称'); return }
      if (!file) { Toast.error('请选择图片'); return }
    }
    const form = new FormData()
    if (values.category) form.append('category', values.category)
    if (name) form.append('name', name)
    if (values.description != null) form.append('description', values.description)
    if (file) form.append('file', file)
    setSaving(true)
    try {
      if (editing) await assetsApi.update(editing.id, form)
      else await assetsApi.create(form)
      Toast.success(editing ? '已更新' : '已上传')
      setModalOpen(false)
      load(tab)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setSaving(false) }
  }

  const renderItem = (a: Asset) => (
    <List.Item
      key={a.id}
      header={<PreviewImage src={a.url} alt={a.name} width={64} height={64} preview={false}
        onClick={() => setPreview({ visible: true, index: assets.findIndex(x => x.id === a.id) })} />}
      main={
        <Space vertical align="start">
          <Space>
            <Text strong>{a.name}</Text>
            <Tag color="blue" shape="circle">{CATEGORY_LABEL[a.category]}</Tag>
          </Space>
          <Text type="tertiary">{a.description || '—'}</Text>
        </Space>
      }
      extra={
        <Space>
          <Button onClick={() => openEdit(a)}>编辑</Button>
          <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDelete(a)} />
        </Space>
      }
    />
  )

  return (
    <PageShell
      title="素材库"
      description="全局共享的人物 / 背景 / 道具 / 服饰参考图;人物可在项目角色里导入为造型四视图,创作时也可直接从库中选择"
      headerExtra={
        <Space>
          <Button colorful theme="solid" type="primary" icon={<IconPlus />} onClick={openCreate}>上传素材</Button>
          <Button colorful theme="solid" type="primary" icon={<IconAIImageLevel1 />} onClick={openGenerate}>AI 生成</Button>
        </Space>
      }
    >
      <Row gutter={[0, 16]}>
        <Col span={24}><Divider /></Col>

        <Col span={24}>
          <Tabs type="line" activeKey={tab} tabList={TAB_LIST} onChange={setTab} />
        </Col>

        <Col span={24}>
          {loading ? (
            <PageLoading />
          ) : assets.length === 0 ? (
            tab === 'all' ? (
              <PageEmpty title="还没有素材" description="点击右上角「上传素材」或「AI 生成」，添加人物 / 背景 / 道具 / 服饰参考图" />
            ) : (
              <PageEmpty
                title={`${CATEGORY_LABEL[tab as AssetCategory]}分类下暂无素材`}
                description="切换到「全部」查看所有素材，或点击右上角新增"
              />
            )
          ) : (
            <Card>
              <List dataSource={assets} renderItem={renderItem} />
            </Card>
          )}
        </Col>
      </Row>

      <ImagePreview
        src={assets.map(a => a.url)}
        visible={preview.visible}
        currentIndex={preview.index}
        onVisibleChange={v => setPreview(p => ({ ...p, visible: v }))}
        onChange={i => setPreview(p => ({ ...p, index: i }))}
      />

      <Modal
        title={editing ? '编辑素材' : '上传素材'}
        visible={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={save}
        okText="保存" cancelText="取消" confirmLoading={saving} width={560}
      >
        <Form<AssetFormValues>
          key={editing?.id ?? 'create'}
          getFormApi={api => (formApiRef.current = api)}
          initValues={{
            category: editing?.category,
            name: editing?.name,
            description: editing?.description || '',
          }}
          labelPosition="top"
        >
          <Form.Select
            field="category" label="分类"
            placeholder="选择素材分类"
            rules={editing ? undefined : [{ required: true, message: '请选择分类' }]}
          >
            {CATEGORIES.map(c => (
              <Form.Select.Option key={c} value={c}>{CATEGORY_LABEL[c]}</Form.Select.Option>
            ))}
          </Form.Select>
          <Form.Input
            field="name" label="名称" placeholder="如 女主-林夏"
            rules={editing ? undefined : [{ required: true, message: '请输入名称' }]}
          />
          <Form.TextArea field="description" label="描述(可选)" placeholder="外貌 / 风格 / 用途等备注" />
        </Form>
        <Space vertical align="start">
          <Text type="tertiary">{editing ? '图片(不选则保留原图)' : '图片'}</Text>
          <Upload
            action=""
            accept="image/*"
            showUploadList={false}
            beforeUpload={({ file: f }: { file: FileItem }) => {
              if (f.fileInstance) setFile(f.fileInstance)
              return { autoRemove: false, status: 'validateFail', shouldUpload: false }
            }}
          >
            <Button icon={<IconUpload />}>选择图片</Button>
          </Upload>
          {file ? <Text>{file.name}</Text> : editing ? <PreviewImage src={editing.url} alt={editing.name} width={64} height={64} /> : null}
        </Space>
        {editing ? (
          <>
            <Divider />
            <Form labelPosition="top" getFormApi={api => (editFormApiRef.current = api)}>
              <Form.TextArea
                field="aiPrompt" label="AI 改图(基于当前图生成新图,可另存为新素材)"
                placeholder="如:改成夜晚场景、换成红色服饰"
                onChange={v => setGenPrompt(v)}
              />
              <Button colorful theme="solid" type="primary" loading={optimizing} onClick={() => optimizePrompt('edit')}>✨ 优化描述</Button>
              <Button
                loading={genBusy}
                onClick={async () => {
                  if (!genPrompt.trim()) { Toast.error('请输入改图描述'); return }
                  let list = imageModels
                  let def = imageDefault
                  if (!list.length) {
                    const r = await configApi.listImageModels()
                      .catch(() => ({ models: [] as ImageModelOption[], default: null }))
                    list = r.models
                    def = r.default || ''
                    setImageModels(list)
                    setImageDefault(def)
                    if (def) setGenModel(def)
                  }
                  setGenBusy(true)
                  try {
                    const r = await assetsApi.edit({
                      asset_id: editing.id,
                      model_id: genModel || def || '',
                      prompt: genPrompt.trim(),
                    })
                    if (r.images[0]) { setGenPreview(r.images[0]); Toast.success('已生成,可在下方另存') }
                  } catch (e: unknown) {
                    const err = e as { response?: { data?: { detail?: string } } }
                    Toast.error(err?.response?.data?.detail || '当前图片模型不支持编辑')
                  } finally { setGenBusy(false) }
                }}
              >AI 生成改图</Button>
              {genPreview ? (
                <>
                  <PreviewImage src={`data:image/png;base64,${genPreview}`} alt="改图预览" width={160} height={160} />
                  <Form.Input
                    field="aiNewName" label="新素材名称" placeholder="新素材名称"
                    onChange={v => setGenName(v)}
                  />
                  <Button
                    type="primary" loading={genBusy}
                    onClick={async () => {
                      if (!genName.trim()) { Toast.error('请输入新素材名称'); return }
                      setGenBusy(true)
                      try {
                        await assetsApi.saveGenerated({
                          category: editing.category, name: genName.trim(), image_b64: genPreview,
                        })
                        Toast.success('已另存为新素材')
                        setModalOpen(false); setGenPreview(''); setGenName(''); load(tab)
                      } catch { Toast.error('保存失败') }
                      finally { setGenBusy(false) }
                    }}
                  >另存为新素材</Button>
                </>
              ) : null}
            </Form>
          </>
        ) : null}
      </Modal>

      <Modal
        title="AI 生成素材"
        visible={genOpen}
        onCancel={() => setGenOpen(false)}
        footer={
          genPreview ? (
            <Space>
              <Button onClick={() => setGenPreview('')}>重新生成</Button>
              <Button type="primary" theme="solid" loading={genBusy} onClick={saveGenerated}>保存到素材库</Button>
            </Space>
          ) : (
            <Button type="primary" theme="solid" loading={genBusy} onClick={doGenerate}>生成</Button>
          )
        }
        width={560}
      >
        <Form
          key={genOpen ? 'gen-open' : 'gen-closed'}
          getFormApi={api => (genFormApiRef.current = api)}
          initValues={{ model: genModel, size: '' }}
          labelPosition="top"
        >
          <Form.Select
            field="model" label="模型" placeholder="选择图片模型"
            onChange={v => applyModel(v as string, imageModels)}
          >
            {imageModels.map(m => (
              <Form.Select.Option key={m.value} value={m.value}>{m.label}</Form.Select.Option>
            ))}
          </Form.Select>
          <Form.Select
            field="category" label="分类" placeholder="选择分类(将预填推荐描述)"
            onChange={v => {
              const cat = v as AssetCategory
              setGenCategory(cat)
              const rec = RECOMMENDED_PROMPT[cat]
              setGenPrompt(rec)
              genFormApiRef.current?.setValue('prompt', rec)
            }}
          >
            {CATEGORIES.map(c => (
              <Form.Select.Option key={c} value={c}>{CATEGORY_LABEL[c]}</Form.Select.Option>
            ))}
          </Form.Select>
          <Form.TextArea
            field="prompt" label="描述(prompt)"
            placeholder="选择分类后自动预填推荐描述,可自行修改;也可点「优化描述」AI 润色"
            onChange={v => setGenPrompt(v)}
          />
          <Button colorful theme="solid" type="primary" loading={optimizing} onClick={() => optimizePrompt('gen')}>✨ 优化描述</Button>
          <Form.Select
            field="size" label="尺寸" placeholder="选择尺寸(默认已按模型预选)"
            onChange={v => setGenSize(v as string)}
          >
            {(imageModels.find(m => m.value === genModel)?.resolutions ?? []).map(r => (
              <Form.Select.Option key={r} value={r}>{r}</Form.Select.Option>
            ))}
          </Form.Select>
          {genPreview ? (
            <>
              <PreviewImage src={`data:image/png;base64,${genPreview}`} alt="预览" width={200} height={200} />
              <Form.Input
                field="name" label="名称" placeholder="素材名称,如 男主-陆沉"
                onChange={v => setGenName(v)}
              />
            </>
          ) : null}
        </Form>
      </Modal>
    </PageShell>
  )
}
