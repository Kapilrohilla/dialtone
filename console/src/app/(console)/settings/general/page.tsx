"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { Button, Field, Panel, StateBlock, useToast } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { useInstance, useMe, useUpdateInstance } from "@/lib/queries";
import type { Instance } from "@/lib/types";
import styles from "../settings.module.css";

const PROJECT_NAME_MAX = 60;

/** Install-wide settings. Only a super admin (Django superuser) may change them; the server says 403 to anyone else. */
export default function GeneralSettingsPage() {
  const me = useMe();
  const instance = useInstance();

  let body: ReactNode;
  // Only a first load that failed replaces the page: a failed background refetch keeps the form.
  const meFailed = !me.data && me.isError;
  if (meFailed || (me.data?.is_superuser && !instance.data && instance.isError)) {
    const error = meFailed ? me.error : instance.error;
    body = (
      <StateBlock
        state="error"
        title="Could not load your settings"
        body={error instanceof ApiError ? error.detail : undefined}
        onRetry={() => (meFailed ? me.refetch() : instance.refetch())}
      />
    );
  } else if (!me.data) {
    body = <StateBlock state="loading" title="Loading" />;
  } else if (!me.data.is_superuser) {
    body = <StateBlock state="empty" title="You can't change these settings." body="Only a super admin can rename this install." />;
  } else if (!instance.data) {
    body = <StateBlock state="loading" title="Loading" />;
  } else {
    body = <GeneralForm instance={instance.data} />;
  }

  return (
    <>
      <TopBar title="General" />
      <div className={styles.page}>{body}</div>
    </>
  );
}

function GeneralForm({ instance }: { instance: Instance }) {
  const toast = useToast();
  const update = useUpdateInstance();
  const [draft, setDraft] = useState<string | null>(null);
  const [blank, setBlank] = useState(false);
  const value = draft ?? instance.project_name;
  const dirty = value.trim() !== instance.project_name;
  const serverError = update.error instanceof ApiError ? update.error.fields.project_name?.[0] : undefined;
  const error = blank ? "Enter a project name." : serverError;

  function save(e: FormEvent) {
    e.preventDefault();
    const name = value.trim();
    if (!name) {
      setBlank(true);
      return;
    }
    update.mutate(
      { project_name: name },
      {
        onSuccess: () => {
          setDraft(null);
          toast.show("Saved.", "ok");
        },
        onError: (err) => {
          if (!(err instanceof ApiError) || !err.fields.project_name) toast.show(err instanceof ApiError ? err.detail : "Could not save.", "bad");
        },
      },
    );
  }

  return (
    <form onSubmit={save} noValidate>
      <Panel>
        <section className={styles.section} aria-labelledby="project-h" style={{ borderBottom: 0, paddingBottom: 0 }}>
          <h2 id="project-h">Project</h2>
          <Field
            label="Project name"
            value={value}
            maxLength={PROJECT_NAME_MAX}
            error={error}
            hint="Shown in the sidebar, on the sign-in page and in the browser tab, for everyone on this install."
            onChange={(e) => {
              setDraft(e.target.value);
              setBlank(false);
              if (update.isError) update.reset();
            }}
          />
        </section>
      </Panel>
      <div className={styles.footer}>
        <Button variant="primary" type="submit" disabled={!dirty} loading={update.isPending}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
