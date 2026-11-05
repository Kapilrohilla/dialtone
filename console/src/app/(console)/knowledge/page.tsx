"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Button, Dialog, StateBlock } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { useCreateDoc, useKnowledgeDoc, useKnowledgeList, useMe, useRevisions, useSaveDoc, type DocUpdate } from "@/lib/queries";
import { canEdit as roleCanEdit } from "@/lib/roles";
import { DocEditor, type EditorMode } from "./_components/DocEditor";
import { DocList } from "./_components/DocList";
import { UploadButton } from "./_components/UploadButton";
import { VersionHistory } from "./_components/VersionHistory";
import styles from "./knowledge.module.css";

type Draft = { id: number; title: string; body: string };

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
  const { data: me } = useMe();
  const create = useCreateDoc();
  const editable = roleCanEdit(me?.role);
  const timeZone = me?.preferences.time_zone ?? "Asia/Kolkata";

  const fromUrl = Number(params.get("doc")) || undefined;
  const [selected, setSelected] = useState<number | undefined>(fromUrl);
  const docs = list.data;
  const docId = docs ? (docs.find((d) => d.id === selected) ?? docs[0])?.id : undefined;

  const doc = useKnowledgeDoc(docId);
  const revisions = useRevisions(docId);
  const save = useSaveDoc(docId ?? 0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [mode, setMode] = useState<EditorMode>("rich");
  const [history, setHistory] = useState(false);
  /** What to do once the person agrees to drop unsaved changes. */
  const [pending, setPending] = useState<(() => void) | null>(null);

  // A newly loaded document starts a fresh draft.
  if (doc.data && draft?.id !== doc.data.id) setDraft({ id: doc.data.id, title: doc.data.title, body: doc.data.body_md });

  const current = doc.data && draft?.id === doc.data.id ? { doc: doc.data, draft } : null;
  const changes: DocUpdate = {};
  if (current) {
    if (current.draft.title.trim() !== current.doc.title) changes.title = current.draft.title.trim();
    if (current.draft.body !== current.doc.body_md) changes.body_md = current.draft.body;
  }
  const dirty = Object.keys(changes).length > 0;

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
    function onBeforeUnload(e: BeforeUnloadEvent) {
      if (!latest.current.dirty) return;
      e.preventDefault();
      e.returnValue = "";
    }
    // In-app links (the sidebar) ask first too.
    function onClick(e: MouseEvent) {
      if (!latest.current.dirty || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element).closest?.("a[href]");
      const href = a?.getAttribute("href");
      if (!a || !href?.startsWith("/") || a.getAttribute("target") === "_blank") return;
      e.preventDefault();
      e.stopPropagation();
      setPending(() => () => router.push(href));
    }
    document.addEventListener("keydown", onKey);
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [router]);

  /** Runs `action` now, or after the person agrees to discard unsaved changes. */
  function guarded(action: () => void) {
    if (latest.current.dirty) setPending(() => action);
    else action();
  }

  function open(id: number) {
    setSelected(id);
    router.replace(`/knowledge?doc=${id}`);
  }

  const switchTo = (id: number) => id !== docId && guarded(() => open(id));
  const newDocument = () =>
    guarded(() => create.mutate({ title: "Untitled document", body_md: "" }, { onSuccess: (d) => open(d.id) }));

  const empty = docs?.length === 0;
  const topBar = (
    <TopBar
      title="Knowledge base"
      secondary={editable && !empty ? <UploadButton onUploaded={(d) => guarded(() => open(d.id))} /> : undefined}
      primary={
        editable && !empty ? (
          <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(changes)}>
            Save
          </Button>
        ) : undefined
      }
    />
  );

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
          onRestore={(body) => setDraft((d) => (d ? { ...d, body } : d))}
        />
      )}
      <Dialog
        open={pending !== null}
        onClose={() => setPending(null)}
        title={`Discard unsaved changes to ${current?.draft.title.trim() || "this document"}?`}
        footer={
          <>
            <Button onClick={() => setPending(null)}>Keep editing</Button>
            <Button
              variant="danger"
              onClick={() => {
                const action = pending;
                setPending(null);
                action?.();
              }}
            >
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
