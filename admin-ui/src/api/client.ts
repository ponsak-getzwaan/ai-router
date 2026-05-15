import { useAuthStore } from "../auth/store";
import { redirectToLogin } from "../auth/cognito";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const token = await useAuthStore.getState().getValidAccessToken();

  if (!token) {
    redirectToLogin().catch(() => undefined);
    throw new ApiError(401, "unauthenticated");
  }

  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init.headers,
    },
  });

  if (resp.status === 401) {
    // Token was rejected — clear state and force re-login
    useAuthStore.getState().logout();
    throw new ApiError(401, "session_expired");
  }

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new ApiError(resp.status, text || resp.statusText);
  }

  return resp.json() as Promise<T>;
}
