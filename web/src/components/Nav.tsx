import { Link, useRouterState } from "@tanstack/react-router";

const links: [string, string][] = [
  ["/", "Dashboard"],
  ["/incidents", "Incidents"],
  ["/ask", "Ask"],
];

export function Nav() {
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <header className="hairline-b">
      <div className="max-w-[1440px] mx-auto px-6 lg:px-10 h-16 flex items-center gap-8">
        <Link to="/" className="font-display text-2xl tracking-wide leading-none">
          MARCONI
        </Link>
        <nav className="flex items-center gap-6">
          {links.map(([to, label]) => {
            const active = path === to;
            return (
              <Link
                key={to}
                to={to}
                className={
                  "text-[15px] font-medium pb-1 " +
                  (active
                    ? "text-ink border-b-2 border-ink"
                    : "text-mute hover:text-ink")
                }
              >
                {label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
