"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";
import {
  Music,
  Mic2,
  ListMusic,
  BarChart3,
  ShoppingCart,
  Settings,
  Users,
  Monitor,
  Building2,
  LayoutDashboard,
  SlidersHorizontal,
} from "lucide-react";

const navItems = [
  { label: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
  { label: "Queue", href: "/queue", icon: ListMusic },
  { label: "Singers", href: "/singers", icon: Users },
  { label: "Songs", href: "/songs", icon: Music },
  { label: "KJ Devices", href: "/kj-devices", icon: Monitor },
  { label: "Analytics", href: "/analytics", icon: BarChart3 },
  { label: "Commerce", href: "/commerce", icon: ShoppingCart },
  { label: "Venue", href: "/venue", icon: Building2 },
  { label: "Settings", href: "/settings", icon: SlidersHorizontal },
];

const adminItems = [
  { label: "Admin", href: "/admin", icon: Settings },
];

export function SidebarContent({ onNav }: { onNav?: () => void }) {
  const pathname = usePathname();
  const { user } = useAuth();

  const isAdmin = user?.role === "admin";

  const NavLink = ({
    item,
    admin = false,
  }: {
    item: (typeof navItems)[number];
    admin?: boolean;
  }) => {
    const active = pathname === item.href || pathname.startsWith(item.href + "/");
    const Icon = item.icon;
    return (
      <Link
        href={item.href}
        onClick={onNav}
        className={cn(
          "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
          active
            ? "bg-primary/10 text-primary"
            : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
          admin && "text-sidebar-foreground/70"
        )}
      >
        <Icon className="h-4 w-4" />
        {item.label}
      </Link>
    );
  };

  return (
    <nav className="flex flex-col gap-1 p-3">
      <div className="mb-4 px-3 py-2">
        <span className="text-lg font-bold tracking-tight text-sidebar-foreground">
          Scales Portal
        </span>
      </div>

      <div className="flex flex-col gap-1">
        {navItems.map((item) => (
          <NavLink key={item.href} item={item} />
        ))}
      </div>

      {isAdmin && (
        <>
          <div className="my-3 border-t border-sidebar-border" />
          <div className="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Administration
          </div>
          <div className="flex flex-col gap-1">
            {adminItems.map((item) => (
              <NavLink key={item.href} item={item} admin />
            ))}
          </div>
        </>
      )}
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="hidden h-screen w-64 flex-shrink-0 border-r bg-sidebar text-sidebar-foreground md:flex">
      <SidebarContent />
    </aside>
  );
}
