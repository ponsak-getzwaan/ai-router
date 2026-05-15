import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuthStore } from "../auth/store";
import { Button } from "./ui/button";
import { cn } from "../lib/utils";

const NAV_ITEMS = [
  { to: "/admin/health", label: "Pipeline Health" },
  { to: "/admin/escalations", label: "Escalations" },
  { to: "/admin/bouncer", label: "Bouncer" },
  { to: "/admin/classifier", label: "Classifier" },
  { to: "/admin/strategist", label: "Strategist" },
  { to: "/admin/routing-rules", label: "Routing Rules" },
  { to: "/admin/audit", label: "Audit Log" },
  { to: "/admin/test-console", label: "Test Console" },
];

interface Props {
  children: ReactNode;
}

export function Layout({ children }: Props) {
  const logout = useAuthStore((s) => s.logout);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-56 shrink-0 flex-col border-r bg-card">
        <div className="border-b px-4 py-4">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            AI Router
          </p>
          <p className="text-sm font-medium">Admin</p>
        </div>
        <nav className="flex-1 overflow-y-auto p-2" aria-label="Main navigation">
          <ul className="space-y-0.5">
            {NAV_ITEMS.map(({ to, label }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "block rounded-md px-3 py-2 text-sm transition-colors",
                      isActive
                        ? "bg-accent text-accent-foreground font-medium"
                        : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                    )
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="border-t p-3">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-muted-foreground"
            onClick={logout}
          >
            Sign out
          </Button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-7xl p-6">{children}</div>
      </main>
    </div>
  );
}
