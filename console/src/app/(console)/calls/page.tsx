"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { Button, StateBlock } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { shiftDay, todayIn } from "@/lib/format";
import { callsQuery, useCalls, useMe, type CallFilters } from "@/lib/queries";
import { CallSlideOver } from "./_components/CallSlideOver";
import { CallsTable } from "./_components/CallsTable";
import { DateRange } from "./_components/DateRange";
import { Filters } from "./_components/Filters";
import styles from "./calls.module.css";

const DEFAULT_TZ = "Asia/Kolkata";
const TEXT_FILTERS = ["q", "outcome", "agent", "mood", "city"] as const;

export default function CallsPage() {
  // useSearchParams needs a Suspense boundary for the static build.
  return (
    <Suspense>
      <Calls />
    </Suspense>
  );
}

function Calls() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: me, isError: meFailed } = useMe();
  const timeZone = me?.preferences.time_zone ?? DEFAULT_TZ;
  // "Today" is the user's day, so the default range waits for the time zone (or for the profile to fail).
  const zoneKnown = me !== undefined || meFailed;

  const urlFrom = params.get("from") ?? "";
  const urlTo = params.get("to") ?? "";
  const today = todayIn(timeZone);
  const filters: CallFilters = {
    q: params.get("q") ?? "",
    outcome: params.get("outcome") ?? "",
    agent: params.get("agent") ?? "",
    mood: params.get("mood") ?? "",
    city: params.get("city") ?? "",
    from: urlFrom || shiftDay(today, -6),
    to: urlTo || today,
    page: Math.max(1, Number.parseInt(params.get("page") ?? "1", 10) || 1),
  };
  const room = params.get("room");

  const href = (next: CallFilters, withRoom = room) => {
    const query = callsQuery(next);
    const roomPart = withRoom ? `${query ? "&" : ""}room=${encodeURIComponent(withRoom)}` : "";
    return `/calls${query || roomPart ? "?" : ""}${query}${roomPart}`;
  };

  // Put the default range in the URL so the page can be shared and the back button keeps it.
  const missingRange = !urlFrom || !urlTo;
  useEffect(() => {
    if (zoneKnown && missingRange) router.replace(href(filters), { scroll: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoneKnown, missingRange]);

  /** Changing a filter goes back to page 1. `replace` keeps typing from filling the history. */
  function change(patch: Partial<CallFilters>, mode: "push" | "replace" = "push") {
    const next = { ...filters, page: 1, ...patch };
    router[mode](href(next), { scroll: false });
  }

  const anyFilter = TEXT_FILTERS.some((key) => filters[key] !== "");
  const clearFilters = () => router.push(href({ from: filters.from, to: filters.to }), { scroll: false });

  const calls = useCalls(filters, { enabled: zoneKnown });
  // An empty list with only the default dates could still be a workspace with older calls: ask for all of them.
  const noneInRange = calls.data?.count === 0 && !anyFilter;
  const ever = useCalls({}, { enabled: noneInRange });
  const exportHref = `/api/calls/export.csv?${callsQuery({ ...filters, page: undefined })}`;

  const filterError = calls.error instanceof ApiError && calls.error.status === 400 ? calls.error.detail : null;

  let body;
  if (filterError) {
    body = null;
  } else if (calls.isError) {
    body = <StateBlock state="error" title="Could not load calls" body={calls.error instanceof ApiError ? calls.error.detail : undefined} onRetry={() => calls.refetch()} />;
  } else if (!calls.data) {
    body = <StateBlock state="loading" title="Loading calls" />;
  } else if (calls.data.count === 0) {
    const neverAnyCalls = noneInRange && ever.data?.count === 0;
    body = noneInRange && !ever.data && !ever.isError ? (
      <StateBlock state="loading" title="Loading calls" />
    ) : neverAnyCalls ? (
      <StateBlock state="empty" title="No calls yet." />
    ) : (
      <StateBlock
        state="empty"
        title="No calls match these filters."
        action={anyFilter ? <Button variant="text" onClick={clearFilters}>Clear filters</Button> : undefined}
      />
    );
  } else {
    body = (
      <CallsTable
        page={calls.data}
        timeZone={timeZone}
        stale={calls.isPlaceholderData}
        onOpen={(next) => router.push(href(filters, next), { scroll: false })}
        onPage={(page) => change({ page })}
      />
    );
  }

  return (
    <>
      <TopBar
        title="Call history"
        secondary={
          <>
            <DateRange from={filters.from ?? ""} to={filters.to ?? ""} today={today} onChange={(from, to) => change({ from, to })} />
            <a href={exportHref} download className={styles.export}>Export</a>
          </>
        }
      />
      <div className={styles.page}>
        <Filters filters={filters} anyFilter={anyFilter} error={filterError} onChange={change} onClear={clearFilters} />
        {body}
      </div>
      {room && <CallSlideOver key={room} room={room} timeZone={timeZone} onClose={() => router.replace(href(filters, null), { scroll: false })} />}
    </>
  );
}
