export interface User {
  user_id: string;
  username: string;
  role: "admin" | "operator";
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
}

export interface RefreshResponse {
  access_token: string;
}
