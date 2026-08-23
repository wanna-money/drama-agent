import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import '../test/mocks'
import ActionParamForm from '../components/ActionParamForm'
import type { ParamField } from '../services/api'

describe('ActionParamForm', () => {
  it('submits empty object when schema is empty', () => {
    const onSubmit = vi.fn()
    render(<ActionParamForm schema={[]} onSubmit={onSubmit} />)
    fireEvent.click(screen.getByText('确定'))
    expect(onSubmit).toHaveBeenCalledWith({})
  })

  it('submits default values from schema', () => {
    const onSubmit = vi.fn()
    const schema: ParamField[] = [
      { name: 'resolution', type: 'enum', label: '分辨率', options: ['768P', '2K'], default: '768P' },
      { name: 'duration', type: 'int', label: '时长', min: 4, max: 15, default: 5 },
      { name: 'prompt', type: 'text', label: 'Prompt', default: 'hero' },
    ]
    render(<ActionParamForm schema={schema} onSubmit={onSubmit} />)
    fireEvent.click(screen.getByText('确定'))
    expect(onSubmit).toHaveBeenCalledWith({ resolution: '768P', duration: 5, prompt: 'hero' })
  })
})
