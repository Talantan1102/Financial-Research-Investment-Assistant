import { ConfigProvider } from 'antd'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import type { ReactElement, ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

interface ProvidersOptions {
  initialRoute?: string
}

export function renderWithProviders(
  ui: ReactElement,
  options: ProvidersOptions & Omit<RenderOptions, 'wrapper'> = {},
): RenderResult {
  const { initialRoute = '/', ...rest } = options

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ConfigProvider>
        <MemoryRouter initialEntries={[initialRoute]}>{children}</MemoryRouter>
      </ConfigProvider>
    )
  }

  return render(ui, { wrapper: Wrapper, ...rest })
}
