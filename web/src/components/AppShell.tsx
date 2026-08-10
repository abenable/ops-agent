import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  ActivityIcon,
  AlertTriangleIcon,
  BoxesIcon,
  BotIcon,
  FlaskConicalIcon,
  MessagesSquareIcon,
  RadioIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
  ShieldQuestionIcon,
} from "lucide-react";

import { api } from "@/api";
import { cn } from "@/lib/utils";
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
  // Cheap reachability ping (no Docker dependency) so "Live"/"Agent healthy"
  // reflect the actual API process instead of being permanently hardcoded.
  const ping = useQuery({
    queryKey: ["ping"],
    queryFn: api.watched,
    refetchInterval: 15_000,
    retry: 1,
  });
  const online = ping.isSuccess;
  const checking = ping.isLoading;

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
                {online ? (
                  <ShieldCheckIcon />
                ) : checking ? (
                  <ShieldQuestionIcon />
                ) : (
                  <ShieldAlertIcon />
                )}
                <span>{online ? "Agent healthy" : checking ? "Checking agent…" : "Agent unreachable"}</span>
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
            <span
              className={cn(
                "size-1.5 rounded-full",
                online ? "bg-success" : checking ? "bg-muted-foreground" : "bg-destructive",
              )}
            />
            {online ? "Live" : checking ? "Checking…" : "Unreachable"}
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
