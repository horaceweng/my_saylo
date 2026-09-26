import { describe, expect, it } from 'vitest'
import type { CloudPreset } from '../api/types'
import { presetFor } from './CloudSettings'

const presets: CloudPreset[] = [
  { id: 'gemini', label: 'Gemini', base_url: 'https://g.example/openai/', model: 'm', note: '' },
  { id: 'custom', label: 'Other', base_url: '', model: '', note: '' },
]

describe('presetFor', () => {
  it('recognises a saved address as one of the presets', () => expect(presetFor(presets, 'https://g.example/openai/')).toBe('gemini'))
  it('otherwise, or when nothing is saved yet, it is custom', () => {
    expect(presetFor(presets, 'https://elsewhere.example')).toBe('custom')
    expect(presetFor(presets, '')).toBe('custom')
  })
})
