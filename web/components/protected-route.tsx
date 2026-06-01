"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";

const ROLE_RANK: Record<string, number> = {
  owner: 4,
  admin: 3,
  operator: 2,
  kj: 1,
};

interface ProtectedRouteProps {
  children: React.ReactNode;
  requiredRole?: string;
}

export function ProtectedRoute({ children, requiredRole }: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;

    if (!isAuthenticated) {
      router.replace("/auth/login");
      return;
    }

    if (requiredRole && user) {
      const userRank = ROLE_RANK[user.role] ?? 0;
      const requiredRank = ROLE_RANK[requiredRole] ?? 0;
      if (userRank < requiredRank) {
        router.replace("/queue");
      }
    }
  }, [isLoading, isAuthenticated, user, requiredRole, router]);

  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted-foreground border-t-primary" />
      </div>
    );
  }

  if (!isAuthenticated) return null;

  if (requiredRole && user) {
    const userRank = ROLE_RANK[user.role] ?? 0;
    const requiredRank = ROLE_RANK[requiredRole] ?? 0;
    if (userRank < requiredRank) return null;
  }

  return <>{children}</>;
}
