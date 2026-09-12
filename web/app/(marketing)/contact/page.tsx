import { Metadata } from "next";
import ContactForm, { ContactSidebar } from "./contact-form";

export const metadata: Metadata = {
  title: "Contact — Scales Karaoke",
  description:
    "Get in touch with the Scales team for sales, support, or partnership questions.",
};

export default function ContactPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-20">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight">Contact us</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          Questions about sales, support, or partnerships? Send us a message and
          we&apos;ll get back to you within one business day.
        </p>
      </div>

      <div className="mt-12 grid gap-8 lg:grid-cols-3">
        <ContactForm />
        <ContactSidebar />
      </div>
    </div>
  );
}
