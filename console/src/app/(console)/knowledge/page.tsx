"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Button, Dialog, StateBlock } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import type { KnowledgeDoc } from "@/lib/types";
import { useCreateDoc, useKnowledgeDoc, useKnowledgeList, useMe, useRevisions, useSaveDoc, type DocUpdate } from "@/lib/queries";
import { canEdit as roleCanEdit } from "@/lib/roles";
import { useLeaveGuard } from "@/lib/useLeaveGuard";
import { DocEditor, type EditorMode } from "./_components/DocEditor";
import { DocList } from "./_components/DocList";
import { UploadButton } from "./_components/UploadButton";
import { VersionHistory } from "./_components/VersionHistory";
import styles from "./knowledge.module.css";

/** The text being edited, plus the saved text (and its revision) it was started from. */
type Draft = { id: number; rev: number; baseTitle: string; baseBody: string; title: string; body: string };

/** One field after a save: a saved field is now the saved text, an unedited one takes the server's text (it may
 *  be newer), and an edit made while saving stays. */
function settle(value: string, base: string, sent: string | undefined, saved: string, norm: (v: string) => string) {
  if (sent !== undefined) return { value: norm(value) === sent ? saved : value, base: saved };
  if (norm(value) === base) return { value: saved, base: saved };
  return { value, base };
}

function afterSave(d: Draft, saved: KnowledgeDoc, sent: DocUpdate): Draft {
  const title = settle(d.title, d.baseTitle, sent.title, saved.title, (v) => v.trim());
  const body = settle(d.body, d.baseBody, sent.body_md, saved.body_md, (v) => v);
  return { ...d, rev: saved.current_revision, title: title.value, baseTitle: title.base, body: body.value, baseBody: body.base };
}

const seed = (d: KnowledgeDoc): Draft => ({ id: d.id, rev: d.current_revision, baseTitle: d.title, baseBody: d.body_md, title: d.title, body: d.body_md });

export default function KnowledgePage() {
  // useSearchParams needs a Suspense boundary for the static build.
  return (
    <Suspense>
      <Knowledge />
    </Suspense>
  );
}

