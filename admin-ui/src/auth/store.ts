import { create } from "zustand";
import type { TokenSet } from "./cognito";
import { redirectToLogin, redirectToLogout, refreshTokens } from "./cognito";

interface AuthState {
  tokens: TokenSet | null;
  isRefreshing: boolean;
  setTokens: (tokens: TokenSet) => void;
  logout: () => void;
  getValidAccessToken: () => Promise<string | null>;
}

export const useAuthStore = create<AuthState>()((set, get) => ({
  tokens: null,
  isRefreshing: false,

  setTokens(tokens) {
    set({ tokens });
  },

  logout() {
    set({ tokens: null });
    redirectToLogout();
  },

  async getValidAccessToken() {
    const { tokens, isRefreshing } = get();

    if (!tokens) return null;

    // If token is still valid for at least 60s, return it directly
    if (tokens.expiresAt - Date.now() > 60_000) {
      return tokens.accessToken;
    }

    // Avoid concurrent refreshes
    if (isRefreshing) {
      await new Promise<void>((resolve) => {
        const unsub = useAuthStore.subscribe((s) => {
          if (!s.isRefreshing) {
            unsub();
            resolve();
          }
        });
      });
      return get().tokens?.accessToken ?? null;
    }

    set({ isRefreshing: true });
    try {
      const refreshed = await refreshTokens(tokens.refreshToken);
      set({ tokens: refreshed, isRefreshing: false });
      return refreshed.accessToken;
    } catch {
      set({ tokens: null, isRefreshing: false });
      redirectToLogin().catch(() => undefined);
      return null;
    }
  },
}));
