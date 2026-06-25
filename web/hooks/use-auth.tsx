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

  const getAccessToken = useCallback(() => accessToken, []);

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

    // Only fetch once per token to prevent loops during impersonation/navigation
    if (fetchedTokenRef.current === accessToken || fetchedTokens.has(accessToken)) {
      return;
    }
    fetchedTokenRef.current = accessToken;
    fetchedTokens.add(accessToken);

    // Deduplicate concurrent in-flight fetches so only one /auth/me fires
    if (fetchingRef.current) {
      return;
    }

    setIsLoading(true);
    const fetchPromise = fetchMe(accessToken).finally(() => {
      fetchingRef.current = null;
    });
    fetchingRef.current = fetchPromise;

    fetchPromise
      .then((u) => {
        setUser(u);
      })
      .catch(() => {
        // Only clear tokens if the failure happened with the same token we started with
        if (getAccessToken() === accessToken) {
          removeAccessToken();
          removeRefreshToken();
          setUser(null);
          router.push("/auth/login");
        }
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [accessHydrated, accessToken, removeAccessToken, removeRefreshToken, getAccessToken, router]);

  const login = async (email: string, password: string) => {
    setIsLoading(true);
    try {
      const data: LoginResponse = await loginUser(email, password);
      setAccessToken(data.access_token);
      setRefreshToken(data.refresh_token);
      const u = await fetchMe(data.access_token);
      setUser(u);
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
      const u = await fetchMe(data.access_token);
      setUser(u);
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
