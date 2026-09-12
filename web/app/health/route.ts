import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const res = await fetch("http://api:8000/health", { cache: "no-store" });
    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { status: "degraded", error: err instanceof Error ? err.message : String(err) },
      { status: 503 }
    );
  }
}
