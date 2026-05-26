"use client";

export default function QueuePage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Live Queue</h1>
      <p className="text-muted-foreground">Real-time queue management for tonight's show.</p>
      <div className="mt-6 rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <p className="font-medium">Queue Table Component</p>
        <p className="text-sm mt-1">Renders a sortable live queue table with approve/reject/skip/complete actions.</p>
      </div>
    </div>
  );
}
