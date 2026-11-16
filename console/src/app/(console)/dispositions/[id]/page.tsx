"use client";

import { CircleAlert, CircleCheck, Plus } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Fragment, useEffect, useRef, useState } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { Button, Chip, Dialog, Field, Menu, StateBlock, Table, Td, Th, useToast, type MenuItem } from "@/components/ui";
import { ApiError, isSignedOut } from "@/lib/api";
import { aiLine, draftErrors, hasErrors, MAX_ITEMS, MAX_LIST_NAME, type ListDraft } from "@/lib/dispositions";
import { outcomeTone } from "@/lib/outcomes";
import { useDeleteDispositionList, useDispositionList, useDuplicateDispositionList, useMe, useSaveDispositionList } from "@/lib/queries";
import { canEdit } from "@/lib/roles";
import type { DispositionItem, DispositionList } from "@/lib/types";
import { useLeaveGuard } from "@/lib/useLeaveGuard";
import { DeleteListDialog } from "../_components/DeleteListDialog";
import { ItemEditor } from "../_components/ItemEditor";
import styles from "../dispositions.module.css";

export default function DispositionListPage() {
  const { id } = useParams<{ id: string }>();
  const listId = Number(id);
  const { data: list, isError, error, refetch } = useDispositionList(listId);
  const me = useMe();

  if (isError || !list || me.isPending) {
    return (
      <>
        <TopBar breadcrumb={[{ label: "Dispositions", href: "/dispositions" }, { label: "List" }]} />
        <div className={styles.page}>
          {isError ? (
            <StateBlock
              state="error"
              title={error instanceof ApiError && error.status === 404 ? "This list could not be found." : "Could not load the list"}
              body={error instanceof ApiError && error.status !== 404 ? error.detail : undefined}
              onRetry={error instanceof ApiError && error.status === 404 ? undefined : () => refetch()}
            />
          ) : (
            <StateBlock state="loading" title="Loading the list" />
          )}
        </div>
      </>
    );
  }
  return <ListEditor key={list.id} list={list} editable={canEdit(me.data?.role)} />;
}

const draftOf = (l: Pick<DispositionList, "name" | "items" | "fallback_code">): ListDraft => ({ name: l.name, items: l.items, fallback_code: l.fallback_code });

/** What is sent: the draft with stray spaces trimmed. */
function cleaned(d: ListDraft): ListDraft {
  return {
    name: d.name.trim(),
    fallback_code: d.fallback_code,
    items: d.items.map((it) => ({
      ...it,
      name: it.name.trim(),
      description: it.description.trim(),
      fields: it.fields.map((f) => ({ ...f, label: f.label.trim() })),
    })),
  };
}

const BLANK: DispositionItem = { code: "", name: "", description: "", group: "Not interested", fields: [] };

