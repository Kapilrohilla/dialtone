"use client";

import { useState } from "react";
import { Button, Dialog, Field, StateBlock, Table, Td, Th, useToast } from "@/components/ui";
import { TopBar } from "@/components/shell/TopBar";
import { ApiError } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useInvite, useMe, useSetRole, useTeam } from "@/lib/queries";
import { canManageTeam, isOwner } from "@/lib/roles";
import type { Role } from "@/lib/types";
import styles from "../settings.module.css";

const LABELS: Record<Role, string> = { owner: "Owner", admin: "Admin", editor: "Editor", viewer: "Viewer" };

function roleOptions(owner: boolean): Role[] {
  return owner ? ["owner", "admin", "editor", "viewer"] : ["admin", "editor", "viewer"];
}

export default function TeamPage() {
  const { data: me, isPending: meLoading } = useMe();
  const team = useTeam();
  const setRole = useSetRole();
  const [inviting, setInviting] = useState(false);
  const manage = canManageTeam(me?.role);
  const owner = isOwner(me?.role);
  const timeZone = me?.preferences.time_zone ?? "Asia/Kolkata";

  return (
    <>
      <TopBar
        title="Team"
        primary={
          manage ? (
            <Button variant="primary" onClick={() => setInviting(true)}>
              Invite someone
            </Button>
          ) : undefined
        }
      />
      <div className={styles.tableWrap}>
        {team.isError ? (
          <StateBlock state="error" title="Could not load the team" body={team.error instanceof ApiError ? team.error.detail : undefined} onRetry={() => team.refetch()} />
        ) : team.isPending || meLoading ? (
          <StateBlock state="loading" title="Loading" />
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Name</Th>
                <Th>Email</Th>
                <Th>Role</Th>
                <Th>Last signed in</Th>
              </tr>
            </thead>
            <tbody>
              {team.data.map((m) => {
                // Nobody changes their own role, and only an owner touches an owner's.
                const editable = manage && m.id !== me?.id && (owner || m.role !== "owner");
                return (
                  <tr key={m.id}>
                    <Td>{m.name}</Td>
                    <Td>{m.email}</Td>
                    <Td>
                      {editable ? (
                        <select
                          className={styles.roleSelect}
                          aria-label={`Role for ${m.name}`}
                          value={m.role}
                          disabled={setRole.isPending}
                          onChange={(e) => setRole.mutate({ id: m.id, role: e.target.value as Role })}
                        >
                          {roleOptions(owner).map((r) => (
                            <option key={r} value={r}>
                              {LABELS[r]}
                            </option>
                          ))}
                        </select>
                      ) : (
                        LABELS[m.role]
                      )}
                    </Td>
                    <Td>{m.last_login ? timeAgo(m.last_login, new Date(), timeZone) : <span className={styles.mutedText}>Never</span>}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
      </div>
      <InviteDialog open={inviting} owner={owner} onClose={() => setInviting(false)} />
    </>
  );
}

function InviteDialog({ open, owner, onClose }: { open: boolean; owner: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Invite someone">
      <InviteForm owner={owner} onClose={onClose} />
    </Dialog>
  );
}

function InviteForm({ owner, onClose }: { owner: boolean; onClose: () => void }) {
  const invite = useInvite();
  const toast = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const fields = invite.error instanceof ApiError ? invite.error.fields : {};
  const general = invite.error instanceof ApiError ? (Object.keys(fields).length ? null : invite.error.detail) : invite.isError ? "Couldn't reach the server. Try again." : null;

  if (invite.data) {
    const link = `${location.origin}${invite.data.set_password_url}`;
    const copy = async () => {
      try {
        await navigator.clipboard.writeText(link);
        toast.show("Link copied.", "ok");
      } catch {
        toast.show("Couldn't copy. Select the link and copy it.", "bad");
      }
    };
    return (
      <div className={styles.form}>
        <div className={styles.copyRow}>
          <Field label="Set-password link" value={link} readOnly onFocus={(e) => e.currentTarget.select()} />
          <Button onClick={copy}>Copy link</Button>
        </div>
        <p className={styles.note}>Send this link to {name.trim()}. It works once.</p>
        <div className={styles.footer} style={{ padding: 0 }}>
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    );
  }

  return (
    <form
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        invite.mutate({ name: name.trim(), email: email.trim(), role });
      }}
    >
      <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} error={fields.name?.[0]} required maxLength={150} />
      <Field label="Work email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} error={fields.email?.[0]} required />
      <Field label="Role" control="select" value={role} onChange={(e) => setRole(e.target.value as Role)} error={fields.role?.[0]}>
        {roleOptions(owner).map((r) => (
          <option key={r} value={r}>
            {LABELS[r]}
          </option>
        ))}
      </Field>
      {general && <p role="alert" className={styles.note}>{general}</p>}
      <div className={styles.footer} style={{ padding: 0 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button type="submit" variant="primary" loading={invite.isPending}>
          Create link
        </Button>
      </div>
    </form>
  );
}
