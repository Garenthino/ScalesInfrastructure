"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Mail, CheckCircle } from "lucide-react";

export function WaitlistForm({ platform }: { platform: string }) {
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    const subject = encodeURIComponent(`Scales 0.3 beta waitlist — ${platform}`);
    const body = encodeURIComponent(
      `Hi Scales team,\n\nPlease add me to the ${platform} beta waitlist.\n\nEmail: ${email}\n\nThanks!`
    );
    window.location.href = `mailto:beta@dancingdragonservices.com?subject=${subject}&body=${body}`;
    setSubmitted(true);
  };

  if (submitted) {
    return (
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-4 text-sm text-primary">
        <div className="flex items-start gap-2">
          <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            Request sent. We will email {email} when the {platform} beta is ready.
          </p>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="space-y-1.5">
        <Label htmlFor={`waitlist-email-${platform}`} className="text-xs">
          Email address
        </Label>
        <Input
          id={`waitlist-email-${platform}`}
          type="email"
          required
          placeholder="you@venue.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <Button type="submit" variant="outline" className="w-full gap-2">
        <Mail className="h-4 w-4" />
        Join {platform} beta waitlist
      </Button>
      <p className="text-xs text-muted-foreground">
        Opens your email app with a pre-filled request. We will reply when the beta is available.
      </p>
    </form>
  );
}
