"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

/** While `dirty`, closing the tab asks the browser's question and in-app links ask in a dialog first.
 *  `pending` is the navigation waiting on the answer: run it to leave, clear it to stay. */
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

  return { pending, stay: () => setPending(null), leave: () => {
    const go = pending;
    setPending(null);
    go?.();
  } };
}
