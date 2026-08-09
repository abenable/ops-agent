import { createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { AppShell } from "./components/AppShell";
import { Dashboard } from "./routes/Dashboard";
import { ServiceDetail } from "./routes/ServiceDetail";
import { Incidents } from "./routes/Incidents";
import { Tasks } from "./routes/Tasks";
import { Chat } from "./routes/Chat";
import { Activity } from "./routes/Activity";

const root = createRootRoute({
  component: () => <AppShell />,
});

const index = createRoute({ getParentRoute: () => root, path: "/", component: Dashboard });
const service = createRoute({
  getParentRoute: () => root,
  path: "/services/$name",
  component: ServiceDetail,
});
const incidents = createRoute({ getParentRoute: () => root, path: "/incidents", component: Incidents });
const tasks = createRoute({ getParentRoute: () => root, path: "/tasks", component: Tasks });
const chat = createRoute({ getParentRoute: () => root, path: "/chat", component: Chat });
const activity = createRoute({ getParentRoute: () => root, path: "/activity", component: Activity });

export const router = createRouter({
  routeTree: root.addChildren([index, service, incidents, tasks, chat, activity]),
  defaultPreload: "intent",
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
