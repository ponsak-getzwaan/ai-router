import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { exchangeCode } from "../auth/cognito";
import { useAuthStore } from "../auth/store";
import { Spinner } from "../components/Spinner";

export function AuthCallback() {
  const navigate = useNavigate();
  const setTokens = useAuthStore((s) => s.setTokens);
  const exchanged = useRef(false);

  useEffect(() => {
    // Prevent double-execution in React StrictMode
    if (exchanged.current) return;
    exchanged.current = true;

    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    const error = params.get("error");

    if (error || !code || !state) {
      navigate("/auth/error", {
        replace: true,
        state: { message: error ?? "Missing code or state" },
      });
      return;
    }

    exchangeCode(code!, state!)
      .then((tokens) => {
        setTokens(tokens);
        navigate("/admin/health", { replace: true });
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "Unknown error";
        navigate("/auth/error", { replace: true, state: { message } });
      });
  }, [navigate, setTokens]);

  return (
    <div className="flex h-screen items-center justify-center">
      <Spinner />
      <span className="ml-3 text-muted-foreground">Signing in…</span>
    </div>
  );
}
