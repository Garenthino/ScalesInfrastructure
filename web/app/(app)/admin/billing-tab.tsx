"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { RefreshCw, DollarSign, TrendingUp, TrendingDown, Calendar } from "lucide-react";
import { AdminBillingMetrics } from "@/lib/types";

interface BillingTabProps {
  billing: AdminBillingMetrics | null;
  loading: boolean;
  onRefresh: () => void;
}

export function BillingTab({ billing, loading, onRefresh }: BillingTabProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Billing Overview</h1>
          <p className="text-muted-foreground">
            Platform-wide subscription metrics and renewal forecast.
          </p>
        </div>
        <Button variant="outline" onClick={onRefresh} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <DollarSign className="h-4 w-4 text-emerald-500" /> MRR
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {billing ? `$${(billing.mrr_cents / 100).toLocaleString()}` : "—"}
            </div>
            <p className="text-xs text-muted-foreground">Estimated monthly recurring revenue</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-blue-500" /> Active Subs
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{billing?.active_subscriptions ?? "—"}</div>
            <p className="text-xs text-muted-foreground">Paying venues (incl. grace period)</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Calendar className="h-4 w-4 text-amber-500" /> Trialing
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{billing?.trialing_venues ?? "—"}</div>
            <p className="text-xs text-muted-foreground">Venues still in trial period</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <TrendingDown className="h-4 w-4 text-red-500" /> Past Due
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{billing?.past_due_venues ?? "—"}</div>
            <p className="text-xs text-muted-foreground">Failed or overdue payments</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Churn (30d)</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{billing?.churned_last_30_days ?? "—"}</div>
            <p className="text-xs text-muted-foreground">Venues cancelled in last 30 days</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Renewals ≤ 7d</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{billing?.upcoming_renewals_7d ?? "—"}</div>
            <p className="text-xs text-muted-foreground">Plans expiring this week</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Renewals ≤ 30d</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{billing?.upcoming_renewals_30d ?? "—"}</div>
            <p className="text-xs text-muted-foreground">Plans expiring this month</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Revenue by Tier</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-sm space-y-1">
              {billing?.revenue_by_tier_cents && Object.keys(billing.revenue_by_tier_cents).length > 0 ? (
                Object.entries(billing.revenue_by_tier_cents).map(([tier, cents]) => (
                  <div key={tier} className="flex justify-between">
                    <span className="capitalize text-muted-foreground">{tier}</span>
                    <span className="font-medium">${(Number(cents) / 100).toLocaleString()}</span>
                  </div>
                ))
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
