"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { Button, StateBlock } from "@/components/ui";
import { formatPhone } from "@/lib/format";
import { useDashboard, useLiveCalls, useMe } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { LiveCall } from "@/lib/types";
import { LiveCallView } from "./_components/LiveCallView";
import { LiveList } from "./_components/LiveList";
import styles from "./live.module.css";

const POLL_MS = 2000;
const CALL_SERVER_DOWN = "Couldn't reach the call server.";

/** Re-renders every second so the timers tick. */
function useNow(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

export default function LivePage() {
  // useSearchParams needs a Suspense boundary for the static build.
  return (
    <Suspense>
      <Live />
    </Suspense>
  );
}

function EmptyLive() {
  const { data } = useDashboard();
  const phone = data?.live_agent?.phone_number;
  return (
    <StateBlock
      state="empty"
      title="No calls right now."
      body={
        <>
          Calls show up here as soon as someone calls {phone ? <span className="mono">{formatPhone(phone)}</span> : "your number"}.
        </>
      }
    />
  );
}

type Seen = { call: LiveCall; at: Date };

function Live() {
  const router = useRouter();
  const initial = useSearchParams().get("room");
  const { data: calls, dataUpdatedAt, isError, refetch } = useLiveCalls(POLL_MS);
  const { data: me } = useMe();
  const now = useNow();
  const [picked, setPicked] = useState<string | null>(initial);
  const [seen, setSeen] = useState<Record<string, Seen>>({});

  // Remember each call as last seen live, so a call that hangs up stays on screen.
  useEffect(() => {
    if (!calls) return;
    const at = new Date(dataUpdatedAt);
    setSeen((prev) => {
      const next = { ...prev };
      for (const call of calls) next[call.room] = { call, at };
      return next;
    });
  }, [calls, dataUpdatedAt]);

  // With no ?room= (or one that was never live here), stay on the first call that was on screen even if the
  // list reorders or that call hangs up.
  const firstRoom = calls?.[0]?.room;
  const unknownPick = picked !== null && calls !== undefined && !calls.some((c) => c.room === picked) && !seen[picked];
  useEffect(() => {
    if (!firstRoom || !(picked === null || unknownPick)) return;
    setPicked(firstRoom);
    if (unknownPick) router.replace(`/live?room=${encodeURIComponent(firstRoom)}`, { scroll: false });
  }, [picked, unknownPick, firstRoom, router]);

  const room = picked ?? firstRoom;
  const live = calls?.find((c) => c.room === room);
  const last = room ? seen[room] : undefined;
  // `calls` is the last successful answer (a failed poll keeps it), so a call absent from it has ended and stays ended.
  const ended = !live && calls !== undefined && last !== undefined;
  // A ?room= that was never live here (stale link) falls back to the first call.
  const shown = live ?? last?.call ?? (unknownPick ? calls?.[0] : undefined);

  function select(next: string) {
    setPicked(next);
    router.replace(`/live?room=${encodeURIComponent(next)}`, { scroll: false });
  }

  let body;
  if (calls === undefined && isError) {
    body = <StateBlock state="error" title={CALL_SERVER_DOWN} onRetry={() => refetch()} />;
  } else if (calls === undefined) {
    body = <StateBlock state="loading" title="Loading calls" />;
  } else if (calls.length === 0 && !shown) {
    body = <EmptyLive />;
  }

  return (
    <>
      <TopBar title="Live calls" />
      {body ? (
        <div className={styles.empty}>{body}</div>
      ) : (
        <div className={styles.layout}>
          <nav aria-label="Calls in progress" className={styles.list}>
            {isError && (
              <p role="alert" className={styles.notice}>
                {CALL_SERVER_DOWN}{" "}
                <Button variant="text" size="sm" onClick={() => refetch()}>Try again</Button>
              </p>
            )}
            <LiveList calls={calls ?? []} selected={ended ? undefined : shown?.room} now={now} onSelect={select} />
          </nav>
          {shown && (
            <LiveCallView
              key={shown.room}
              call={shown}
              ended={ended}
              now={ended && last ? last.at : now}
              canAct={canEdit(me?.role)}
            />
          )}
        </div>
      )}
    </>
  );
}
