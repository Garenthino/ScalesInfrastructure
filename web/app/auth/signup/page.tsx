"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Music, Loader2 } from "lucide-react";
import Link from "next/link";
import { signupVenue, checkSlugAvailable } from "@/lib/api";

export default function SignupPage() {
  const { loginWithSignup, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isAuthenticated) {
      router.replace("/venue");
    }
  }, [isAuthenticated, router]);

  const [form, setForm] = useState({
    venue_name: "",
    slug: "",
    owner_email: "",
    owner_password: "",
    owner_stage_name: "",
    timezone: "UTC",
  });
  const [slugAvailable, setSlugAvailable] = useState<boolean | null>(null);
  const [checkingSlug, setCheckingSlug] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const update = (field: keyof typeof form, value: string) => {
    setForm((prev) => ({ ...prev, [field]: value }));
    if (field === "slug") {
      setSlugAvailable(null);
    }
  };

  const checkSlug = async () => {
    if (!form.slug || form.slug.length < 2) return;
    setCheckingSlug(true);
    try {
      const res = await checkSlugAvailable(form.slug.toLowerCase().replace(/\s+/g, "-"));
      setSlugAvailable(res.available);
    } catch {
      setSlugAvailable(null);
    } finally {
      setCheckingSlug(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (slugAvailable === false) {
      setError("That venue URL is already taken.");
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        slug: form.slug.toLowerCase().replace(/\s+/g, "-"),
      };
      const data = await signupVenue(payload);
      await loginWithSignup(data);
    } catch (err: any) {
      setError(err?.message || "Signup failed");
    } finally {
      setSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted-foreground border-t-primary" />
      </div>
    );
  }

  if (isAuthenticated) {
    return (
      <div className="flex h-screen w-full items-center justify-center">
        <div className="text-muted-foreground">
          Already logged in.{" "}
          <Link href="/venue" className="underline">Go to venue</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-background px-4 py-12">
      <Card className="w-full max-w-lg">
        <CardHeader className="text-center">
          <div className="mb-2 flex justify-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Music className="h-5 w-5" />
            </div>
          </div>
          <CardTitle>Create your venue</CardTitle>
          <CardDescription>Start your 30-day hosting software trial today</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="venue_name">Venue Name</Label>
              <Input
                id="venue_name"
                required
                value={form.venue_name}
                onChange={(e) => update("venue_name", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="slug">Venue URL Slug</Label>
              <div className="flex gap-2">
                <Input
                  id="slug"
                  required
                  pattern="[a-z0-9-]+"
                  value={form.slug}
                  onChange={(e) => update("slug", e.target.value)}
                  onBlur={checkSlug}
                  placeholder="my-venue"
                />
                <Button type="button" variant="outline" onClick={checkSlug} disabled={checkingSlug}>
                  {checkingSlug ? <Loader2 className="h-4 w-4 animate-spin" /> : "Check"}
                </Button>
              </div>
              {slugAvailable === true && (
                <p className="text-xs text-green-600">Available</p>
              )}
              {slugAvailable === false && (
                <p className="text-xs text-destructive">Already taken</p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="owner_email">Owner Email</Label>
              <Input
                id="owner_email"
                type="email"
                required
                value={form.owner_email}
                onChange={(e) => update("owner_email", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="owner_password">Password</Label>
              <Input
                id="owner_password"
                type="password"
                minLength={8}
                required
                value={form.owner_password}
                onChange={(e) => update("owner_password", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="owner_stage_name">Your Stage Name</Label>
              <Input
                id="owner_stage_name"
                required
                value={form.owner_stage_name}
                onChange={(e) => update("owner_stage_name", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="timezone">Timezone</Label>
              <Input
                id="timezone"
                value={form.timezone}
                onChange={(e) => update("timezone", e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Creating venue..." : "Create Venue"}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-muted-foreground">
            Already have a venue?{" "}
            <Link href="/auth/login" className="underline hover:text-primary">Log in</Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
