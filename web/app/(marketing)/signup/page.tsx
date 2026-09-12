import Link from "next/link";
import { redirect } from "next/navigation";

export default function MarketingSignupRedirect() {
  redirect("/auth/signup");
}
