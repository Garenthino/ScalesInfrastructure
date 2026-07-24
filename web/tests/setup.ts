import { vi, afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Provide a minimal Next.js app-router context so useRouter() in AuthProvider works in jsdom.
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    pathname: "/",
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

// jsdom does not implement ResizeObserver; Radix ScrollArea (used in conflict dialog) needs it.
class ResizeObserverPolyfill {
  observe() {}
  unobserve() {}
  disconnect() {}
}
Object.defineProperty(globalThis, "ResizeObserver", {
  value: ResizeObserverPolyfill,
  writable: true,
  configurable: true,
});

// happy-dom/jsdom crypto is partial; ensure randomUUID is present for repair sync idempotency keys.
Object.defineProperty(globalThis, "crypto", {
  value: {
    ...globalThis.crypto,
    randomUUID: () => "idemp-key-test",
  },
  writable: true,
  configurable: true,
});

// Clean up rendered DOM after each test to avoid leaks and cross-test contamination.
afterEach(() => {
  cleanup();
});