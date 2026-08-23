import { useState } from 'react'
import { Button, Select, InputNumber, Input, Toast } from '@douyinfe/semi-ui'
import { filesApi, ParamField } from '../services/api'

interface Props {
  schema: ParamField[]
  onSubmit: (values: Record<string, unknown>) => void
  submitting?: boolean
  projectId?: string
}

export default function ActionParamForm({ schema, onSubmit, submitting, projectId }: Props) {
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const init: Record<string, unknown> = {}
    for (const f of schema) if (f.default !== undefined) init[f.name] = f.default
    return init
  })

  const setField = (name: string, v: unknown) => setValues(prev => ({ ...prev, [name]: v }))

  const handleUpload = async (name: string, file: File) => {
    if (!projectId) return
    try {
      const res = await filesApi.uploadImage(projectId, file)
      setField(name, res.url)
    } catch {
      Toast.error('上传失败')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {schema.map(f => (
        <div key={f.name}>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>{f.label}</label>
          {f.type === 'enum' && (
            <Select style={{ width: '100%' }} value={values[f.name] as string}
              onChange={v => setField(f.name, v as string)}>
              {(f.options ?? []).map(o => <Select.Option key={o} value={o}>{o}</Select.Option>)}
            </Select>
          )}
          {f.type === 'int' && (
            <InputNumber style={{ width: '100%' }} min={f.min} max={f.max}
              value={values[f.name] as number} onChange={v => setField(f.name, v)} />
          )}
          {f.type === 'text' && (
            <Input value={values[f.name] as string} onChange={v => setField(f.name, v)} />
          )}
          {(f.type === 'file' || f.type === 'audio') && (
            <input type="file" onChange={e => e.target.files?.[0] && handleUpload(f.name, e.target.files[0])} />
          )}
        </div>
      ))}
      <Button type="primary" loading={submitting} onClick={() => onSubmit(values)}>确定</Button>
    </div>
  )
}
