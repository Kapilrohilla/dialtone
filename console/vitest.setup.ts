import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";
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

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  document.cookie.split(";").forEach((c) => {
    document.cookie = `${c.split("=")[0].trim()}=; max-age=0; path=/`;
  });
  document.documentElement.removeAttribute("data-theme");
  vi.unstubAllGlobals();
});
afterAll(() => server.close());
