import { HeadContent, Outlet, Scripts, createRootRoute } from '@tanstack/react-router'
import type { ReactNode } from 'react'
import { AppSidebar } from '@/components/app-sidebar'
import { ErrorState, NotFoundState } from '@/components/states'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import { TooltipProvider } from '@/components/ui/tooltip'
import { listThreads, sidebarOpen } from '@/server/functions'
import appCss from '../styles/app.css?url'

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { name: 'color-scheme', content: 'dark' },
      { title: 'Oracle · Marconi Lab' },
    ],
    links: [
      { rel: 'stylesheet', href: appCss },
      { rel: 'icon', type: 'image/png', href: '/favicon.png' },
    ],
  }),
  // Streamed: the page shell renders first and the sidebar's recent list fills in when it settles.
  loader: () => ({
    sidebarOpen: sidebarOpen(),
    recent: listThreads({ data: { source: 'web', perPage: 20 } }).catch(() => null),
  }),
  staleTime: 5 * 60_000,
  shellComponent: RootDocument,
  component: RootLayout,
  errorComponent: ErrorState,
  notFoundComponent: NotFoundState,
})

function RootDocument({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  )
}

function RootLayout() {
  const { sidebarOpen } = Route.useLoaderData()
  return (
    <TooltipProvider>
      <SidebarProvider defaultOpen={sidebarOpen}>
        <AppSidebar />
        <SidebarInset>
          <Outlet />
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
