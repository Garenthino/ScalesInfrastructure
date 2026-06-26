"use client";

import { createContext, useContext, useState, useEffect, useCallback, useRef, ReactNode } from "react";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { fetchMe, loginUser, refreshToken } from "@/lib/api";
import { User, LoginResponse, TokenPair } from "@/lib/types";
import { useRouter } from "next/navigation";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  loginWithSignup: (data: { access_token: string; refresh_token: string }) => Promise<void>;
  logout: () => void;
  tokens: TokenPair | null;
  getAccessToken: () => string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const ACCESS_TOKEN_KEY="scales...oken";
const REFRESH_TOKEN_KEY="scales...oken";

// Process-wide token guard so /auth/me is never fetched more than once for the same token,
// even across component remounts or Strict Mode double-effects.
const fetchedTokens = new Set<string>();

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();

  const {
    value: accessToken,
    setValue: setAccessToken,
    removeValue: removeAccessToken,
    isHydrated: accessHydrated,
  } = useLocalStorage<string | null>(ACCESS_TOKEN_KEY, null);

  const {
    value: refreshTokenValue,
    setValue: setRefreshToken,
    removeValue: removeRefreshToken,
  } = useLocalStorage<string | null>(REFRESH_TOKEN_KEY, null);

  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const fetchedTokenRef = useRef<string | null>(null);
  const fetchingRef = useRef<Promise<User> | null>(null);

  const getAccessToken = useCallback(() => accessToken, [accessToken]);

  // Shared helper: fetch /auth/me once per token, deduping concurrent callers.
  const ensureUserForToken = useCallback(
    async (token: string) => {
      // If a fetch for this token is already in flight, return the same promise so callers share it.
      if (fetchingRef.current) {
        return fetchingRef.current;
      }
      // Already completed for this token; return the cached user.
      if (fetchedTokens.has(token)) {
        return user as User;
      }
      fetchedTokens.add(token);
      fetchedTokenRef.current = token;
      const promise = fetchMe(token)
        .then((u) => {
          setUser(u);
          return u;
        })
        .catch(() => {
          // Only clear tokens if the failure happened with the same token we started with
          if (getAccessToken() === token) {
            removeAccessToken();
            removeRefreshToken();
            setUser(null);
          }
          throw new Error("Failed to fetch user");
        })
        .finally(() => {
          fetchingRef.current = null;
        });
      fetchingRef.current = promise;
      return promise;
    },
    [accessToken, user, getAccessToken, removeAccessToken, removeRefreshToken]
  );

  const logout = useCallback(() => {
    removeAccessToken();
    removeRefreshToken();
    setUser(null);
    router.push("/auth/login");
  }, [removeAccessToken, removeRefreshToken, router]);

  // Auto-refresh token before expiry
  useEffect(() => {
    if (!accessHydrated || !accessToken) {
      return;
    }

    let timer: ReturnType<typeof setTimeout>;

    const decodeExp = (token: string): number | null => {
      try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        return payload.exp ? payload.exp * 1000 : null;
      } catch {
        return null;
      }
    };

    const scheduleRefresh = () => {
      if (!refreshTokenValue || isRefreshing) return;
      const exp = decodeExp(accessToken);
      if (!exp) return;
      const now = Date.now();
      const buffer = 60_000; // refresh 1 min before expiry
      const delay = exp - now - buffer;
      if (delay <= 0) {
        removeAccessToken();
        removeRefreshToken();
        setUser(null);
        router.push("/auth/login");
        return;
      }
      timer = setTimeout(performRefresh, delay);
    };

    const performRefresh = async () => {
      if (!refreshTokenValue || isRefreshing) return;
      setIsRefreshing(true);
      try {
        const data = await refreshToken(refreshTokenValue);
        setAccessToken(data.access_token);
        scheduleRefresh();
      } catch {
        removeAccessToken();
        removeRefreshToken();
        setUser(null);
        router.push("/auth/login");
      } finally {
        setIsRefreshing(false);
      }
    };

    scheduleRefresh();
    return () => clearTimeout(timer);
  }, [accessHydrated, accessToken, refreshTokenValue, isRefreshing, removeAccessToken, removeRefreshToken, setAccessToken, router]);

  // Fetch user on mount / when token changes
  useEffect(() => {
    if (!accessHydrated) return;
    if (!accessToken) {
      setIsLoading(false);
      fetchedTokenRef.current = null;
      return;
    }

    // If an impersonation token is in the URL and we are not yet using it,
    // skip fetching for the old token. After loginWithSignup swaps to the new
    // token, this effect will run again and fetch exactly once.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const impersonateToken = params.get("impersonate");
      if (impersonateToken && accessToken !== impersonateToken) {
        return;
      }
    }

    setIsLoading(true);
    ensureUserForToken(accessToken)
      .catch(() => {
        // navigate handled inside helper
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [accessHydrated, accessToken, ensureUserForToken]);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const data: LoginResponse = await loginUser(email, password);
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      await ensureUserForToken(data.access_token);
      router.push("/queue");
    } catch (err) {
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const loginWithSignup = async (data: { access_token: string; refresh_token: string }) => {
    setIsLoading(true);
    try {
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      await ensureUserForToken(data.access_token);
      router.push("/venue");
    } catch (err) {
      throw err;
    } finally {
      setIsLoading(false);
    }
  };

  const tokens = accessToken ? { access_token: accessToken, refresh_token: refreshTokenValue || "" } : null;

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        loginWithSignup,
        logout,
        tokens,
        getAccessToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
