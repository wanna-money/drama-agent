import { useEffect, useRef, useState } from 'react'
import { Table, Button, Tag, Modal, Toast, Typography, Form } from '@douyinfe/semi-ui'
import type { FormApi } from '@douyinfe/semi-ui/lib/es/form/interface'
import { IconPlus, IconDelete } from '@douyinfe/semi-icons'
import PageShell, { PageEmpty, PageLoading } from '../components/PageShell'
import {
  providersApi, ProviderInfo, ProviderInput, ProtocolCatalog, StorageProviderConfig,
} from '../services/api'

const { Text } = Typography

/** 存储表单字段。与 ProviderInput 分开维护:storage 没有 models/base_url,
 *  凑进 ProviderInput 的字段会挤出一堆与本页无关的空值。 */
interface StorageFormValues {
  provider_id: string
  label: string
  protocol: string
  api_key?: string
  bucket?: string
  region?: string
  secret_id?: string
  prefix?: string
  expires_days?: string
  enabled: boolean
}

const emptyCatalog: ProtocolCatalog = {
  llm: [], video: [], image: [], storage: [], ops: {}, response_fields: {},
}

const blankForm = (protocol: string): StorageFormValues => ({
  provider_id: '', label: '', protocol, api_key: '',
  bucket: '', region: '', secret_id: '', prefix: '', expires_days: '',
  enabled: true,
})

export default function StoragePage() {
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [protocols, setProtocols] = useState<ProtocolCatalog>(emptyCatalog)
  const [loading, setLoading] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<StorageFormValues>(blankForm(''))
  const formApiRef = useRef<FormApi<StorageFormValues> | null>(null)

  const load = () => {
    setLoading(true)
    Promise.all([providersApi.list(), providersApi.protocols()])
      .then(([ps, protos]) => { setProviders(ps); setProtocols(protos) })
      .catch(() => Toast.error('加载失败'))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const storageList = providers.filter(p => p.kind === 'storage')

  const openCreate = () => {
    setEditingId(null)
    setForm(blankForm(protocols.storage[0] || 'cos'))
    setModalOpen(true)
  }

  const openEdit = async (p: ProviderInfo) => {
    try {
      const full = await providersApi.get(p.provider_id)
      const config: StorageProviderConfig = full.config || {}
      setEditingId(p.provider_id)
      setForm({
        provider_id: full.provider_id, label: full.label, protocol: full.protocol,
        api_key: full.api_key || '', enabled: full.enabled,
        bucket: config.bucket || '', region: config.region || '',
        secret_id: config.secret_id || '', prefix: config.prefix || '',
        expires_days: config.expires_days || '',
      })
      setModalOpen(true)
    } catch { Toast.error('读取失败') }
  }

  const onDelete = (p: ProviderInfo) => {
    Modal.confirm({
      title: '删除存储配置', content: `删除「${p.label}」(${p.provider_id})?依赖它取参考素材的视频模型将无法访问。`,
      okType: 'danger', okText: '删除', cancelText: '取消',
      onOk: async () => {
        try { await providersApi.delete(p.provider_id); Toast.success('已删除'); load() }
        catch { Toast.error('删除失败') }
      },
    })
  }

  const save = async () => {
    let values: Partial<StorageFormValues> | undefined
    try {
      values = await formApiRef.current?.validate?.() as Partial<StorageFormValues> | undefined
    } catch {
      return  // 必填项为空:Semi 已在字段旁标红,不重复提交
    }
    const merged: StorageFormValues = { ...form, ...(values || {}) }
    const payload: ProviderInput = {
      provider_id: merged.provider_id, label: merged.label,
      kind: 'storage', protocol: merged.protocol,
      api_key: merged.api_key, enabled: merged.enabled,
      models: [], paths: {}, response_map: {},
      config: {
        bucket: merged.bucket, region: merged.region, secret_id: merged.secret_id,
        prefix: merged.prefix, expires_days: merged.expires_days,
      },
    }
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

  const columns = [
    { title: '名称', dataIndex: 'label' },
    { title: '后端', dataIndex: 'protocol' },
    {
      title: '桶', dataIndex: 'config',
      render: (v: StorageProviderConfig | undefined) => v?.bucket || <Text type="tertiary">—</Text>,
    },
    {
      title: '地域', dataIndex: 'config',
      render: (v: StorageProviderConfig | undefined) => v?.region || <Text type="tertiary">—</Text>,
    },
    {
      title: '凭证', dataIndex: 'api_key',
      render: (v: string | null | undefined) => v || <Text type="tertiary">—</Text>,
    },
    {
      title: '启用', dataIndex: 'enabled',
      render: (v: boolean) => v ? <Tag color="green">已启用</Tag> : <Tag color="grey">未启用</Tag>,
    },
    {
      title: '操作',
      render: (_: unknown, r: ProviderInfo) => (
        <>
          <Button onClick={() => openEdit(r)}>编辑</Button>
          <Button type="danger" theme="borderless" icon={<IconDelete />} onClick={() => onDelete(r)} />
        </>
      ),
    },
  ]

  return (
    <PageShell
      title="存储管理"
      description="让外部视频模型能取到参考素材"
      headerExtra={<Button colorful theme="solid" icon={<IconPlus />} type="primary" onClick={openCreate}>新建</Button>}
    >
      {loading ? (
        <PageLoading />
      ) : storageList.length === 0 ? (
        <PageEmpty description="还没有配置存储" />
      ) : (
        <Table columns={columns} dataSource={storageList} rowKey="provider_id" pagination={false} />
      )}

      <Modal
        title={editingId ? '编辑存储配置' : '新建存储配置'}
        visible={modalOpen} onCancel={() => setModalOpen(false)} onOk={save}
        okText="保存" cancelText="取消" confirmLoading={saving}
      >
        <Form<StorageFormValues>
          key={editingId ?? 'create'}
          getFormApi={api => (formApiRef.current = api)}
          initValues={form}
          labelPosition="top"
        >
          <Form.Input
            field="provider_id" label="Provider ID" placeholder="如 cos" disabled={!!editingId}
            rules={[{ required: true, message: '请输入 Provider ID' }]}
            data-testid="field-provider_id"
          />
          <Form.Input
            field="label" label="名称" placeholder="如 腾讯云 COS"
            rules={[{ required: true, message: '请输入名称' }]}
            data-testid="field-label"
          />
          <Form.Select field="protocol" label="后端 Protocol">
            {protocols.storage.map(pr => <Form.Select.Option key={pr} value={pr}>{pr}</Form.Select.Option>)}
          </Form.Select>
          <Form.Input
            field="bucket" label="Bucket"
            rules={[{ required: true, message: '请输入 Bucket' }]}
            data-testid="field-bucket"
          />
          <Form.Input
            field="region" label="Region"
            rules={[{ required: true, message: '请输入 Region' }]}
            data-testid="field-region"
          />
          <Form.Input
            field="secret_id" label="SecretId"
            rules={[{ required: true, message: '请输入 SecretId' }]}
            data-testid="field-secret_id"
          />
          <Form.Input
            field="api_key" label="SecretKey(明文存储)" mode="password"
            rules={[{ required: true, message: '请输入 SecretKey' }]}
            data-testid="field-api_key"
          />
          <Form.Input field="prefix" label="路径前缀(可选)" data-testid="field-prefix" />
          <Form.InputNumber field="expires_days" label="链接有效期(天,可选)" data-testid="field-expires_days" />
          <Form.Switch field="enabled" label="启用" />
        </Form>
      </Modal>
    </PageShell>
  )
}
