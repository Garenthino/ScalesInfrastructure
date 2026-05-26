import type { Metadata } from "next";
import "@/app/globals.css";
import QueryProvider from "@/components/query-provider";
import { AuthProvider } from "@/hooks/use-auth";
import { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Scales Web Portal",
  description: "Venue management dashboard",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <QueryProvider>
          <AuthProvider>{children}</AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
