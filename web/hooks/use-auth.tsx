"use client";

import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { fetchMe, loginUser, refreshToken } from "@/lib/api";
import { User, LoginResponse, TokenPair } from "@/lib/types";
import { useRouter } from "next/navigation";

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  tokens: TokenPair | null;
  getAccessToken: () => string | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const ACCESS_TOKEN_KEY = "scales_access_token";
const REFRESH_TOKEN_KEY = "scales_refresh_token";

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

  const getAccessToken = useCallback(() => accessToken, [accessToken]);

  const logout = useCallback(() => {
    removeAccessToken();
    removeRefreshToken();
    setUser(null);
    router.push("/auth/login");
  }, [removeAccessToken, removeRefreshToken, router]);

  // Auto-refresh token before expiry
  useEffect(() => {
    if (!accessHydrated || !accessToken) {
      setIsLoading(false);
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
        // Token already expired — log out instead of hammering refresh endpoint
        logout();
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
        logout();
      } finally {
        setIsRefreshing(false);
      }
    };

    scheduleRefresh();
    return () => clearTimeout(timer);
  }, [accessHydrated, accessToken, refreshTokenValue, logout, setAccessToken]);

  // Fetch user on mount when tokens exist
  useEffect(() => {
    if (!accessHydrated) return;
    if (!accessToken) {
      setIsLoading(false);
      return;
    }

    fetchMe(accessToken)
      .then((u) => {
        setUser(u);
      })
      .catch(() => {
        logout();
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [accessHydrated, accessToken, logout]);

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

  const tokens = accessToken && refreshTokenValue ? { access_token: accessToken, refresh_token: refreshTokenValue } : null;

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
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
