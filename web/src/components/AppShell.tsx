import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  ActivityIcon,
  AlertTriangleIcon,
  BoxesIcon,
  BotIcon,
  FlaskConicalIcon,
  MessagesSquareIcon,
  RadioIcon,
  ShieldCheckIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarSeparator,
  SidebarTrigger,
} from "@/components/ui/sidebar";

const NAV = [
  {
    group: "Overview",
    items: [
      { to: "/", label: "Dashboard", icon: BoxesIcon },
      { to: "/incidents", label: "Incidents", icon: AlertTriangleIcon },
      { to: "/tasks", label: "Tasks", icon: FlaskConicalIcon },
      { to: "/chat", label: "Chat", icon: MessagesSquareIcon },
      { to: "/activity", label: "Activity", icon: ActivityIcon },
    ],
  },
] as const;

export function AppShell() {
  const path = useRouterState({ select: (s) => s.location.pathname });

  return (
    <SidebarProvider>
      <Sidebar collapsible="icon">
        <SidebarHeader>
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton size="lg" render={<Link to="/" />}>
                <div className="flex aspect-square size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                  <RadioIcon />
                </div>
                <div className="grid flex-1 text-left text-sm leading-tight">
                  <span className="truncate font-semibold">Marconi Ops</span>
                  <span className="truncate text-xs">Operations Agent</span>
                </div>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarHeader>
        <SidebarContent>
          {NAV.map((section) => (
            <SidebarGroup key={section.group}>
              <SidebarGroupLabel>{section.group}</SidebarGroupLabel>
              <SidebarGroupContent>
                <SidebarMenu>
                  {section.items.map((item) => (
                    <SidebarMenuItem key={item.to}>
                      <SidebarMenuButton
                        isActive={path === item.to}
                        render={<Link to={item.to} />}
                      >
                        <item.icon />
                        <span>{item.label}</span>
                      </SidebarMenuButton>
                    </SidebarMenuItem>
                  ))}
                </SidebarMenu>
              </SidebarGroupContent>
            </SidebarGroup>
          ))}
        </SidebarContent>
        <SidebarFooter>
          <SidebarSeparator />
          <SidebarMenu>
            <SidebarMenuItem>
              <SidebarMenuButton render={<Link to="/" />}>
                <ShieldCheckIcon />
                <span>Agent healthy</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarFooter>
        <SidebarRail />
      </Sidebar>
      <SidebarInset>
        <header className="flex h-12 shrink-0 items-center gap-2 px-4">
          <SidebarTrigger />
          <Badge variant="outline" className="gap-1.5">
            <span className="size-1.5 rounded-full bg-success" />
            Live
          </Badge>
          <Badge variant="outline">
            <BotIcon />
            v0.1.0
          </Badge>
          <span className="ml-auto flex items-center gap-1.5 text-xs text-muted-foreground">
            <ActivityIcon className="size-3.5" />
            Polling services every 10s
          </span>
        </header>
        <div className="flex flex-1 flex-col gap-4 p-4 pt-0">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
