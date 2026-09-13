import { useEffect, useRef, useState } from 'react'
import { Button, Modal, Input, InputNumber, Select, Toast, Tag, List, Card, Typography, Space, Divider, Form, Empty, Row, Col, Checkbox } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import { IconPlus, IconDelete } from '@douyinfe/semi-icons'
import { providersApi, ProviderInfo, ProviderModel, ProviderInput, ModelCost, ProtocolCatalog } from '../services/api'
import PageShell, { PageLoading } from '../components/PageShell'

const { Text } = Typography

type Kind = 'llm' | 'video' | 'image'

const emptyModel = (kind: Kind): ProviderModel => ({ id: '', label: '', kind })

const blankInput = (): ProviderInput => ({
  provider_id: '', label: '', kind: 'llm', protocol: 'openai-compat',
  base_url: '', api_key: '', models: [emptyModel('llm')], enabled: true,
  paths: {}, response_map: {},
})

const emptyCatalog: ProtocolCatalog = {
  llm: [], video: [], image: [], storage: [], ops: {}, response_fields: {},
}

export default function ProvidersPage() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [protocols, setProtocols] = useState<ProtocolCatalog>(emptyCatalog)
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingBuiltin, setEditingBuiltin] = useState(false)
  const [form, setForm] = useState<ProviderInput>(blankInput())
  const [saving, setSaving] = useState(false)
  // 自定义接入路径的开关状态不入库:paths/response_map 非空即"已启用"(单一真相)。
  // 这里只记住"用户在本次编辑中把它展开了"——刚打开时字典还是空的。
  const [accessOpen, setAccessOpen] = useState(false)
  const formApiRef = useRef<FormApi<ProviderInput> | null>(null)

  const load = () => {
    setLoading(true)
    Promise.all([providersApi.list(), providersApi.protocols()])
      .then(([ps, protos]) => { setProviders(ps); setProtocols(protos) })
      .catch(() => Toast.error('加载失败'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const openCreate = () => {
    setEditingId(null); setEditingBuiltin(false); setForm(blankInput())
    setAccessOpen(false); setModalOpen(true)
  }

  const openEdit = async (p: ProviderInfo) => {
    try {
      const full = await providersApi.get(p.provider_id)
      setEditingId(p.provider_id)
      setEditingBuiltin(full.builtin)
      // 本页只列 llm/video/image 三组(storage 走独立的存储管理页),故编辑入口
      // 拿到的 full.kind 在运行时必落在 Kind 内;这里窄化类型以匹配本页表单。
      const kind = full.kind as Kind
      setForm({
        provider_id: full.provider_id, label: full.label, kind,
        protocol: full.protocol, base_url: full.base_url || '', api_key: full.api_key || '',
        models: full.models.length ? full.models : [emptyModel(kind)],
        enabled: full.enabled,
        paths: full.paths || {}, response_map: full.response_map || {},
      })
      // 已有声明就展开:折叠着保存会把用户配好的路径连带清空
      setAccessOpen(Object.keys(full.paths || {}).length > 0
        || Object.keys(full.response_map || {}).length > 0)
      setModalOpen(true)
    } catch { Toast.error('读取失败') }
  }

  const onDelete = (p: ProviderInfo) => {
    Modal.confirm({
      title: '删除 Provider', content: `删除「${p.label}」(${p.provider_id})?其模型将从可选列表移除。`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try { await providersApi.delete(p.provider_id); Toast.success('已删除'); load() }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const setKind = (kind: Kind) => {
    const protocol = kind === 'llm'
      ? (protocols.llm[0] || 'openai-compat')
      : kind === 'video'
        ? (protocols.video[0] || 'seedance')
        : (protocols.image[0] || 'openai-image')
    // 切类型意味着换 protocol,旧 protocol 的功能键在新 protocol 下不合法(后端会拒),
    // 故一并清空,避免保存时才报错
    setForm(f => ({ ...f, kind, protocol, models: f.models.map(m => ({ ...m, kind })),
      paths: {}, response_map: {} }))
    formApiRef.current?.setValue('protocol', protocol)
  }

  const setPath = (op: string, value: string) =>
    setForm(f => ({ ...f, paths: { ...(f.paths || {}), [op]: value } }))
  const setRespField = (field: string, value: string) =>
    setForm(f => ({ ...f, response_map: { ...(f.response_map || {}), [field]: value } }))

  const updateModel = (i: number, patch: Partial<ProviderModel>) =>
    setForm(f => ({ ...f, models: f.models.map((m, idx) => idx === i ? { ...m, ...patch } : m) }))
  const updateCost = (i: number, patch: Partial<ModelCost>) =>
    setForm(f => ({
      ...f,
      models: f.models.map((m, idx) => {
        if (idx !== i) return m
        const next: ModelCost = { ...(m.cost || {}), ...patch }
        const priced = Object.values(next).some(v => typeof v === 'number')
        return { ...m, cost: priced ? next : null }
      }),
    }))
  const addModel = () => setForm(f => ({ ...f, models: [...f.models, emptyModel(f.kind as Kind)] }))
  const removeModel = (i: number) => setForm(f => ({ ...f, models: f.models.filter((_, idx) => idx !== i) }))
  const setDefaultModel = (i: number) =>
    setForm(f => ({ ...f, models: f.models.map((m, idx) => ({ ...m, is_default: idx === i })) }))
  const clearDefaultModel = (i: number) =>
    setForm(f => ({ ...f, models: f.models.map((m, idx) => idx === i ? { ...m, is_default: false } : m) }))

  /** 只提交真正填了值的项:空串会被后端当成非法路径拒掉,而"没填"应当表示走官方默认。 */
  const nonEmpty = (d?: Record<string, string>) =>
    Object.fromEntries(Object.entries(d || {}).filter(([, v]) => v.trim()))

  const save = async () => {
    const values = formApiRef.current?.getValues?.() as Partial<ProviderInput> | undefined
    const payload: ProviderInput = {
      // values 里的 paths/response_map 是 Form 的旧快照,必须由 form 覆盖回来
      ...form, ...(values || {}), models: form.models, enabled: form.enabled,
      // 开关关闭 = 走官方默认,提交空字典把库里旧声明清掉
      paths: accessOpen ? nonEmpty(form.paths) : {},
      response_map: accessOpen ? nonEmpty(form.response_map) : {},
    }
    if (!payload.provider_id?.trim()) { Toast.error('请输入 Provider ID'); return }
    if (payload.models.some(m => !m.id.trim() || !m.label.trim())) { Toast.error('每个模型需填 ID 和名称'); return }
    setSaving(true)
    try {
      if (editingId) await providersApi.update(editingId, payload)
      else await providersApi.create(payload)
      Toast.success(editingId ? '已更新' : '已新增')
      setModalOpen(false); load()
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      Toast.error('保存失败: ' + (err?.response?.data?.detail || '请检查输入'))
    } finally { setSaving(false) }
  }

  const protoOptions = form.kind === 'llm' ? protocols.llm : form.kind === 'video' ? protocols.video : protocols.image
  // 该 protocol 认的功能键与官方默认路径:词表来自后端,前端不另抄一份(规范 4)
  const ops = protocols.ops[form.protocol] || {}
  const respFields = protocols.response_fields || {}

  const accessSection = () => (
    <Space vertical align="start">
      <Text type="tertiary">
        网关把接口挂在非官方路径上时才需要填。留空走该协议官方路径。
      </Text>
      {Object.keys(ops).length === 0 ? (
        <Text type="tertiary">该协议暂不支持自定义路径</Text>
      ) : (
        <Row gutter={[16, 12]}>
          {Object.entries(ops).map(([op, def]) => (
            <Col xs={24} md={12} key={op}>
              <Space vertical align="start">
                <Text>{op}</Text>
                <Input
                  value={form.paths?.[op] || ''} placeholder={def}
                  onChange={v => setPath(op, v)}
                />
              </Space>
            </Col>
          ))}
        </Row>
      )}
      <Divider />
      <Text type="tertiary">
        响应结构与官方不同时填。只需填不一样的那几项,其余按协议官方位置解析。
      </Text>
      <Row gutter={[16, 12]}>
        {Object.entries(respFields).map(([field, desc]) => (
          <Col xs={24} md={12} key={field}>
            <Space vertical align="start">
              <Text>{field}</Text>
              <Input
                value={form.response_map?.[field] || ''} placeholder={desc}
                onChange={v => setRespField(field, v)}
              />
            </Space>
          </Col>
        ))}
      </Row>
    </Space>
  )
  const llmList = providers.filter(p => p.kind === 'llm')
  const videoList = providers.filter(p => p.kind === 'video')
  const imageList = providers.filter(p => p.kind === 'image')

  const renderItem = (p: ProviderInfo) => (
    <List.Item
      main={
        <Space wrap>
          <Text strong>{p.label}</Text>
          {p.models.length ? p.models.map(m => (
            <Space key={m.id} spacing="tight">
              <Text type="tertiary">{m.id}</Text>
              {m.is_default && <Tag color="green" shape="circle">默认</Tag>}
            </Space>
          )) : <Text type="tertiary">—</Text>}
        </Space>
      }
      extra={
        <Space>
          <Button onClick={() => openEdit(p)}>编辑</Button>
          {p.enabled === false && <Tag color="grey" shape="circle">未启用</Tag>}
          {p.builtin
            ? <Tag colorful gradient type="light" shape="circle">内置</Tag>
            : <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDelete(p)} />}
        </Space>
      }
    />
  )

  const renderGroup = (title: string, list: ProviderInfo[]) => (
    <Row gutter={[0, 8]}>
      <Col span={24}><Text type="tertiary" strong>{title}</Text></Col>
      <Col span={24}>
        <Card>
          <List dataSource={list} renderItem={renderItem} emptyContent={<Empty description="暂无" />} />
        </Card>
      </Col>
    </Row>
  )

  const costField = (m: ProviderModel, i: number, key: keyof ModelCost, label: string) => (
    <InputNumber
      value={m.cost?.[key] ?? ''}
      min={0}
      showClear
      insetLabel={label}
      placeholder="留空=未定价"
      onChange={v => updateCost(i, { [key]: v === '' || v === null ? undefined : Number(v) })}
    />
  )

  const modelRow = (m: ProviderModel, i: number) => (
    <Card>
      <Row gutter={[16, 12]} align="middle">
        <Col xs={20} md={11}>
          <Input value={m.id} onChange={v => updateModel(i, { id: v })} placeholder="模型 ID (如 qwen-max)" />
        </Col>
        <Col xs={24} md={11}>
          <Input value={m.label} onChange={v => updateModel(i, { label: v })} placeholder="显示名" />
        </Col>
        <Col xs={4} md={2}>
          <Button type="danger" theme="borderless" icon={<IconDelete />}
            onClick={() => removeModel(i)} disabled={form.models.length <= 1} />
        </Col>
        <Col span={24}>
          <Checkbox
            checked={!!m.is_default}
            onChange={e => (e.target.checked ? setDefaultModel(i) : clearDefaultModel(i))}
          >设为默认</Checkbox>
        </Col>
        {form.kind === 'llm' && (
          <Col span={24}>
            <Input type="number" value={m.context_window?.toString() || ''}
              onChange={v => updateModel(i, { context_window: v ? parseInt(v) : null })}
              placeholder="上下文窗口(token 数,可选)" />
          </Col>
        )}
        {form.kind === 'video' && (
          <>
            <Col xs={24} md={8}>
              <Input value={(m.resolutions || []).join(',')}
                onChange={v => updateModel(i, { resolutions: v.split(',').map(s => s.trim()).filter(Boolean) })}
                placeholder="分辨率,逗号分隔 (768P,2K)" />
            </Col>
            <Col xs={24} md={8}>
              <Input value={m.default_resolution || ''}
                onChange={v => updateModel(i, { default_resolution: v || null })}
                placeholder="默认分辨率" />
            </Col>
            <Col xs={24} md={8}>
              <Select multiple value={m.supported_actions || []}
                onChange={v => updateModel(i, { supported_actions: v as string[] })} placeholder="支持动作">
                <Select.Option value="rerun">rerun</Select.Option>
                <Select.Option value="regenerate">regenerate</Select.Option>
                <Select.Option value="upscale">upscale</Select.Option>
              </Select>
            </Col>
          </>
        )}
        <Col span={24}>
          <Text type="tertiary" size="small">预估单价(人民币 ¥,用于成本统计;留空=未定价)</Text>
        </Col>
        {form.kind === 'llm' && (
          <>
            <Col xs={24} md={12}>{costField(m, i, 'input', '输入 ¥/百万token')}</Col>
            <Col xs={24} md={12}>{costField(m, i, 'output', '输出 ¥/百万token')}</Col>
          </>
        )}
        {form.kind === 'video' && (
          <Col xs={24} md={12}>{costField(m, i, 'per_second', '视频 ¥/秒')}</Col>
        )}
        <Col xs={24} md={12}>{costField(m, i, 'per_call', '每次调用 ¥/次')}</Col>
      </Row>
    </Card>
  )

  return (
    <PageShell
      title="模型管理"
      description="内置模型可改凭证/模型(不可删);可新增自定义文本 / 视频 / 图片 Provider"
      headerExtra={<Button colorful theme="solid" icon={<IconPlus />} type="primary" onClick={openCreate}>新增 Provider</Button>}
    >
      <Divider />

      {loading ? (
        <PageLoading />
      ) : (
        <Row gutter={[0, 24]}>
          <Col span={24}>{renderGroup('文本模型 (LLM)', llmList)}</Col>
          <Col span={24}>{renderGroup('视频模型 (Video)', videoList)}</Col>
          <Col span={24}>{renderGroup('图片模型 (Image)', imageList)}</Col>
        </Row>
      )}

      <Modal
        title={editingId ? '编辑 Provider' : '新增 Provider'}
        visible={modalOpen} onCancel={() => setModalOpen(false)} onOk={save}
        okText="保存" cancelText="取消" confirmLoading={saving} width={640}
      >
        <Form<ProviderInput>
          key={editingId ?? 'create'}
          getFormApi={api => (formApiRef.current = api)}
          initValues={form}
          labelPosition="top"
          // models / paths / response_map 由 Form 之外的受控组件维护:Form 持有的是
          // initValues 那一刻的旧值,不排除就会在任意字段变更时把它们覆盖回旧值
          onValueChange={values => setForm(f => ({
            ...f, ...values, models: f.models,
            paths: f.paths, response_map: f.response_map,
          }))}
        >
          <Row gutter={[16, 0]}>
            <Col xs={24} md={12}>
              <Form.Input
                field="provider_id" label="Provider ID" placeholder="如 mycorp" disabled={!!editingId}
                rules={[{ required: true, message: '请输入 Provider ID' }]}
              />
            </Col>
            <Col xs={24} md={12}>
              <Form.Input
                field="label" label="名称" placeholder="如 私有部署"
                rules={[{ required: true, message: '请输入名称' }]}
              />
            </Col>
            <Col xs={24} md={12}>
              <Form.Select field="kind" label="类型" disabled={!!editingId} onChange={v => setKind(v as Kind)}>
                <Form.Select.Option value="llm">文本 (LLM)</Form.Select.Option>
                <Form.Select.Option value="video">视频 (Video)</Form.Select.Option>
                <Form.Select.Option value="image">图片 (Image)</Form.Select.Option>
              </Form.Select>
            </Col>
            <Col xs={24} md={12}>
              <Form.Select field="protocol" label="协议 Protocol">
                {protoOptions.map(pr => <Form.Select.Option key={pr} value={pr}>{pr}</Form.Select.Option>)}
              </Form.Select>
            </Col>
            <Col span={24}>
              <Form.Input
                field="base_url" label="Base URL"
                placeholder="https://llm.mycorp.com/v1"
                disabled={editingBuiltin}
                extraText={editingBuiltin ? '内置模型地址为官方地址,不可修改;只需填写 API Key' : undefined}
              />
            </Col>
            <Col span={24}>
              <Form.Input field="api_key" label="API Key(明文存储)" mode="password" placeholder="sk-..." />
            </Col>
            <Col span={24}>
              <Form.Switch field="enabled" label="启用" />
            </Col>
          </Row>
          <Row gutter={[0, 12]}>
            <Col span={24}>
              <Checkbox checked={accessOpen} onChange={e => setAccessOpen(!!e.target.checked)}>
                自定义接入路径
              </Checkbox>
            </Col>
            {accessOpen && <Col span={24}>{accessSection()}</Col>}
          </Row>
          <Row gutter={[0, 12]}>
            <Col span={24}>
              <Space align="center">
                <Text strong>模型列表</Text>
                <Button icon={<IconPlus />} onClick={addModel}>加一个模型</Button>
              </Space>
            </Col>
            {form.models.map((m, i) => (
              <Col span={24} key={i}>{modelRow(m, i)}</Col>
            ))}
          </Row>
        </Form>
      </Modal>
    </PageShell>
  )
}
