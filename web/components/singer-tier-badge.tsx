import { cn } from "@/lib/utils";
import { SingerLoyaltyTier } from "@/lib/types";

const tierStyles: Record<SingerLoyaltyTier, string> = {
  none: "bg-gray-100 text-gray-800 border-gray-300",
  bronze: "bg-amber-100 text-amber-800 border-amber-300",
  silver: "bg-slate-100 text-slate-800 border-slate-300",
  gold: "bg-yellow-100 text-yellow-800 border-yellow-300",
  platinum: "bg-teal-100 text-teal-800 border-teal-300",
};

export function SingerTierBadge({ tier }: { tier: SingerLoyaltyTier }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium uppercase tracking-wide",
        tierStyles[tier] ?? tierStyles.none
      )}
    >
      {tier}
    </span>
  );
}
