import Link from "next/link";
import { Music } from "lucide-react";
import { ReactNode } from "react";

export default function MarketingLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-background text-foreground">
      <header className="border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
          <Link href="/" className="flex items-center gap-2 font-bold text-xl">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Music className="h-4 w-4" />
            </div>
            Scales
          </Link>
          <nav className="hidden gap-6 text-sm font-medium md:flex">
            <Link href="/features" className="hover:text-primary">Features</Link>
            <Link href="/pricing" className="hover:text-primary">Pricing</Link>
            <Link href="/help" className="hover:text-primary">Help</Link>
            <Link href="/contact" className="hover:text-primary">Contact</Link>
            <Link href="/affiliates" className="hover:text-primary">Affiliates</Link>
          </nav>
          <div className="flex items-center gap-4">
            <Link href="/auth/login" className="text-sm font-medium hover:text-primary">Log in</Link>
            <Link
              href="/auth/signup"
              className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Sign up
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t bg-muted/40">
        <div className="mx-auto max-w-7xl px-4 py-8">
          <div className="grid gap-8 md:grid-cols-4">
            <div>
              <Link href="/" className="flex items-center gap-2 font-bold">
                <div className="flex h-6 w-6 items-center justify-center rounded bg-primary text-primary-foreground">
                  <Music className="h-3 w-3" />
                </div>
                Scales
              </Link>
              <p className="mt-2 text-sm text-muted-foreground">
                Karaoke hosting software, singer apps, and venue management.
              </p>
            </div>
            <div>
              <h4 className="font-semibold">Product</h4>
              <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                <li><Link href="/features" className="hover:text-foreground">Features</Link></li>
                <li><Link href="/pricing" className="hover:text-foreground">Pricing</Link></li>
                <li><Link href="/auth/signup" className="hover:text-foreground">Sign up</Link></li>
              </ul>
            </div>
            <div>
              <h4 className="font-semibold">Company</h4>
              <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                <li><Link href="/contact" className="hover:text-foreground">Contact</Link></li>
                <li><Link href="/sales-portal" className="hover:text-foreground">Sales Portal</Link></li>
                <li><Link href="/affiliates" className="hover:text-foreground">Affiliate Program</Link></li>
              </ul>
            </div>
            <div>
              <h4 className="font-semibold">Support</h4>
              <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
                <li><Link href="/help" className="hover:text-foreground">Help Center</Link></li>
                <li><Link href="/help#getting-started" className="hover:text-foreground">Getting Started</Link></li>
              </ul>
            </div>
          </div>
          <div className="mt-8 border-t pt-4 text-sm text-muted-foreground">
            © {new Date().getFullYear()} Scales Karaoke. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
}
