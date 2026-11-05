"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/** Unsaved-changes guard for screens with an explicit Save (knowledge, workflows). While `dirty`, closing the tab
 *  asks the browser's question and in-app links wait for the person's answer in a dialog. `guarded(action)` does
 *  the same for the screen's own actions. `pending` is the action waiting: `leave` runs it, `stay` drops it. */
export function useLeaveGuard(dirty: boolean) {
  const router = useRouter();
  const [pending, setPending] = useState<(() => void) | null>(null);
  const latest = useRef(dirty);
  useEffect(() => {
    latest.current = dirty;
  });

  useEffect(() => {
    function onBeforeUnload(e: BeforeUnloadEvent) {
      if (!latest.current) return;
      e.preventDefault();
      e.returnValue = "";
    }
    function onClick(e: MouseEvent) {
      if (!latest.current || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element).closest?.("a[href]");
      const href = a?.getAttribute("href");
      if (!a || !href?.startsWith("/") || a.getAttribute("target") === "_blank") return;
      e.preventDefault();
      e.stopPropagation();
      setPending(() => () => router.push(href));
    }
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [router]);

  /** Runs `action` now, or once the person agrees to discard unsaved changes. */
  function guarded(action: () => void) {
    if (latest.current) setPending(() => action);
    else action();
  }

  function leave() {
    const go = pending;
    setPending(null);
    go?.();
  }

  return { pending, guarded, stay: () => setPending(null), leave };
}
