"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Field, Panel, Segmented, StateBlock, Switch, useToast } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { useMe, useUpdateMe, type MeUpdate } from "@/lib/queries";
import { applyAppearance } from "@/lib/theme";
import type { Appearance, Me, Preferences } from "@/lib/types";
import { PasswordDialog } from "./_components/PasswordDialog";
import styles from "./settings.module.css";

type Draft = { name?: string; phone?: string } & Partial<Preferences>;

const APPEARANCES: { value: Appearance; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "Match system" },
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase() || "?";
}

function timeZones(current: string): string[] {
  let all: string[] = [];
  try {
    all = Intl.supportedValuesOf("timeZone");
  } catch {
    all = [];
  }
  return all.includes(current) ? all : [current, ...all];
}

/** The fields that differ from what is saved, shaped for PATCH /api/me. */
function changesFrom(me: Me, draft: Draft): MeUpdate {
  const out: MeUpdate = {};
  const name = draft.name?.trim();
  if (name !== undefined && name !== me.name) out.name = name;
  if (draft.phone !== undefined && draft.phone.trim() !== me.phone) out.phone = draft.phone.trim();
  const prefs: Partial<Preferences> = {};
  for (const key of ["appearance", "notify_needs_person", "notify_daily_summary", "time_zone"] as const) {
    const value = draft[key];
    if (value !== undefined && value !== me.preferences[key]) (prefs as Record<string, unknown>)[key] = value;
  }
  if (Object.keys(prefs).length) out.preferences = prefs;
  return out;
}

export default function ProfilePage() {
  const { data: me, isError, error, refetch } = useMe();
  // Only a first load that failed replaces the form: a failed background refetch keeps it and its edits.
  if (!me) {
    return (
      <>
        <TopBar title="Settings" />
        <div className={styles.page}>
          {isError ? (
            <StateBlock state="error" title="Could not load your settings" body={error instanceof ApiError ? error.detail : undefined} onRetry={() => refetch()} />
          ) : (
            <StateBlock state="loading" title="Loading" />
          )}
        </div>
      </>
    );
  }
  return <ProfileForm me={me} />;
}

function ProfileForm({ me }: { me: Me }) {
  const toast = useToast();
  const update = useUpdateMe();
  const [draft, setDraft] = useState<Draft>({});
  const [passwordOpen, setPasswordOpen] = useState(false);
  const saved = me.preferences;
  const value = { name: draft.name ?? me.name, phone: draft.phone ?? me.phone, ...saved, ...stripUndefined(draft) };
  const changes = changesFrom(me, draft);
  const dirty = Object.keys(changes).length > 0;
  const nameBlank = value.name.trim() === "";
  const zones = useMemo(() => timeZones(value.time_zone), [value.time_zone]);
  const fieldErrors = update.error instanceof ApiError ? update.error.fields : {};

  // Leaving with a previewed theme that was never saved puts the saved one back.
  const savedAppearance = useRef(saved.appearance);
  useEffect(() => {
    savedAppearance.current = saved.appearance;
  }, [saved.appearance]);
  useEffect(() => () => applyAppearance(savedAppearance.current), []);

  const set = (patch: Draft) => setDraft((d) => ({ ...d, ...patch }));

  function pickAppearance(a: Appearance) {
    applyAppearance(a);
    set({ appearance: a });
  }

  function cancel() {
    applyAppearance(saved.appearance);
    update.reset();
    setDraft({});
  }

  function save() {
    update.mutate(changes, {
      onSuccess: () => {
        setDraft({});
        toast.show("Saved.", "ok");
      },
      onError: (e) => {
        if (!(e instanceof ApiError) || Object.keys(e.fields).length === 0) toast.show(e instanceof ApiError ? e.detail : "Could not save.", "bad");
      },
    });
  }

  return (
    <>
      <TopBar title="Settings" />
      <div className={styles.page}>
        <Panel>
          <section className={styles.section} aria-labelledby="profile-h">
            <h2 id="profile-h">Profile</h2>
            <div className={styles.identity}>
              <span className={styles.avatar} aria-hidden="true">{initials(value.name)}</span>
              <div>
                <div>{me.name}</div>
                <div className={styles.note}>{me.workspace.name}</div>
              </div>
            </div>
            <Field label="Full name" value={value.name} onChange={(e) => set({ name: e.target.value })} error={fieldErrors.name?.[0]} autoComplete="name" />
            <Field label="Work email" value={me.email} readOnly hint="Ask an owner to change your email." />
            <div>
              <Button variant="text" onClick={() => setPasswordOpen(true)}>
                Change password
              </Button>
            </div>
            <Field className={styles.mono} label="Phone" value={value.phone} onChange={(e) => set({ phone: e.target.value })} error={fieldErrors.phone?.[0]} inputMode="tel" autoComplete="tel" />
            <Field label="Time zone" control="select" value={value.time_zone} onChange={(e) => set({ time_zone: e.target.value })} error={fieldErrors.time_zone?.[0] ?? fieldErrors.preferences?.[0]}>
              {zones.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </Field>
          </section>

          <section id="appearance" className={styles.section} aria-labelledby="appearance-h">
            <h2 id="appearance-h">Appearance</h2>
            <Segmented label="Appearance" options={APPEARANCES} value={value.appearance} onChange={pickAppearance} />
            <p className={styles.note}>Switch the console between light and dark.</p>
          </section>

          <section className={styles.section} aria-labelledby="notifications-h" style={{ borderBottom: 0, paddingBottom: 0 }}>
            <h2 id="notifications-h">Notifications</h2>
            <div className={styles.switches}>
              <Switch label="Email me when a call needs a person" checked={value.notify_needs_person} onChange={(v) => set({ notify_needs_person: v })} />
              <Switch label="Send a daily summary" checked={value.notify_daily_summary} onChange={(v) => set({ notify_daily_summary: v })} />
            </div>
            <p className={styles.note}>Emails start once email sending is set up.</p>
          </section>
        </Panel>
        <div className={styles.footer}>
          <Button onClick={cancel}>
            Cancel
          </Button>
          <Button variant="primary" disabled={!dirty || nameBlank} loading={update.isPending} onClick={save}>
            Save changes
          </Button>
        </div>
      </div>
      <PasswordDialog open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </>
  );
}

function stripUndefined<T extends object>(o: T): Partial<T> {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v !== undefined)) as Partial<T>;
}
