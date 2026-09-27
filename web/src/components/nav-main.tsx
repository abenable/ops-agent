import { Link } from '@tanstack/react-router'
import { ChevronRightIcon, ClipboardListIcon, HistoryIcon, MessageSquarePlusIcon } from 'lucide-react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
} from '@/components/ui/sidebar'

const SOURCES = [
  { title: 'All', source: 'all' },
  { title: 'Web', source: 'web' },
  { title: 'Discord', source: 'discord' },
  { title: 'API & eval', source: 'other' },
] as const

export function NavMain() {
  return (
    <SidebarGroup>
      <SidebarGroupLabel>Agent</SidebarGroupLabel>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton asChild tooltip="New conversation">
            <Link to="/">
              <MessageSquarePlusIcon />
              <span>New conversation</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <Collapsible asChild defaultOpen className="group/collapsible">
          <SidebarMenuItem>
            <SidebarMenuButton asChild tooltip="History">
              <Link to="/conversations" activeOptions={{ includeSearch: false }} activeProps={{ 'data-active': true }}>
                <HistoryIcon />
                <span>History</span>
              </Link>
            </SidebarMenuButton>
            <CollapsibleTrigger asChild>
              <SidebarMenuAction>
                <ChevronRightIcon className="transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
                <span className="sr-only">Toggle sources</span>
              </SidebarMenuAction>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <SidebarMenuSub>
                {SOURCES.map((item) => (
                  <SidebarMenuSubItem key={item.source}>
                    <SidebarMenuSubButton asChild>
                      <Link to="/conversations" search={{ source: item.source }} activeProps={{ 'data-active': true }}>
                        <span>{item.title}</span>
                      </Link>
                    </SidebarMenuSubButton>
                  </SidebarMenuSubItem>
                ))}
              </SidebarMenuSub>
            </CollapsibleContent>
          </SidebarMenuItem>
        </Collapsible>
        <SidebarMenuItem>
          <SidebarMenuButton asChild tooltip="Reports">
            <Link to="/reports" activeOptions={{ includeSearch: false }} activeProps={{ 'data-active': true }}>
              <ClipboardListIcon />
              <span>Reports</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarGroup>
  )
}
