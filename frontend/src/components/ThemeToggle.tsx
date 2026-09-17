import { useEffect, useState } from 'react'
import { Button } from '@douyinfe/semi-ui'
import { IconSun, IconMoon } from '@douyinfe/semi-icons'

type ThemeMode = 'dark' | 'light'

const STORAGE_KEY = 'drama-agent-theme'

function applyTheme(mode: ThemeMode) {
  if (mode === 'dark') document.body.setAttribute('theme-mode', 'dark')
  else document.body.removeAttribute('theme-mode')
}

/** 深浅主题切换。默认深色(与 index.html 的 body[theme-mode="dark"] 初值一致),
 *  首次访问无 localStorage 记录时不跟随系统色彩方案。 */
export default function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>('dark')

  useEffect(() => {
    const saved = (localStorage.getItem(STORAGE_KEY) as ThemeMode | null) ?? 'dark'
    setMode(saved)
    applyTheme(saved)
  }, [])

  const toggle = () => {
    const next: ThemeMode = mode === 'dark' ? 'light' : 'dark'
    setMode(next)
    applyTheme(next)
    localStorage.setItem(STORAGE_KEY, next)
  }

  return (
    <Button
      theme="borderless"
      type="tertiary"
      icon={mode === 'dark' ? <IconMoon /> : <IconSun />}
      onClick={toggle}
      aria-label="切换深浅色主题"
    />
  )
}
