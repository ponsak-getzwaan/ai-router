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
      <aside className="flex w-56 shrink-0 flex-col bg-primary">
        <div className="border-b border-primary-foreground/20 px-4 py-5">
          <p className="text-lg font-semibold text-primary-foreground">
            Evidor<span className="font-normal opacity-60">.ai</span>
          </p>
          <p className="text-xs text-primary-foreground/60">Admin</p>
        </div>
        <nav className="flex-1 overflow-y-auto p-2" aria-label="Main navigation">
          <ul className="space-y-0.5">
            {NAV_ITEMS.map(({ to, label }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "block rounded-full px-3 py-2 text-sm transition-colors",
                      isActive
                        ? "bg-primary-foreground/15 text-primary-foreground font-medium"
                        : "text-primary-foreground/60 hover:bg-primary-foreground/10 hover:text-primary-foreground"
                    )
                  }
                >
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <div className="border-t border-primary-foreground/20 p-3">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start text-primary-foreground/60 hover:bg-primary-foreground/10 hover:text-primary-foreground"
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
