"use client";

import { useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import { Button, Field, Panel, StateBlock, useToast } from "@/components/ui";
import { initials } from "@/components/shell/Sidebar";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { THEME_SWATCHES, THEMES } from "@/lib/palette";
import { useInstance, useMe, useRemoveLogo, useUpdateInstance, useUploadLogo } from "@/lib/queries";
import type { Instance, InstanceUpdate, Theme } from "@/lib/types";
import styles from "../settings.module.css";
import general from "./general.module.css";

const PROJECT_NAME_MAX = 60;
const LOGO_MAX_BYTES = 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/svg+xml"];
const LOGO_EXTENSIONS = /\.(png|jpe?g|svg)$/i;

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
    body = (
      <StateBlock
        state="empty"
        title="You can't change these settings."
        body="Only a super admin can change the name, logo and theme of this install."
      />
    );
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

/** A logo picked but not saved yet, or "remove". */
type LogoDraft = { file: File; preview: string } | "remove" | null;

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/** The reason a file can't be a logo, or null. The server checks again (and also that it is square). */
function logoProblem(file: File): string | null {
  if (!LOGO_TYPES.includes(file.type) && !LOGO_EXTENSIONS.test(file.name)) return "Upload a PNG, SVG or JPG.";
  if (file.size > LOGO_MAX_BYTES) return "The logo is too large; the limit is 1 MB.";
  if (file.size === 0) return "The file is empty.";
  return null;
}

function GeneralForm({ instance }: { instance: Instance }) {
  const toast = useToast();
  const update = useUpdateInstance();
  const upload = useUploadLogo();
  const remove = useRemoveLogo();
  const fileInput = useRef<HTMLInputElement>(null);

  const [draft, setDraft] = useState<string | null>(null);
  const [blank, setBlank] = useState(false);
  const [themeDraft, setThemeDraft] = useState<Theme | null>(null);
  const [logoDraft, setLogoDraft] = useState<LogoDraft>(null);
  const [logoError, setLogoError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const value = draft ?? instance.project_name;
  const theme = themeDraft ?? instance.theme;
  const nameDirty = value.trim() !== instance.project_name;
  const themeDirty = theme !== instance.theme;
  const logoDirty = logoDraft !== null && !(logoDraft === "remove" && !instance.logo_url);
  const dirty = nameDirty || themeDirty || logoDirty;

  const serverError = update.error instanceof ApiError ? update.error.fields.project_name?.[0] : undefined;
  const nameError = blank ? "Enter a project name." : serverError;
  const shownLogo = logoDraft === "remove" ? null : logoDraft ? logoDraft.preview : instance.logo_url;

  async function pick(file: File | undefined) {
    if (fileInput.current) fileInput.current.value = ""; // picking the same file again still fires onChange
    if (!file) return;
    const problem = logoProblem(file);
    if (problem) {
      setLogoError(problem);
      return;
    }
    setLogoError(null);
    upload.reset();
    try {
      setLogoDraft({ file, preview: await readAsDataUrl(file) });
    } catch {
      setLogoError("Could not read the file.");
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    const name = value.trim();
    if (!name) {
      setBlank(true);
      return;
    }
    const changes: InstanceUpdate = {};
    if (nameDirty) changes.project_name = name;
    if (themeDirty) changes.theme = theme;
    setSaving(true);
    try {
      if (Object.keys(changes).length) {
        await update.mutateAsync(changes);
        setDraft(null);
        setThemeDraft(null);
      }
      if (logoDraft && logoDraft !== "remove") await upload.mutateAsync(logoDraft.file);
      else if (logoDraft === "remove" && instance.logo_url) await remove.mutateAsync();
      setLogoDraft(null);
      toast.show("Saved.", "ok");
    } catch (err) {
      const fields = err instanceof ApiError ? err.fields : {};
      if (fields.file) setLogoError(fields.file[0]);
      else if (!fields.project_name) toast.show(err instanceof ApiError ? err.detail : "Could not save.", "bad");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} noValidate>
      <Panel>
        <section className={styles.section} aria-labelledby="project-h">
          <h2 id="project-h">Project</h2>
          <Field
            label="Project name"
            value={value}
            maxLength={PROJECT_NAME_MAX}
            error={nameError}
            hint="Shown in the sidebar, on the sign-in page and in the browser tab, for everyone on this install."
            onChange={(e) => {
              setDraft(e.target.value);
              setBlank(false);
              if (update.isError) update.reset();
            }}
          />
        </section>

        <section className={styles.section} aria-labelledby="logo-h">
          <h2 id="logo-h">Logo</h2>
          <div className={general.logoRow}>
            <span className={general.logoTile} data-testid="logo-preview">
              {/* eslint-disable-next-line @next/next/no-img-element -- a data URL or a small same-origin file */}
              {shownLogo ? <img src={shownLogo} alt="Logo preview" /> : <span aria-hidden="true">{initials(value.trim() || instance.project_name)}</span>}
            </span>
            <div className={general.logoActions}>
              <div className={general.buttons}>
                <Button onClick={() => fileInput.current?.click()} aria-describedby="logo-hint">
                  {shownLogo ? "Replace logo" : "Upload logo"}
                </Button>
                {shownLogo && (
                  <Button
                    variant="text"
                    onClick={() => {
                      setLogoDraft(instance.logo_url ? "remove" : null);
                      setLogoError(null);
                    }}
                  >
                    Remove
                  </Button>
                )}
              </div>
              <input
                ref={fileInput}
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,.png,.jpg,.jpeg,.svg"
                aria-label="Logo file"
                className="sr-only"
                tabIndex={-1}
                onChange={(e) => pick(e.target.files?.[0])}
              />
              <p id="logo-hint" className={general.hint}>
                PNG, SVG or JPG, square, up to 1 MB. Shown in the sidebar, on the sign-in page and as the browser tab icon.
                With no logo, the sidebar shows the project&apos;s initials.
              </p>
              {logoError && (
                <p role="alert" className={general.error}>
                  {logoError}
                </p>
              )}
            </div>
          </div>
        </section>

        <section className={styles.section} aria-labelledby="theme-h" style={{ borderBottom: 0, paddingBottom: 0 }}>
          <h2 id="theme-h">Theme</h2>
          <p className={general.hint} id="theme-hint">
            The colours of the console for everyone on this install. Light or dark stays each person&apos;s own choice.
          </p>
          <div role="radiogroup" aria-labelledby="theme-h" aria-describedby="theme-hint" className={general.themes}>
            {THEMES.map((t) => (
              <label key={t.value} className={general.themeCard}>
                <ThemePreview theme={t.value} />
                <span className={general.themeName}>
                  <input
                    type="radio"
                    name="theme"
                    value={t.value}
                    checked={theme === t.value}
                    onChange={() => {
                      setThemeDraft(t.value);
                      if (update.isError) update.reset();
                    }}
                  />
                  {t.label}
                </span>
              </label>
            ))}
          </div>
        </section>
      </Panel>
      <div className={styles.footer}>
        <Button variant="primary" type="submit" disabled={!dirty} loading={saving}>
          Save changes
        </Button>
      </div>
    </form>
  );
}

/** A sidebar strip, a panel and the primary swatch in the theme's own colours (dark ones in dark appearance). */
function ThemePreview({ theme }: { theme: Theme }) {
  const { light, dark } = THEME_SWATCHES[theme];
  const vars: Record<string, string> = {};
  for (const [k, v] of Object.entries(light)) vars[`--sw-${k}-light`] = v;
  for (const [k, v] of Object.entries(dark)) vars[`--sw-${k}-dark`] = v;
  return (
    <span className={general.preview} style={vars as CSSProperties} aria-hidden="true">
      <span className={general.previewSidebar}>
        <span className={general.previewNav} />
        <span className={general.previewNav} />
      </span>
      <span className={general.previewPanel}>
        <span className={general.previewLine} />
        <span className={general.previewButton} />
      </span>
    </span>
  );
}
