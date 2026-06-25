"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchAdminVenues,
  updateAdminVenueStatus,
  provisionVenue,
  impersonateVenueOwner,
} from "@/lib/api";
import { AdminVenue, VenueProvisionPayload, VenueStatusUpdatePayload } from "@/lib/types";
import { toast } from "sonner";
import { Search, Plus, RefreshCw, Eye, UserCircle, Loader2 } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  trialing: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300",
  active: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  past_due: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  cancelled: "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300",
  comped: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
};

export default function AdminPage() {
  const { user, getAccessToken } = useAuth();
  const [venues, setVenues] = useState<AdminVenue[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [tierFilter, setTierFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<AdminVenue | null>(null);
  const [provisionOpen, setProvisionOpen] = useState(false);
  const [impersonating, setImpersonating] = useState(false);

  const load = async (p = page) => {
    setLoading(true);
    try {
      const token = getAccessToken() || undefined;
      const res = await fetchAdminVenues(
        {
          page: p,
          per_page: perPage,
          search: search || undefined,
          status: statusFilter === "all" ? undefined : statusFilter,
          tier: tierFilter === "all" ? undefined : tierFilter,
        },
        token
      );
      setVenues(res.items);
      setTotal(res.total);
    } catch (err: any) {
      toast.error(err.message || "Failed to load venues");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === "admin") {
      load(1);
      setPage(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, search, statusFilter, tierFilter]);

  const handlePage = (p: number) => {
    setPage(p);
    load(p);
  };

  const handleStatusUpdate = async (venueId: string, payload: VenueStatusUpdatePayload) => {
    try {
      const token = getAccessToken() || undefined;
      const updated = await updateAdminVenueStatus(venueId, payload, token);
      setVenues((prev) => prev.map((v) => (v.id === venueId ? updated : v)));
      setSelected((prev) => (prev?.id === venueId ? updated : prev));
      toast.success("Venue updated");
    } catch (err: any) {
      toast.error(err.message || "Update failed");
    }
  };

  const handleImpersonate = async (venueId: string) => {
    setImpersonating(true);
    try {
      const token = getAccessToken() || undefined;
      const res = await impersonateVenueOwner(venueId, token);
      // Open portal in new tab as the owner
      const url = `${window.location.origin}/venue?impersonate=${encodeURIComponent(res.access_token)}`;
      window.open(url, "_blank");
      toast.success("Impersonation token issued");
    } catch (err: any) {
      toast.error(err.message || "Impersonation failed");
    } finally {
      setImpersonating(false);
    }
  };

  const handleProvision = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    const payload: VenueProvisionPayload = {
      venue_name: String(fd.get("venue_name")),
      slug: String(fd.get("slug")),
      owner_email: String(fd.get("owner_email")),
      owner_password: String(fd.get("owner_password")),
      owner_stage_name: String(fd.get("owner_stage_name")),
      timezone: String(fd.get("timezone") || "UTC"),
      subscription_tier: String(fd.get("subscription_tier") || "basic"),
      sales_rep_email: String(fd.get("sales_rep_email") || "") || undefined,
    };
    try {
      const token = getAccessToken() || undefined;
      const created = await provisionVenue(payload, token);
      setVenues((prev) => [created, ...prev]);
      setTotal((t) => t + 1);
      setProvisionOpen(false);
      form.reset();
      toast.success("Venue provisioned");
    } catch (err: any) {
      toast.error(err.message || "Provisioning failed");
    }
  };

  if (user?.role !== "admin") {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <p className="font-medium">Admin access required</p>
        <p className="text-sm mt-1">You do not have permission to view this page.</p>
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Venue Management</h1>
          <p className="text-muted-foreground">
            Manage all venues, billing status, and access.
          </p>
        </div>
        <Dialog open={provisionOpen} onOpenChange={setProvisionOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" /> Provision Venue
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Provision New Venue</DialogTitle>
              <DialogDescription>
                Create a venue and owner account for sales-assisted onboarding.
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleProvision} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <Label htmlFor="venue_name">Venue Name</Label>
                  <Input id="venue_name" name="venue_name" required />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="slug">Slug</Label>
                  <Input id="slug" name="slug" required pattern="[a-z0-9-]+" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="owner_email">Owner Email</Label>
                  <Input id="owner_email" name="owner_email" type="email" required />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="owner_password">Owner Password</Label>
                  <Input id="owner_password" name="owner_password" type="password" minLength={8} required />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="owner_stage_name">Owner Stage Name</Label>
                  <Input id="owner_stage_name" name="owner_stage_name" required />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="timezone">Timezone</Label>
                  <Input id="timezone" name="timezone" defaultValue="UTC" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="subscription_tier">Tier</Label>
                  <Select name="subscription_tier" defaultValue="basic">
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="basic">basic</SelectItem>
                      <SelectItem value="pro">pro</SelectItem>
                      <SelectItem value="enterprise">enterprise</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="sales_rep_email">Sales Rep Email</Label>
                  <Input id="sales_rep_email" name="sales_rep_email" type="email" />
                </div>
              </div>
              <DialogFooter>
                <Button type="submit">Provision</Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Total Venues</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Active</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{venues.filter((v) => v.is_active).length}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Trialing</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {venues.filter((v) => v.billing.subscription_status === "trialing").length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Past Due</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {venues.filter((v) => v.billing.subscription_status === "past_due").length}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="flex flex-col gap-4 md:flex-row">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search name, slug, code..."
            className="pl-9"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Filter status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            <SelectItem value="trialing">Trialing</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="past_due">Past Due</SelectItem>
            <SelectItem value="cancelled">Cancelled</SelectItem>
            <SelectItem value="comped">Comped</SelectItem>
          </SelectContent>
        </Select>
        <Select value={tierFilter} onValueChange={setTierFilter}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Filter tier" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All tiers</SelectItem>
            <SelectItem value="basic">Basic</SelectItem>
            <SelectItem value="pro">Pro</SelectItem>
            <SelectItem value="enterprise">Enterprise</SelectItem>
          </SelectContent>
        </Select>
        <Button variant="outline" onClick={() => load(page)} disabled={loading}>
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </Button>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Venue</TableHead>
              <TableHead>Code</TableHead>
              <TableHead>Tier</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>S / KJ / Q</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {venues.map((venue) => (
              <TableRow key={venue.id}>
                <TableCell className="font-medium">
                  <div>{venue.name}</div>
                  <div className="text-xs text-muted-foreground">{venue.slug}</div>
                </TableCell>
                <TableCell className="font-mono">{venue.venue_code}</TableCell>
                <TableCell className="capitalize">{venue.billing.subscription_tier}</TableCell>
                <TableCell>
                  <Badge className={STATUS_COLORS[venue.billing.subscription_status] || ""}>
                    {venue.billing.subscription_status}
                  </Badge>
                </TableCell>
                <TableCell className="text-sm">{venue.owner_email || "—"}</TableCell>
                <TableCell className="text-sm tabular-nums">
                  {venue.total_singers} / {venue.total_kj_devices} / {venue.queue_depth}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {venue.created_at ? new Date(venue.created_at).toLocaleDateString() : "—"}
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleImpersonate(venue.id)}
                      disabled={impersonating}
                      title="Impersonate owner"
                    >
                      {impersonating ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <UserCircle className="h-4 w-4" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setSelected(venue)}
                      title="Edit status"
                    >
                      <Eye className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {venues.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                  No venues found.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <Button
            variant="outline"
            disabled={page <= 1}
            onClick={() => handlePage(page - 1)}
          >
            Previous
          </Button>
          <span className="text-sm text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <Button
            variant="outline"
            disabled={page >= totalPages}
            onClick={() => handlePage(page + 1)}
          >
            Next
          </Button>
        </div>
      )}

      {selected && (
        <VenueEditDialog
          venue={selected}
          onClose={() => setSelected(null)}
          onUpdate={handleStatusUpdate}
        />
      )}
    </div>
  );
}

function VenueEditDialog({
  venue,
  onClose,
  onUpdate,
}: {
  venue: AdminVenue;
  onClose: () => void;
  onUpdate: (id: string, payload: VenueStatusUpdatePayload) => Promise<void>;
}) {
  const [payload, setPayload] = useState<VenueStatusUpdatePayload>({
    is_active: venue.is_active,
    subscription_tier: venue.billing.subscription_tier || "basic",
    subscription_status: venue.billing.subscription_status || "trialing",
    billing_status: venue.billing.billing_status || "trial",
    plan_expires_at: venue.billing.plan_expires_at ?? null,
    trial_ends_at: venue.billing.trial_ends_at ?? null,
    sales_rep_email: venue.billing.sales_rep_email ?? null,
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{venue.name}</DialogTitle>
          <DialogDescription>{venue.slug} · {venue.venue_code}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="flex items-center justify-between">
            <Label htmlFor="is_active">Active</Label>
            <input
              id="is_active"
              type="checkbox"
              checked={payload.is_active ?? venue.is_active}
              onChange={(e) => setPayload({ ...payload, is_active: e.target.checked })}
            />
          </div>
          <div className="space-y-1.5">
            <Label>Tier</Label>
            <Select
              value={payload.subscription_tier ?? venue.billing.subscription_tier}
              onValueChange={(v) => setPayload({ ...payload, subscription_tier: v })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="basic">basic</SelectItem>
                <SelectItem value="pro">pro</SelectItem>
                <SelectItem value="enterprise">enterprise</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Subscription Status</Label>
            <Select
              value={payload.subscription_status ?? venue.billing.subscription_status}
              onValueChange={(v) => setPayload({ ...payload, subscription_status: v })}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="trialing">Trialing</SelectItem>
                <SelectItem value="active">Active</SelectItem>
                <SelectItem value="past_due">Past Due</SelectItem>
                <SelectItem value="cancelled">Cancelled</SelectItem>
                <SelectItem value="comped">Comped</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="trial_ends_at">Trial Ends At (ISO)</Label>
            <Input
              id="trial_ends_at"
              value={payload.trial_ends_at ?? ""}
              onChange={(e) => setPayload({ ...payload, trial_ends_at: e.target.value || null })}
              placeholder="2026-12-31T23:59:59Z"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sales_rep_email">Sales Rep Email</Label>
            <Input
              id="sales_rep_email"
              value={payload.sales_rep_email ?? ""}
              onChange={(e) => setPayload({ ...payload, sales_rep_email: e.target.value || null })}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={() => onUpdate(venue.id, payload).then(onClose)}>Save Changes</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
