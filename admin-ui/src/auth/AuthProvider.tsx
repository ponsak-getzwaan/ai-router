import { type ReactNode, useEffect } from "react";
import { useAuthStore } from "./store";
import { redirectToLogin } from "./cognito";

interface Props {
  children: ReactNode;
}

export function AuthProvider({ children }: Props) {
  const tokens = useAuthStore((s) => s.tokens);

  useEffect(() => {
    if (!tokens) {
      // Not on the callback page — redirect to Cognito
      if (!window.location.pathname.startsWith("/auth/callback")) {
        redirectToLogin().catch(() => undefined);
      }
    }
  }, [tokens]);

  return <>{children}</>;
}