function Knowledge() {
  const router = useRouter();
  const params = useSearchParams();
  const list = useKnowledgeList();
  const { data: me, isPending: meLoading } = useMe();
  const create = useCreateDoc();
  const editable = roleCanEdit(me?.role);
  const timeZone = me?.preferences.time_zone ?? "Asia/Kolkata";

  const fromUrl = Number(params.get("doc")) || undefined;
  const [selected, setSelected] = useState<number | undefined>(fromUrl);
  const docs = list.data;
  const docId = docs ? (docs.find((d) => d.id === selected) ?? docs[0])?.id : undefined;

  const doc = useKnowledgeDoc(docId);
  const revisions = useRevisions(docId);
  const [draft, setDraft] = useState<Draft | null>(null);
  const save = useSaveDoc(docId ?? 0, (saved, sent) => setDraft((d) => (d && d.id === saved.id ? afterSave(d, saved, sent) : d)));
  const [mode, setMode] = useState<EditorMode>("rich");
  const [history, setHistory] = useState(false);

  // A newly loaded document starts a fresh draft. A newer saved revision replaces an untouched draft silently;
  // an edited one is kept and the person is told.
  const loaded = doc.data;
  const touched = (d: Draft) => d.title.trim() !== d.baseTitle || d.body !== d.baseBody;
  let newerSaved = false;
  if (loaded) {
    if (draft?.id !== loaded.id) setDraft(seed(loaded));
    else if (loaded.current_revision > draft.rev) {
      if (touched(draft)) newerSaved = true;
      else setDraft(seed(loaded));
    }
  }

  const current = loaded && draft?.id === loaded.id ? { doc: loaded, draft } : null;
  // Only the fields this person edited are sent, so a newer saved body is never replaced by an old one.
  const changes: DocUpdate = {};
  if (current) {
    if (current.draft.title.trim() !== current.draft.baseTitle) changes.title = current.draft.title.trim();
    if (current.draft.body !== current.draft.baseBody) changes.body_md = current.draft.body;
  }
  const dirty = Object.keys(changes).length > 0;
  const { pending, guarded, stay, leave } = useLeaveGuard(dirty);

  const latest = useRef({ dirty, changes, canSave: editable && !save.isPending, save });
  useEffect(() => {
    latest.current = { dirty, changes, canSave: editable && !save.isPending, save };
  });

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "s") return;
      e.preventDefault();
      const { dirty, changes, canSave, save } = latest.current;
      if (dirty && canSave) save.mutate(changes);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  function open(id: number) {
    setDraft(null);
    setSelected(id);
    router.replace(`/knowledge?doc=${id}`);
  }

  const switchTo = (id: number) => id !== docId && guarded(() => open(id));
  const newDocument = () =>
    guarded(() => create.mutate({ title: "Untitled document", body_md: "" }, { onSuccess: (d) => open(d.id) }));

  const empty = docs?.length === 0;
  const loadTheirs = () => loaded && guarded(() => setDraft(seed(loaded)));
  const restore = (body: string) =>
    guarded(() => {
      setDraft((d) => (d ? { ...d, body } : d));
      setHistory(false);
    });
  const topBar = (
    <TopBar
      title="Knowledge base"
      secondary={editable && !empty && !meLoading ? <UploadButton onUploaded={(d) => guarded(() => open(d.id))} /> : undefined}
      primary={
        editable && !empty && !meLoading ? (
          <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(changes)}>
            Save
          </Button>
        ) : undefined
      }
    />
  );

  if (meLoading) {
    return (
      <>
        {topBar}
        <div className={styles.main}>
          <StateBlock state="loading" title="Loading" />
        </div>
      </>
    );
  }
  if (list.isError) {
    return (
      <>
        {topBar}
        <div className={styles.main}>
          <StateBlock state="error" title="Could not load documents" body={list.error instanceof ApiError ? list.error.detail : undefined} onRetry={() => list.refetch()} />
        </div>
      </>
    );
  }
  if (empty) {
    return (
      <>
        {topBar}
        <div className={styles.main}>
          <StateBlock
            state="empty"
            title="No documents yet"
            body="Write down what the agent may quote, such as prices, plans and policies."
            action={
              editable ? (
                <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
                  <Button variant="primary" loading={create.isPending} onClick={newDocument}>
                    New document
                  </Button>
                  <UploadButton onUploaded={(d) => open(d.id)} />
                </div>
              ) : undefined
            }
          />
        </div>
      </>
    );
  }

  return (
    <>
      {topBar}
      <div className={styles.layout}>
        {docs ? (
          <DocList docs={docs} selectedId={docId} canEdit={editable} creating={create.isPending} onSelect={switchTo} onNew={newDocument} />
        ) : (
          <div className={styles.list} aria-label="Loading documents">
            {[0, 1, 2].map((i) => (
              <span key={i} className={styles.skeleton} aria-hidden="true" />
            ))}
          </div>
        )}
        <div className={styles.main}>
          {doc.isError ? (
            <StateBlock state="error" title="Could not load this document" body={doc.error instanceof ApiError ? doc.error.detail : undefined} onRetry={() => doc.refetch()} />
          ) : !current ? (
            <StateBlock state="loading" title="Loading document" />
          ) : (
            <DocEditor
              key={current.doc.id}
              title={current.draft.title}
              body={current.draft.body}
              mode={mode}
              readOnly={!editable}
              newest={revisions.data?.[0]}
              timeZone={timeZone}
              onTitle={(title) => setDraft((d) => (d ? { ...d, title } : d))}
              onBody={(body) => setDraft((d) => (d ? { ...d, body } : d))}
              onMode={setMode}
              onHistory={() => setHistory(true)}
              onLoadTheirs={newerSaved ? loadTheirs : undefined}
            />
          )}
        </div>
      </div>
      {current && (
        <VersionHistory
          docId={current.doc.id}
          open={history}
          onClose={() => setHistory(false)}
          timeZone={timeZone}
          canEdit={editable}
          onRestore={restore}
        />
      )}
      <Dialog
        open={pending !== null}
        onClose={stay}
        title={`Discard unsaved changes to ${current?.draft.title.trim() || "this document"}?`}
        footer={
          <>
            <Button onClick={stay}>Keep editing</Button>
            <Button variant="danger" onClick={leave}>
              Discard
            </Button>
          </>
        }
      >
        <p className={styles.dialogText}>Your edits have not been saved. Agents keep quoting the saved text until you save.</p>
      </Dialog>
    </>
  );
}
