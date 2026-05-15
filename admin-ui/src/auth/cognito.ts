import {
  generateCodeChallenge,
  generateCodeVerifier,
  generateState,
} from "./pkce";

export interface TokenSet {
  accessToken: string;
  idToken: string;
  refreshToken: string;
  expiresAt: number; // epoch ms
}

const COGNITO_DOMAIN = import.meta.env["VITE_COGNITO_DOMAIN"] as string;
const CLIENT_ID = import.meta.env["VITE_COGNITO_CLIENT_ID"] as string;
const REDIRECT_URI = import.meta.env["VITE_COGNITO_REDIRECT_URI"] as string;
const LOGOUT_URI = import.meta.env["VITE_COGNITO_LOGOUT_URI"] as string;

const VERIFIER_KEY = "pkce_verifier";
const STATE_KEY = "pkce_state";

export async function redirectToLogin(): Promise<void> {
  const verifier = generateCodeVerifier();
  const challenge = await generateCodeChallenge(verifier);
  const state = generateState();

  // sessionStorage is OK for auth flow data — these are not tokens
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);

  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    redirect_uri: REDIRECT_URI,
    scope: "openid email aws.cognito.signin.user.admin",
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });

  window.location.href = `${COGNITO_DOMAIN}/oauth2/authorize?${params.toString()}`;
}

export async function exchangeCode(
  code: string,
  returnedState: string
): Promise<TokenSet> {
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  const expectedState = sessionStorage.getItem(STATE_KEY);

  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);

  if (!verifier || returnedState !== expectedState) {
    throw new Error("invalid_state");
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    code,
    code_verifier: verifier,
  });

  const resp = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`token_exchange_failed: ${text}`);
  }

  const json = (await resp.json()) as {
    access_token: string;
    id_token: string;
    refresh_token: string;
    expires_in: number;
  };

  return {
    accessToken: json.access_token,
    idToken: json.id_token,
    refreshToken: json.refresh_token,
    expiresAt: Date.now() + json.expires_in * 1000,
  };
}

export async function refreshTokens(refreshToken: string): Promise<TokenSet> {
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: CLIENT_ID,
    refresh_token: refreshToken,
  });

  const resp = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  if (!resp.ok) {
    throw new Error("refresh_failed");
  }

  const json = (await resp.json()) as {
    access_token: string;
    id_token: string;
    refresh_token?: string;
    expires_in: number;
  };

  return {
    accessToken: json.access_token,
    idToken: json.id_token,
    // Cognito may not return a new refresh token — keep the old one
    refreshToken: json.refresh_token ?? refreshToken,
    expiresAt: Date.now() + json.expires_in * 1000,
  };
}

export function redirectToLogout(): void {
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    logout_uri: LOGOUT_URI,
  });
  window.location.href = `${COGNITO_DOMAIN}/logout?${params.toString()}`;
}
