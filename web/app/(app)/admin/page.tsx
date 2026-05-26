import { AppShell } from "@/components/app-shell";
import { ProtectedRoute } from "@/components/protected-route";

export default function AdminPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Admin</h1>
      <p className="text-muted-foreground">Administration settings and tools.</p>
    </div>
  );
}
