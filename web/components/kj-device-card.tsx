"use client";

import { useState } from "react";
import { KJDevice } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Monitor,
  Wifi,
  WifiOff,
  Music,
  ListMusic,
  Unlink,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";

interface KJDeviceCardProps {
  device: KJDevice;
  onRevoke: (device: KJDevice) => void;
}

export function KJDeviceCard({ device, onRevoke }: KJDeviceCardProps) {
  const [showQueue, setShowQueue] = useState(false);

  const isOnline = device.status === "online";
  const lastSeen = device.last_seen_at
    ? formatDistanceToNow(new Date(device.last_seen_at), { addSuffix: true })
    : "Never";

  return (
    <Card className={isOnline ? "" : "opacity-75"}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2">
            <Monitor className="h-5 w-5 text-muted-foreground" />
            <CardTitle className="text-base">{device.name}</CardTitle>
            <Badge variant={isOnline ? "default" : "secondary"} className="text-xs">
              {isOnline ? (
                <span className="flex items-center gap-1">
                  <Wifi className="h-3 w-3" />
                  Online
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  <WifiOff className="h-3 w-3" />
                  Offline
                </span>
              )}
            </Badge>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
            onClick={() => onRevoke(device)}
          >
            <Unlink className="h-4 w-4 mr-1" />
            Revoke
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Last seen {lastSeen} · Connected {formatDistanceToNow(new Date(device.connected_at), { addSuffix: true })}
        </p>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Now Playing */}
        <div className="rounded-md bg-muted/50 p-3">
          <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-1">
            <Music className="h-4 w-4" />
            Now Playing
          </div>
          {device.now_playing ? (
            <div>
              <p className="font-medium truncate">
                {device.now_playing.song_title}
              </p>
              <p className="text-sm text-muted-foreground">
                Singer: {device.now_playing.singer_name}
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground italic">Nothing playing</p>
          )}
        </div>

        {/* Queue */}
        <div>
          <button
            onClick={() => setShowQueue((v) => !v)}
            className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-full"
          >
            <ListMusic className="h-4 w-4" />
            Queue ({device.queue.length})
            {showQueue ? (
              <ChevronUp className="h-3 w-3 ml-auto" />
            ) : (
              <ChevronDown className="h-3 w-3 ml-auto" />
            )}
          </button>

          {showQueue && (
            <div className="mt-2 space-y-1">
              {device.queue.length === 0 ? (
                <p className="text-sm text-muted-foreground italic pl-6">Queue is empty</p>
              ) : (
                device.queue.map((item) => (
                  <div
                    key={`${device.device_id}-${item.position}`}
                    className="flex items-center gap-3 rounded-sm px-3 py-2 text-sm bg-muted/30"
                  >
                    <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-xs font-medium text-primary">
                      {item.position + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="truncate font-medium">{item.song_title}</p>
                      <p className="text-xs text-muted-foreground truncate">
                        {item.singer_name}
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
