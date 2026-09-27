import { Link } from '@tanstack/react-router'
import type * as React from 'react'
import { NavMain } from '@/components/nav-main'
import { NavRecent } from '@/components/nav-recent'
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from '@/components/ui/sidebar'

export function AppSidebar(props: React.ComponentProps<typeof Sidebar>) {
  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="Marconi Lab · Oracle">
              <Link to="/">
                <img src="/marconi-mark.png" alt="" className="size-8 shrink-0 object-contain" />
                <img src="/marconi-wordmark.png" alt="Marconi Lab @MAK" className="h-8 w-auto" />
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain />
        <NavRecent />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
