"use client";

export default function CommercePage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Commerce</h1>
      <p className="text-muted-foreground">Merchandise, orders, and loyalty management.</p>
      <div className="mt-6 rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <p className="font-medium">Products & Orders</p>
        <p className="text-sm mt-1">Renders tabs for product management and order tracking with loyalty admin.</p>
      </div>
    </div>
  );
}
