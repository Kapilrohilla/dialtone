"use client";

import Link from "next/link";
import { StateBlock, useToast } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { useDashboard, useMarkHandled, useMe } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import { LiveAgentLine } from "./_components/LiveAgentLine";
import { NeedsPerson } from "./_components/NeedsPerson";
import { OutcomesWeek } from "./_components/OutcomesWeek";
import { Readings } from "./_components/Readings";
import styles from "./_components/dashboard.module.css";

export default function DashboardPage() {
  const { data, isError, error, refetch } = useDashboard();
  const { data: me } = useMe();
  const markHandled = useMarkHandled();
  const toast = useToast();

  const callBack = (room: string) => {
    markHandled.mutate(
      { room, handled: true },
      {
        onSuccess: () =>
          toast.show("Marked as handled.", "ok", { label: "Undo", onClick: () => markHandled.mutate({ room, handled: false }) }),
        onError: (e) => toast.show(e instanceof ApiError ? e.detail : "Could not mark as handled.", "bad"),
      },
    );
  };

  return (
    <>
      <TopBar title="Today" primary={<Link href="/live" className={styles.primaryLink}>Open live calls</Link>} />
      <div className={styles.page}>
        {isError ? (
          <StateBlock state="error" title="Could not load the dashboard" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
        ) : (
          <>
            <Readings data={data} />
            <div className={styles.columns}>
              <NeedsPerson rows={data?.needs_person} canCallBack={canEdit(me?.role)} timeZone={me?.preferences.time_zone ?? "Asia/Kolkata"} onCallBack={callBack} />
              <OutcomesWeek rows={data?.outcomes_week} />
            </div>
            <LiveAgentLine loading={!data} agent={data?.live_agent} />
          </>
        )}
      </div>
    </>
  );
}
