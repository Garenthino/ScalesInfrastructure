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
import { fetchAdminLicenses, createLicense, revokeLicense } from "@/lib/api";
import { License, LicenseCreatePayload } from "@/lib/types";
import { toast } from "sonner";
import { Key, Plus, RefreshCw, Ban, Loader2, Copy } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  unactivated: "bg-gray-100 text-gray-800 dark:bg-gray-900/30 dark:text-gray-300",
  active: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
  expired: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300",
  revoked: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
};

export default function LicenseAdminPage() {
  const { user, getAccessToken } = useAuth();
  const [licenses, setLicenses] = useState<License[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [perPage] = useState(20);
  const [statusFilter, setStatusFilter] = useState("all");
  const [loading, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [createdLicense, setCreatedLicense] = useState<License | null>(null);

  const load = async (p = page) => {
    setLoading(true);
    try {
      const token = getAccessToken() || undefined;
      const res = await fetchAdminLicenses(
        {
          page: p,
          per_page: perPage,
          status: statusFilter === "all" ? undefined : statusFilter,
        },
        token
      );
      setLicenses(res.items);
      setTotal(res.total);
    } catch (err: any) {
      toast.error(err.message || "Failed to load licenses");
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
  }, [user, statusFilter]);

  const handlePage = (p: number) => {
    setPage(p);
    load(p);
  };

  const handleCreate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const fd = new FormData(form);
    const grace_days = Number(fd.get("grace_days") || 7);
    const payload: LicenseCreatePayload = {
      venue_id: String(fd.get("venue_id")),
      plan: String(fd.get("plan") || "basic"),
      expires_at: String(fd.get("expires_at") || "") || undefined,
      grace_days,
    };
    const seatLimit = fd.get("seat_limit");
    if (seatLimit && String(seatLimit).trim()) {
      payload.seat_limit = Number(seatLimit);
    }
    try {
      const token = getAccessToken() || undefined;
      const created = await createLicense(payload, token);
      setCreatedKey(created.license_key);
      setCreatedLicense({
        id: created.id,
        venue_id: created.venue_id,
        license_key_prefix: created.license_key.split("-").slice(1, 3).join(""),
        status: "unactivated",
        plan: created.plan,
        expires_at: created.expires_at || null,
        grace_days,
        created_at: created.created_at,
        updated_at: created.created_at,
      });
      setLicenses((prev) => [
        {
          id: created.id,
          venue_id: created.venue_id,
          license_key_prefix: created.license_key.split("-").slice(1, 3).join(""),
          status: "unactivated",
          plan: created.plan,
          expires_at: created.expires_at || null,
          grace_days,
          created_at: created.created_at,
          updated_at: created.created_at,
        },
        ...prev,
      ]);
      setTotal((t) => t + 1);
      setCreateOpen(false);
      form.reset();
      toast.success("License created");
    } catch (err: any) {
      toast.error(err.message || "Failed to create license");
    }
  };

  const handleRevoke = async (license: License) => {
    try {
      const token = getAccessToken() || undefined;
      await revokeLicense(license.id, token);
      setLicenses((prev) =>
        prev.map((l) => (l.id === license.id ? { ...l, status: "revoked" } : l))
      );
      toast.success("License revoked");
    } catch (err: any) {
      toast.error(err.message || "Failed to revoke license");
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
          <h1 className="text-2xl font-bold tracking-tight">License Management</h1>
          <p className="text-muted-foreground">
            Create, track, and revoke offline desktop licenses.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="Filter status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="unactivated">Unactivated</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="expired">Expired</SelectItem>
              <SelectItem value="revoked">Revoked</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" onClick={() => load(page)} disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="mr-2 h-4 w-4" /> Create License
              </Button>
            </DialogTrigger>
            <DialogContent className="sm:max-w-lg">
              <DialogHeader>
                <DialogTitle>Create License</DialogTitle>
                <DialogDescription>
                  Generate a new offline license key for a venue. The full key is shown only once.
                </DialogDescription>
              </DialogHeader>
              <form onSubmit={handleCreate} className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="venue_id">Venue ID</Label>
                  <Input id="venue_id" name="venue_id" required />
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="plan">Plan</Label>
                    <Select name="plan" defaultValue="basic">
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
                    <Label htmlFor="seat_limit">Seat Limit</Label>
                    <Input id="seat_limit" name="seat_limit" type="number" min={1} placeholder="Unlimited" />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="expires_at">Expires At (ISO)</Label>
                    <Input id="expires_at" name="expires_at" placeholder="2027-12-31T23:59:59Z" />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="grace_days">Grace Days</Label>
                    <Input id="grace_days" name="grace_days" type="number" min={0} defaultValue={7} />
                  </div>
                </div>
                <DialogFooter>
                  <Button type="submit">Create License</Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Total Licenses</CardTitle>
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
            <div className="text-2xl font-bold">
              {licenses.filter((l) => l.status === "active").length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Unactivated</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {licenses.filter((l) => l.status === "unactivated").length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">Revoked</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {licenses.filter((l) => l.status === "revoked").length}
            </div>
          </CardContent>
        </Card>
      </div>

      {createdKey && (
        <div className="rounded-lg border border-dashed p-4 bg-muted/30">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Key className="h-4 w-4 text-primary" />
              <span className="font-medium">New license key</span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                navigator.clipboard.writeText(createdKey);
                toast.success("Copied to clipboard");
              }}
            >
              <Copy className="mr-1 h-3.5 w-3.5" /> Copy
            </Button>
          </div>
          <p className="mt-2 font-mono text-sm break-all">{createdKey}</p>
          <p className="text-xs text-muted-foreground mt-1">
            Store this key securely — it will not be shown again. ID: {createdLicense?.id}
          </p>
        </div>
      )}

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>License</TableHead>
              <TableHead>Venue</TableHead>
              <TableHead>Plan</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead>Activated</TableHead>
              <TableHead>Created</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {licenses.map((license) => (
              <TableRow key={license.id}>
                <TableCell className="font-mono text-sm">
                  {license.license_key_prefix}…
                  <div className="text-xs text-muted-foreground">{license.id}</div>
                </TableCell>
                <TableCell className="font-mono text-xs">{license.venue_id}</TableCell>
                <TableCell className="capitalize">{license.plan}</TableCell>
                <TableCell>
                  <Badge className={STATUS_COLORS[license.status] || ""}>{license.status}</Badge>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {license.expires_at ? new Date(license.expires_at).toLocaleDateString() : "—"}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {license.activated_at ? new Date(license.activated_at).toLocaleString() : "—"}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {license.created_at ? new Date(license.created_at).toLocaleDateString() : "—"}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => handleRevoke(license)}
                    disabled={license.status === "revoked"}
                    className="text-destructive hover:text-destructive"
                    title="Revoke license"
                  >
                    <Ban className="h-4 w-4" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {licenses.length === 0 && !loading && (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                  No licenses found.
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
    </div>
  );
}
