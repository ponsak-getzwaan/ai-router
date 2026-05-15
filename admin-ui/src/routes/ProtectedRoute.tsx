import type { ReactNode } from "react";
import { useEffect } from "react";
import { useAuthStore } from "../auth/store";
import { redirectToLogin } from "../auth/cognito";
import { Spinner } from "../components/Spinner";

interface Props {
  children: ReactNode;
}

export function ProtectedRoute({ children }: Props) {
  const tokens = useAuthStore((s) => s.tokens);

  useEffect(() => {
    if (!tokens) {
      redirectToLogin().catch(() => undefined);
    }
  }, [tokens]);

  if (!tokens) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
        <span className="ml-3 text-muted-foreground">Redirecting to login…</span>
      </div>
    );
  }

  return <>{children}</>;
}