function ListEditor({ list, editable }: { list: DispositionList; editable: boolean }) {
  const router = useRouter();
  const toast = useToast();
  const [draft, setDraft] = useState<ListDraft>(() => draftOf(list));
  const [base, setBase] = useState(() => JSON.stringify(cleaned(draftOf(list))));
  const [editing, setEditing] = useState<number | null>(null);
  const [serverErrors, setServerErrors] = useState<Record<string, string[]> | null>(null);
  const [deleting, setDeleting] = useState(false);
  const save = useSaveDispositionList(list.id);
  const duplicate = useDuplicateDispositionList();
  const remove = useDeleteDispositionList();

  const dirty = JSON.stringify(cleaned(draft)) !== base;
  const errors = draftErrors(draft);
  const { pending, guarded, stay, leave } = useLeaveGuard(dirty);

  function change(next: ListDraft) {
    setDraft(next);
    setServerErrors(null);
  }

  function submit() {
    if (!dirty || !editable || save.isPending) return;
    if (hasErrors(errors)) {
      const first = Object.keys(errors.items)[0];
      if (first !== undefined) setEditing(Number(first));
      toast.show("Fix the errors before saving.", "bad");
      return;
    }
    const sent = cleaned(draft);
    save.mutate(sent, {
      onSuccess: (saved) => {
        const next = draftOf(saved);
        setBase(JSON.stringify(cleaned(next)));
        // Edits made while saving stay.
        setDraft((d) => (JSON.stringify(cleaned(d)) === JSON.stringify(sent) ? next : d));
        setServerErrors(null);
      },
      onError: (e) => {
        if (e instanceof ApiError && Object.keys(e.fields).length) setServerErrors(e.fields);
        toast.show(isSignedOut(e) ? "You were signed out. Sign in again in another tab, then save." : e instanceof ApiError ? e.detail : "Could not save.", "bad");
      },
    });
  }

  const latest = useRef(submit);
  useEffect(() => {
    latest.current = submit;
  });
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "s") return;
      e.preventDefault();
      latest.current();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const items = draft.items;
  const setItem = (i: number, next: DispositionItem) => {
    const old = items[i];
    change({
      ...draft,
      items: items.map((it, j) => (j === i ? next : it)),
      // The fallback follows its item's code.
      fallback_code: old.code === draft.fallback_code ? next.code : draft.fallback_code,
    });
  };
  const move = (i: number, by: -1 | 1) => {
    const next = [...items];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    change({ ...draft, items: next });
    if (editing === i) setEditing(i + by);
    else if (editing === i + by) setEditing(i);
  };
  const removeItem = (i: number) => {
    change({ ...draft, items: items.filter((_, j) => j !== i) });
    if (editing === i) setEditing(null);
    else if (editing !== null && editing > i) setEditing(editing - 1);
  };
  const addItem = () => {
    change({ ...draft, items: [...items, BLANK] });
    setEditing(items.length);
  };

  function menu(item: DispositionItem, i: number): MenuItem[] {
    const isFallback = item.code === draft.fallback_code;
    return [
      { label: "Edit", onSelect: () => setEditing(i) },
      { label: "Set as fallback", disabled: isFallback || !item.code, onSelect: () => change({ ...draft, fallback_code: item.code }) },
      { label: "Move up", disabled: i === 0, onSelect: () => move(i, -1) },
      { label: "Move down", disabled: i === items.length - 1, onSelect: () => move(i, 1) },
      { label: "Remove", danger: true, disabled: isFallback, onSelect: () => removeItem(i) },
    ];
  }

  const serverNameError = serverErrors?.name?.[0];
  const listErrors = [...(serverErrors?.items ?? []), ...(serverErrors?.fallback_code ?? []), ...(serverErrors?.errors ?? [])];
  const name = draft.name.trim() || "Untitled list";

  const hasNotReached = items.some((it) => it.group === "Not reached");
  const hasDropped = items.some((it) => it.group === "Dropped");

  return (
    <>
      <TopBar
        breadcrumb={[{ label: "Dispositions", href: "/dispositions" }, { label: name }]}
        status={dirty ? "Unsaved changes" : undefined}
        secondary={
          editable ? (
            <Menu
              label="List actions"
              items={[
                { label: "Duplicate", onSelect: () => guarded(() => duplicate.mutate(list.id, { onSuccess: (copy) => router.push(`/dispositions/${copy.id}`) })) },
                { label: "Delete", danger: true, onSelect: () => setDeleting(true) },
              ]}
            />
          ) : undefined
        }
        primary={
          editable ? (
            <Button variant="primary" disabled={!dirty} loading={save.isPending} onClick={submit}>Save list</Button>
          ) : undefined
        }
      />
      <div className={styles.editorLayout}>
        <div className={styles.editorMain}>
          <Field
            label="List name"
            className={styles.nameField}
            value={draft.name}
            maxLength={MAX_LIST_NAME}
            readOnly={!editable}
            error={errors.name ?? serverNameError}
            onChange={(e) => change({ ...draft, name: e.target.value })}
          />
          <section aria-labelledby="items-h" className={styles.itemsSection}>
            <div className={styles.sectionHead}>
              <h2 id="items-h" className={styles.sectionTitle}>
                Dispositions <span className={styles.count}>({items.length})</span>
              </h2>
              {editable && items.length < MAX_ITEMS && (
                <button type="button" className={styles.textButton} onClick={addItem}>
                  <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
                  Add disposition
                </button>
              )}
            </div>
            {(errors.list || listErrors.length > 0) && (
              <div role="alert" className={styles.error}>
                {[...(errors.list ? [errors.list] : []), ...listErrors].map((m) => (
                  <p key={m}>{m}</p>
                ))}
              </div>
            )}
            <Table aria-label="Dispositions" rowHeight={52}>
              <thead>
                <tr>
                  <Th>Code</Th>
                  <Th>Name</Th>
                  <Th>Description</Th>
                  <Th>Report group</Th>
                  <Th><span className={styles.srOnly}>Actions</span></Th>
                </tr>
              </thead>
              <tbody>
                {items.map((item, i) => {
                  const isFallback = item.code === draft.fallback_code;
                  return (
                    <Fragment key={i}>
                      <tr className={editing === i ? styles.editingRow : undefined}>
                        <Td>{item.code ? <Chip tone="blue" className="mono">{item.code}</Chip> : <span className={styles.mutedSmall}>No code</span>}</Td>
                        <Td>
                          <span className={styles.itemName}>
                            {item.name || <span className={styles.mutedSmall}>No name</span>}
                            {isFallback && <Chip tone="amber">Fallback</Chip>}
                          </span>
                        </Td>
                        <Td className={styles.description}>{item.description}</Td>
                        <Td><Chip tone={outcomeTone(item.group)}>{item.group}</Chip></Td>
                        <Td className={styles.right}>
                          {editable && <Menu label={`Actions for ${item.code || "new disposition"}`} items={menu(item, i)} />}
                        </Td>
                      </tr>
                      {errors.items[i] && editing !== i && (
                        <tr>
                          <Td colSpan={5}><p role="alert" className={styles.error}>{`${item.code || "New disposition"}: ${errors.items[i]}`}</p></Td>
                        </tr>
                      )}
                      {editable && editing === i && (
                        <tr>
                          <td colSpan={5} className={styles.editorCell}>
                            <ItemEditor
                              item={item}
                              isFallback={isFallback}
                              error={errors.items[i]}
                              onChange={(next) => setItem(i, next)}
                              onRemove={() => removeItem(i)}
                              onDone={() => setEditing(null)}
                            />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </Table>
          </section>
        </div>
        <aside className={styles.aside} aria-label="What the AI reads">
          <section aria-labelledby="ai-h" className={styles.asideSection}>
            <h2 id="ai-h" className={styles.sectionTitle}>What the AI reads</h2>
            <p className={styles.mutedSmall}>These lines go into the agent&rsquo;s instructions. The AI can only pick one of these codes.</p>
            <div className={styles.aiBlock} aria-label="Instructions preview">
              {items.map((item, i) => {
                const line = aiLine(item);
                const at = line.indexOf(":");
                return (
                  <p key={i}>
                    <span className={styles.aiCode}>{line.slice(0, at + 1)}</span>
                    {line.slice(at + 1)}
                  </p>
                );
              })}
            </div>
          </section>
          <div className={styles.checks}>
            {hasNotReached && hasDropped ? (
              <p className={styles.checkOk}>
                <CircleCheck size={16} strokeWidth={1.75} aria-hidden="true" />
                Has Not reached and Dropped codes
              </p>
            ) : (
              <>
                {!hasNotReached && (
                  <p className={styles.checkWarn}>
                    <CircleAlert size={16} strokeWidth={1.75} aria-hidden="true" />
                    {`No Not reached code: unanswered calls get the fallback ${draft.fallback_code}.`}
                  </p>
                )}
                {!hasDropped && (
                  <p className={styles.checkWarn}>
                    <CircleAlert size={16} strokeWidth={1.75} aria-hidden="true" />
                    {`No Dropped code: dropped calls get the fallback ${draft.fallback_code}.`}
                  </p>
                )}
              </>
            )}
          </div>
          <section aria-labelledby="used-h" className={styles.asideSection}>
            <h2 id="used-h" className={styles.sectionTitle}>
              {list.used_by.length ? `Used by ${list.used_by.length} agent${list.used_by.length === 1 ? "" : "s"}` : "Not used by any agent"}
            </h2>
            {list.used_by.length > 0 ? (
              <>
                <div className={styles.agentChips}>
                  {list.used_by.map((a) => (
                    <Link key={a.id} href={`/agents/${a.id}`} className={styles.agentChip}>{a.name}</Link>
                  ))}
                </div>
                <p className={styles.mutedSmall}>Changes reach these agents when you republish them.</p>
              </>
            ) : (
              <p className={styles.mutedSmall}>Attach it to an agent in the agent&rsquo;s settings.</p>
            )}
          </section>
        </aside>
      </div>
      <DeleteListDialog
        list={deleting ? list : null}
        pending={remove.isPending}
        onClose={() => setDeleting(false)}
        onDelete={(id) =>
          remove.mutate(id, {
            onSuccess: () => {
              setDeleting(false);
              setBase(JSON.stringify(cleaned(draft)));
              router.push("/dispositions");
            },
            onError: () => setDeleting(false),
          })
        }
      />
      <Dialog
        open={pending !== null}
        onClose={stay}
        title={`Discard unsaved changes to ${name}?`}
        footer={
          <>
            <Button onClick={stay}>Keep editing</Button>
            <Button variant="danger" onClick={leave}>Discard</Button>
          </>
        }
      >
        <p className={styles.dialogText}>Your edits have not been saved. Agents keep using the saved list until you save and republish them.</p>
      </Dialog>
    </>
  );
}
