"use client";

import { useEffect, useState, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Download, Copy, QrCode } from "lucide-react";

interface VenueQrCardProps {
  venueCode: string;
  venueName: string;
}

export function VenueQrCard({ venueCode, venueName }: VenueQrCardProps) {
  const [svgString, setSvgString] = useState("");
  const svgRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    import("qrcode").then((QRCode) => {
      const payload = `SCALES:${venueCode}`;
      QRCode.toString(payload, { type: "svg", margin: 2, width: 256 })
        .then((svg: string) => setSvgString(svg))
        .catch(() => setSvgString(""));
    });
  }, [venueCode]);

  const handleDownload = () => {
    if (!svgString) return;
    const blob = new Blob([svgString], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${venueCode.toLowerCase()}-qr.svg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleCopyCode = () => {
    navigator.clipboard.writeText(venueCode);
  };

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <QrCode className="h-5 w-5" />
          Venue Check-In QR
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col items-center gap-4">
          {svgString ? (
            <div
              ref={svgRef}
              className="rounded-lg border bg-white p-4"
              dangerouslySetInnerHTML={{ __html: svgString }}
            />
          ) : (
            <div className="flex h-64 w-64 items-center justify-center rounded-lg border bg-muted">
              <span className="text-sm text-muted-foreground">Generating QR code...</span>
            </div>
          )}

          <div className="text-center">
            <p className="text-lg font-bold tracking-wider">{venueCode}</p>
            <p className="text-sm text-muted-foreground">{venueName}</p>
          </div>
        </div>

        <div className="flex gap-2">
          <Button
            variant="outline"
            className="flex-1"
            onClick={handleCopyCode}
          >
            <Copy className="mr-2 h-4 w-4" />
            Copy Code
          </Button>
          <Button
            variant="outline"
            className="flex-1"
            onClick={handleDownload}
            disabled={!svgString}
          >
            <Download className="mr-2 h-4 w-4" />
            Download SVG
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
