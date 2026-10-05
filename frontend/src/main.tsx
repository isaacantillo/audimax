import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createRouter } from '@tanstack/react-router'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { client } from './client/client.gen'
import { routeTree } from './routeTree.gen'
import './index.css'

// Same-origin in both setups: Vite proxies /api in dev, FastAPI serves both in prod.
client.setConfig({ baseUrl: '', credentials: 'include' })
// An expired session on any call sends the user to the login page.
client.interceptors.response.use((response) => {
  if (response.status === 401 && !window.location.pathname.startsWith('/login')) {
    window.location.assign('/login')
  }
  return response
})

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})
const router = createRouter({ routeTree, context: { queryClient }, defaultPreload: 'intent' })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
