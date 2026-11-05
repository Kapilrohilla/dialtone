import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
import { setParams, setRoute } from "@/test/navigation";
import { server } from "@/test/server";

vi.mock("next/navigation", async () => await import("@/test/navigation"));

// jsdom has no fetch and Node's fetch rejects relative URLs: resolve them against the test origin (see environmentOptions in vitest.config.ts).
const nodeFetch = globalThis.fetch;
globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) =>
  nodeFetch(typeof input === "string" && input.startsWith("/") ? new URL(input, "http://localhost:3000") : input, init)) as typeof fetch;

// jsdom's <dialog> has no showModal/close yet in some versions: give it the basics.
if (typeof HTMLDialogElement !== "undefined" && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal() {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close() {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}

// ProseMirror measures ranges to scroll the caret into view and hit-tests clicks with elementFromPoint;
// jsdom has neither. Empty rects and "no element there" keep it on its fallback paths.
if (!document.elementFromPoint) document.elementFromPoint = () => null;
if (!Range.prototype.getClientRects) {
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
}

// React Flow sizes the canvas with ResizeObserver and reads the zoom from a DOMMatrixReadOnly; jsdom has neither.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
if (typeof globalThis.DOMMatrixReadOnly === "undefined") {
  globalThis.DOMMatrixReadOnly = class {
    m22 = 1;
  } as unknown as typeof DOMMatrixReadOnly;
}

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  vi.clearAllMocks();
  setRoute("/");
  setParams({});
  document.cookie.split(";").forEach((c) => {
    document.cookie = `${c.split("=")[0].trim()}=; max-age=0; path=/`;
  });
  document.documentElement.removeAttribute("data-theme");
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
afterAll(() => server.close());
