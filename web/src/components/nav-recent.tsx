import { Await, Link, getRouteApi } from '@tanstack/react-router'
import { CopyIcon, FileTextIcon, MessagesSquareIcon, MoreHorizontalIcon } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSkeleton,
  useSidebar,
} from '@/components/ui/sidebar'

const root = getRouteApi('__root__')

export function NavRecent() {
  const { recent } = root.useLoaderData()
  const { isMobile } = useSidebar()
  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Recent</SidebarGroupLabel>
      <SidebarMenu>
        <Await
          promise={recent}
          fallback={Array.from({ length: 5 }, (_, i) => (
            <SidebarMenuItem key={i}>
              <SidebarMenuSkeleton />
            </SidebarMenuItem>
          ))}
        >
          {(page) =>
            !page ? (
              <p className="px-2 text-sm text-muted-foreground">Couldn't load conversations.</p>
            ) : page.threads.length === 0 ? (
              <p className="px-2 text-sm text-muted-foreground">No web conversations yet.</p>
            ) : (
              <>
                {page.threads.map((thread) => (
                  <SidebarMenuItem key={thread.thread_id}>
                    <SidebarMenuButton asChild>
                      <Link to="/c/$threadId" params={{ threadId: thread.thread_id }} activeProps={{ 'data-active': true }}>
                        <MessagesSquareIcon />
                        <span>{thread.title || 'Untitled'}</span>
                      </Link>
                    </SidebarMenuButton>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <SidebarMenuAction showOnHover className="aria-expanded:bg-muted">
                          <MoreHorizontalIcon />
                          <span className="sr-only">More</span>
                        </SidebarMenuAction>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent className="w-fit" side={isMobile ? 'bottom' : 'right'} align={isMobile ? 'end' : 'start'}>
                        <DropdownMenuGroup>
                          <DropdownMenuItem asChild>
                            <Link to="/c/$threadId" params={{ threadId: thread.thread_id }}>
                              <MessagesSquareIcon />
                              <span>Open chat</span>
                            </Link>
                          </DropdownMenuItem>
                          <DropdownMenuItem asChild>
                            <Link to="/transcripts/$threadId" params={{ threadId: thread.thread_id }}>
                              <FileTextIcon />
                              <span>View transcript</span>
                            </Link>
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                          <DropdownMenuItem onSelect={() => navigator.clipboard.writeText(thread.thread_id)}>
                            <CopyIcon />
                            <span>Copy thread id</span>
                          </DropdownMenuItem>
                        </DropdownMenuGroup>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </SidebarMenuItem>
                ))}
                <SidebarMenuItem>
                  <SidebarMenuButton asChild className="text-sidebar-foreground/70">
                    <Link to="/conversations">
                      <MoreHorizontalIcon className="text-sidebar-foreground/70" />
                      <span>View all</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              </>
            )
          }
        </Await>
      </SidebarMenu>
    </SidebarGroup>
  )
}
