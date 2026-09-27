import { createRouter } from '@tanstack/react-router'
import { ErrorState, NotFoundState } from './components/states'
import { routeTree } from './routeTree.gen'

export function getRouter() {
  return createRouter({
    routeTree,
    scrollRestoration: true,
    defaultPreload: 'intent',
    defaultErrorComponent: ErrorState,
    defaultNotFoundComponent: NotFoundState,
  })
}

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof getRouter>
  }
}
