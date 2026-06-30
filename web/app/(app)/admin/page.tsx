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
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  } from "@/components/ui/sheet";
  import {
    fetchAdminVenues,
    fetchAdminVenue,
    fetchAdminDashboard,
    updateAdminVenueStatus,
    deleteAdminVenue,
    provisionVenue,
    impersonateVenueOwner,
  } from "@/lib/api";
import {
  AdminVenue,
  AdminVenueDetail,
  AdminDashboard,
  VenueProvisionPayload,
  VenueStatusUpdatePayload,
  AdminAuditLog,
} from "@/lib/types";
import { toast } from "sonner";
import {
  Search,
  Plus,
  RefreshCw,
  Eye,
  UserCircle,
  Loader2,
  Trash2,
  AlertTriangle,
  StickyNote,
} from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  trialing: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300",
  active: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  past_due: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
  cancelled: "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300",
  comped: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300",
};

const ACTION_LABELS: Record<string, string> = {
  "venue.status.update": "Status Update",
  "venue.impersonate": "Impersonate Owner",
  "venue.delete": "Delete Venue",
  "venue.provision": "Provision Venue",
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
  const [detail, setDetail] = useState<AdminVenueDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailOpen, setDetailOpen] = useState(false);
  const [provisionOpen, setProvisionOpen] = useState(false);
  const [impersonating, setImpersonating] = useState(false);
  const [venueToDelete, setVenueToDelete] = useState<AdminVenue | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null);
  const [activeTab, setActiveTab] = useState<"venues" | "audit">("venues");
  const [auditLogs, setAuditLogs] = useState<AdminAuditLog[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditPerPage] = useState(20);
  const [auditLoading, setAuditLoading] = useState(false);

  const load = async (p = page) => {
    setLoading(true);
    try {
      const token = getAccessToken() || undefined;
      const [dash, res] = await Promise.all([
        fetchAdminDashboard(token),
        fetchAdminVenues(
          {
            page: p,
            per_page: perPage,
            search: search || undefined,
            status: statusFilter === "all" ? undefined : statusFilter,
            tier: tierFilter === "all" ? undefined : tierFilter,
          },
          token
        ),
      ]);
      setDashboard(dash);
      setVenues(res.items);
      setTotal(res.total);
    } catch (err: any) {
      toast.error(err.message || "Failed to load venues");
    } finally {
      setLoading(false);
    }
  };

  const loadAudit = async (p = auditPage) => {
    setAuditLoading(true);
    try {
      const token = getAccessToken() || undefined;
      const res = await fetchAdminAuditLogs({ page: p, per_page: auditPerPage }, token);
      setAuditLogs(res.items);
      setAuditTotal(res.total);
    } catch (err: any) {
      toast.error(err.message || "Failed to load audit logs");
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    if (user?.role === "admin") {
      load(1);
      setPage(1);
      if (activeTab === "audit") {
        loadAudit(1);
        setAuditPage(1);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, search, statusFilter, tierFilter, activeTab]);

  const handlePage = (p: number) => {
    setPage(p);
    load(p);
  };

  const handleAuditPage = (p: number) => {
    setAuditPage(p);
    loadAudit(p);
  };

  const handleStatusUpdate = async (venueId: string, payload: VenueStatusUpdatePayload) => {
    try {
      const token = getAccessToken() || undefined;
      const updated = await updateAdminVenueStatus(venueId, payload, token);
      setVenues((prev) => prev.map((v) => (v.id === venueId ? updated : v)));
      setSelected((prev) => (prev?.id === venueId ? updated : prev));
      setDetail((prev) => {
        if (prev?.id !== venueId) return prev;
        return { ...prev, ...updated } as AdminVenueDetail;
      });
      toast.success("Venue updated");
    } catch (err: any) {
      toast.error(err.message || "Update failed");
    }
  };

  const handleViewDetail = async (venue: AdminVenue) => {
    setDetailOpen(true);
    setDetailLoading(true);
    try {
      const token = getAccessToken() || undefined;
      const full = await fetchAdminVenue(venue.id, token);
      setDetail(full);
    } catch (err: any) {
      toast.error(err.message || "Failed to load venue details");
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!venueToDelete) return;
    setIsDeleting(true);
    try {
      const token = getAccessToken() || undefined;
      await deleteAdminVenue(venueToDelete.id, token);
      setVenues((prev) => prev.filter((v) => v.id !== venueToDelete.id));
      setTotal((t) => Math.max(0, t - 1));
      toast.success(`Deleted ${venueToDelete.name}`);
    } catch (err: any) {
      toast.error(err.message || "Delete failed");
    } finally {
      setIsDeleting(false);
      setVenueToDelete(null);
    }
  };

  const handleImpersonate = async (venueId: string) => {
    setImpersonating(true);
    try {
      const token = getAccessToken() || undefined;
      const res = await impersonateVenueOwner(venueId, token);
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
  const auditTotalPages = Math.max(1, Math.ceil(auditTotal / auditPerPage));

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Venue Management</h1>
          <p className="text-muted-foreground">
            Manage all venues, billing status, and access.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="inline-flex h-9 items-center justify-center rounded-lg bg-muted p-1 text-muted-foreground">
            <button
              className={`inline-flex items-center justify-center rounded-md px-3 py-1 text-sm font-medium transition-all ${activeTab === "venues" ? "bg-background text-foreground shadow" : ""}`}
              onClick={() => setActiveTab("venues")}
            >
              Venues
            </button>
            <button
              className={`inline-flex items-center justify-center rounded-md px-3 py-1 text-sm font-medium transition-all ${activeTab === "audit" ? "bg-background text-foreground shadow" : ""}`}
              onClick={() => setActiveTab("audit")}
            >
              Audit Log
            </button>
          </div>
          {activeTab === "venues" && (
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
          )}
        </div>
      </div>

      {activeTab === "venues" ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Total Venues</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{dashboard?.total_venues ?? total}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Active</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{dashboard?.active_venues ?? venues.filter((v) => v.is_active).length}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Trialing</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {dashboard?.trialing_venues ?? venues.filter((v) => v.billing.subscription_status === "trialing").length}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Past Due</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {dashboard?.past_due_venues ?? venues.filter((v) => v.billing.subscription_status === "past_due").length}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Total Singers</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{dashboard?.total_singers ?? "—"}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Total KJ Devices</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{dashboard?.total_kj_devices ?? "—"}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">Queue Depth</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{dashboard?.queue_depth ?? "—"}</div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-medium">By Tier</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm space-y-1">
                  {dashboard?.by_tier && Object.keys(dashboard.by_tier).length > 0 ? (
                    Object.entries(dashboard.by_tier).map(([tier, count]) => (
                      <div key={tier} className="flex justify-between">
                        <span className="capitalize text-muted-foreground">{tier}</span>
                        <span className="font-medium">{Number(count)}</span>
                      </div>
                    ))
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
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
                      <div className="flex items-center gap-2">
                        {venue.name}
                        {venue.admin_notes ? (
                          <span title="Admin notes">
                            <StickyNote className="h-3.5 w-3.5 text-amber-500" />
                          </span>
                        ) : null}
                      </div>
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
                          onClick={() => handleViewDetail(venue)}
                          title="View details"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setSelected(venue)}
                          title="Edit status"
                        >
                          <svg className="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 20h9" />
                            <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                          </svg>
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => setVenueToDelete(venue)}
                          title="Delete venue"
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
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
        </>
      ) : (
        <>
          <div className="flex items-center justify-between">
            <p className="text-muted-foreground">Recent admin actions across venues.</p>
            <Button variant="outline" onClick={() => loadAudit(auditPage)} disabled={auditLoading}>
              <RefreshCw className={`mr-2 h-4 w-4 ${auditLoading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>

          <div className="rounded-lg border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Admin</TableHead>
                  <TableHead>Venue</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {auditLogs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-sm text-muted-foreground">
                      {log.created_at ? new Date(log.created_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{ACTION_LABELS[log.action] || log.action}</Badge>
                    </TableCell>
                    <TableCell className="text-sm">{log.admin_email}</TableCell>
                    <TableCell className="text-sm">
                      {log.venue_name ? (
                        <div>
                          <div>{log.venue_name}</div>
                          <div className="text-xs text-muted-foreground font-mono">{log.venue_id}</div>
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm max-w-md truncate">
                      {log.details_json || "—"}
                    </TableCell>
                  </TableRow>
                ))}
                {auditLogs.length === 0 && !auditLoading && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      No audit logs found.
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {auditTotalPages > 1 && (
            <div className="flex items-center justify-between">
              <Button
                variant="outline"
                disabled={auditPage <= 1}
                onClick={() => handleAuditPage(auditPage - 1)}
              >
                Previous
              </Button>
              <span className="text-sm text-muted-foreground">
                Page {auditPage} of {auditTotalPages}
              </span>
              <Button
                variant="outline"
                disabled={auditPage >= auditTotalPages}
                onClick={() => handleAuditPage(auditPage + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}

      {selected && (
        <VenueEditDialog
          venue={selected}
          onClose={() => setSelected(null)}
          onUpdate={handleStatusUpdate}
        />
      )}

      <Sheet open={detailOpen} onOpenChange={setDetailOpen}>
        <SheetContent side="right" className="sm:max-w-lg w-3/4 overflow-y-auto">
          <SheetHeader className="pb-4">
            <SheetTitle>{detail?.name || "Venue details"}</SheetTitle>
            <SheetDescription>
              {detail ? `${detail.slug} · ${detail.venue_code}` : "Loading venue details..."}
            </SheetDescription>
          </SheetHeader>
          {detailLoading && !detail ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : detail ? (
            <div className="space-y-6 py-2">
              <section className="space-y-2">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Overview</h3>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <DetailItem label="Venue ID" value={detail.id} monospace />
                  <DetailItem label="Slug" value={detail.slug} />
                  <DetailItem label="Venue Code" value={detail.venue_code} monospace />
                  <DetailItem label="Timezone" value={detail.timezone} />
                  <DetailItem
                    label="Status"
                    value={
                      <Badge className={STATUS_COLORS[detail.billing.subscription_status] || ""}>
                        {detail.billing.subscription_status}
                      </Badge>
                    }
                  />
                  <DetailItem label="Active" value={detail.is_active ? "Yes" : "No"} />
                  <DetailItem
                    label="Created"
                    value={detail.created_at ? new Date(detail.created_at).toLocaleString() : "—"}
                  />
                  <DetailItem
                    label="Updated"
                    value={detail.updated_at ? new Date(detail.updated_at).toLocaleString() : "—"}
                  />
                </div>
              </section>

              <hr className="border-border" />

              <section className="space-y-2">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Owner & Contact</h3>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <DetailItem label="Owner Email" value={detail.owner_email || "—"} />
                  <DetailItem label="Billing Email" value={detail.billing.billing_email || "—"} />
                  <DetailItem label="Sales Rep" value={detail.billing.sales_rep_email || "—"} />
                  <DetailItem label="Phone" value={detail.contact?.phone || "—"} />
                  <DetailItem label="Contact Email" value={detail.contact?.email || "—"} />
                </div>
              </section>

              <hr className="border-border" />

              <section className="space-y-2">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Billing</h3>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <DetailItem label="Tier" value={detail.billing.subscription_tier} />
                  <DetailItem label="Status" value={detail.billing.subscription_status} />
                  <DetailItem label="Billing Status" value={detail.billing.billing_status} />
                  <DetailItem label="Signup Source" value={detail.billing.signup_source} />
                  <DetailItem
                    label="Plan Expires"
                    value={detail.billing.plan_expires_at ? new Date(detail.billing.plan_expires_at).toLocaleString() : "—"}
                  />
                  <DetailItem
                    label="Trial Ends"
                    value={detail.billing.trial_ends_at ? new Date(detail.billing.trial_ends_at).toLocaleString() : "—"}
                  />
                </div>
              </section>

              <hr className="border-border" />

              <section className="space-y-2">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Stats</h3>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                  <DetailItem label="Total Singers" value={String(detail.total_singers)} />
                  <DetailItem label="Active Singers" value={String(detail.stats?.active_singers ?? 0)} />
                  <DetailItem label="Total KJ Devices" value={String(detail.total_kj_devices)} />
                  <DetailItem label="Queue Depth" value={String(detail.queue_depth)} />
                  <DetailItem label="Total Songs" value={String(detail.stats?.total_songs ?? 0)} />
                </div>
              </section>

              <section className="space-y-2">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Address</h3>
                <div className="grid grid-cols-1 gap-y-1 text-sm text-muted-foreground">
                  {detail.address?.street ? <p>{detail.address.street}</p> : null}
                  <p>
                    {[detail.address?.city, detail.address?.state, detail.address?.zip]
                      .filter(Boolean)
                      .join(", ") || "—"}
                  </p>
                  <p>{detail.address?.country || "—"}</p>
                </div>
              </section>

              {detail.settings ? (
                <section className="space-y-2">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Settings</h3>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
                    <DetailItem label="Max Queue Depth" value={String(detail.settings.max_queue_depth)} />
                    <DetailItem label="Require Approval" value={detail.settings.require_approval ? "Yes" : "No"} />
                    <DetailItem label="Allow Duplicates" value={detail.settings.allow_duplicates ? "Yes" : "No"} />
                    <DetailItem label="Rotation Mode" value={detail.settings.rotation_mode} />
                  </div>
                </section>
              ) : null}

              {detail.operating_hours ? (
                <section className="space-y-2">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Operating Hours</h3>
                  <div className="text-sm text-muted-foreground">
                    <p>Timezone: {detail.operating_hours.timezone}</p>
                    <p>Schedule entries: {detail.operating_hours.schedule?.length ?? 0}</p>
                  </div>
                </section>
              ) : null}
            </div>
          ) : null}
        </SheetContent>
      </Sheet>

      <Dialog open={!!venueToDelete} onOpenChange={(open) => !open && setVenueToDelete(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Delete venue?
            </DialogTitle>
            <DialogDescription>
              This will soft-delete <strong>{venueToDelete?.name}</strong> ({venueToDelete?.slug}).
              The venue and its data will be hidden from normal queries but remain in the database.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setVenueToDelete(null)} disabled={isDeleting}>Cancel</Button>
            <Button onClick={handleDelete} disabled={isDeleting} variant="destructive">
              {isDeleting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Deleting...
                </>
              ) : (
                "Delete"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function DetailItem({
  label,
  value,
  monospace = false,
}: {
  label: string;
  value: React.ReactNode;
  monospace?: boolean;
}) {
  return (
    <div className="space-y-0.5">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className={monospace ? "font-mono" : undefined}>{value}</div>
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
    admin_notes: venue.admin_notes ?? null,
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
          <div className="space-y-1.5">
            <Label htmlFor="admin_notes">Admin Notes</Label>
            <textarea
              id="admin_notes"
              className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              value={(payload as any).admin_notes ?? ""}
              onChange={(e) => setPayload({ ...payload, admin_notes: e.target.value || null } as any)}
              placeholder="Internal notes about this venue..."
              rows={4}
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
