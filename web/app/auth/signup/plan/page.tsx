import { Suspense } from "react";
import { Metadata } from "next";
import SignupPlanForm from "./signup-plan-form";

export const metadata: Metadata = {
  title: "Choose a plan — Scales Karaoke",
  description:
    "Select a Scales venue plan and start your subscription. The Windows KJ hosting software includes a 30-day free trial.",
};

export default function SignupPlanPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted-foreground border-t-primary" />
        </div>
      }
    >
      <SignupPlanForm />
    </Suspense>
  );
}
