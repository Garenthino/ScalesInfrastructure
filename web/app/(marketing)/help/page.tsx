import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import {
  Search,
  HelpCircle,
  QrCode,
  CreditCard,
  Monitor,
  Smartphone,
  ArrowRight,
} from "lucide-react";

const FAQS = [
  {
    value: "trial",
    icon: Monitor,
    question: "Is there a free trial?",
    answer:
      "The KJ hosting software includes a 30-day free trial. The venue portal and Android singer app are paid from the start, though sales-assisted accounts can be comped during onboarding.",
  },
  {
    value: "setup-time",
    icon: QrCode,
    question: "How long does it take to set up a venue?",
    answer:
      "Self-serve signup takes under 5 minutes. After creating your venue you'll get a venue code and QR card that singers can use to check in immediately.",
  },
  {
    value: "singer-app",
    icon: Smartphone,
    question: "Do singers need to install an app?",
    answer:
      "Singers can scan the venue QR code with any phone camera. For the best experience we recommend the Scales Android app, which supports favorites, history, and loyalty tracking.",
  },
  {
    value: "payment",
    icon: CreditCard,
    question: "How does billing work?",
    answer:
      "Venues subscribe via Stripe. Owners can upgrade, downgrade, and manage payment methods from the Billing page. Enterprise and multi-venue accounts can be invoiced.",
  },
  {
    value: "offline",
    icon: Monitor,
    question: "Does the KJ app work offline?",
    answer:
      "Yes. The KJ desktop app is offline-first and syncs to the cloud when connected. If the internet drops, your rotation and queue stay available locally.",
  },
  {
    value: "support",
    icon: HelpCircle,
    question: "How do I get support?",
    answer:
      "Use the Contact page to reach our team, or ask your sales rep if you were provisioned through the sales portal. Platform admins can also impersonate venue owners for live troubleshooting.",
  },
];

export const metadata = {
  title: "Help Center — Scales Karaoke",
  description:
    "Frequently asked questions about Scales karaoke: trials, setup, billing, the singer app, and the KJ desktop software.",
};

export default function HelpPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-20">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">Help Center</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          Answers to the most common questions about setup, billing, and running
          a show with Scales.
        </p>
      </div>

      <div className="mt-10 flex flex-col items-center gap-4 sm:flex-row">
        <div className="relative w-full sm:max-w-md">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search help articles..."
            className="pl-9"
            aria-label="Search help articles"
          />
        </div>
        <Link href="/contact" className="w-full sm:w-auto">
          <Button variant="outline" className="w-full gap-2 sm:w-auto">
            Contact support <ArrowRight className="h-4 w-4" />
          </Button>
        </Link>
      </div>

      <div className="mt-12 grid gap-4">
        <Accordion type="single" collapsible className="w-full">
          {FAQS.map((faq) => (
            <AccordionItem key={faq.value} value={faq.value} className="border-b">
              <AccordionTrigger className="py-4 text-left hover:no-underline">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <faq.icon className="h-4 w-4" />
                  </div>
                  <span className="font-medium">{faq.question}</span>
                </div>
              </AccordionTrigger>
              <AccordionContent className="pb-4 pl-11 text-muted-foreground">
                {faq.answer}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </div>

      <div className="mt-12 grid gap-6 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Getting started</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>Create your venue, download the QR card, and add the KJ desktop API key.</p>
            <Link
              href="/auth/signup"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              Sign up <ArrowRight className="h-3 w-3" />
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Sales</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>Multi-venue pricing, demos, and custom onboarding for enterprise groups.</p>
            <Link
              href="/sales-portal"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              Sales portal <ArrowRight className="h-3 w-3" />
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Affiliates</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>Promote Scales and earn on every venue that signs up with your code.</p>
            <Link
              href="/affiliates"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              Learn more <ArrowRight className="h-3 w-3" />
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
