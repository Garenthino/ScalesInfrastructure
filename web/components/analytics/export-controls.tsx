"use client";

import { useRef } from "react";
import { toPng } from "html-to-image";
import { Button } from "@/components/ui/button";
import { Download, ImageIcon } from "lucide-react";

export function ExportControls({
  elementRef,
  csvData,
  filename = "analytics",
}: {
  elementRef: React.RefObject<HTMLDivElement | null>;
  csvData?: Array<Record<string, string | number>>;
  filename?: string;
}) {
  const exportPng = async () => {
    if (!elementRef.current) return;
    const dataUrl = await toPng(elementRef.current, { cacheBust: true, pixelRatio: 2 });
    const link = document.createElement("a");
    link.download = `${filename}.png`;
    link.href = dataUrl;
    link.click();
  };

  const exportCsv = () => {
    if (!csvData || csvData.length === 0) return;
    const headers = Object.keys(csvData[0]);
    const rows = csvData.map((row) => headers.map((h) => String(row[h])));
    const csv = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${filename}.csv`;
    link.click();
  };

  return (
    <div className="flex items-center gap-2">
      <Button variant="outline" size="sm" onClick={exportPng}>
        <ImageIcon className="mr-1.5 h-3.5 w-3.5" />
        PNG
      </Button>
      {csvData && (
        <Button variant="outline" size="sm" onClick={exportCsv}>
          <Download className="mr-1.5 h-3.5 w-3.5" />
          CSV
        </Button>
      )}
    </div>
  );
}
