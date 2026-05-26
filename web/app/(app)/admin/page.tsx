"use client";

import { SingerTierBadge } from "@/components/singer-tier-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AdminPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Admin</h1>
      <p className="text-muted-foreground">
        Administration, loyalty tiers, quests, and manual point awards.
      </p>
      <div className="mt-6 rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <p className="font-medium">Loyalty &amp; Commerce Admin</p>
        <p className="text-sm mt-1">Tier/quest management and manual point awards.</p>
      </div>
    </div>
  );
}
