"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, api, mutations } from "@/lib/api";
import { Dialog, Field } from "@/components/dialog";
import type { OrgUser } from "@/lib/types";

function InviteButton() {
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<"admin" | "member">("member");
  const queryClient = useQueryClient();

  const invite = useMutation({
    mutationFn: () => mutations.inviteUser({ email, display_name: displayName, org_role: role }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["org-members"] });
      setOpen(false);
      setEmail("");
      setDisplayName("");
      setRole("member");
    },
  });

  function close() {
    if (!invite.isPending) {
      setOpen(false);
      invite.reset();
    }
  }

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        Invite member
      </button>
      <Dialog open={open} title="Invite a member" onClose={close}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            invite.mutate();
          }}
        >
          <Field label="Email" hint="They'll receive sign-in instructions by email">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </Field>
          <Field label="Name">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              maxLength={120}
            />
          </Field>
          <Field label="Organisation role" hint="Admins manage members and all workspaces">
            <select value={role} onChange={(e) => setRole(e.target.value as "admin" | "member")}>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </Field>
          {invite.isError && (
            <div className="form-error">
              {invite.error instanceof ApiError && invite.error.status === 409
                ? "Someone with this email is already in the organisation."
                : "Couldn't send the invite. Check the details and try again."}
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn quiet" onClick={close}>
              Cancel
            </button>
            <button
              type="submit"
              className="btn"
              disabled={invite.isPending || !email.trim() || !displayName.trim()}
            >
              {invite.isPending ? "Inviting…" : "Send invite"}
            </button>
          </div>
        </form>
      </Dialog>
    </>
  );
}

function MemberRow({ member, isAdmin, selfId }: { member: OrgUser; isAdmin: boolean; selfId?: string }) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["org-members"] });

  const setRole = useMutation({
    mutationFn: (org_role: "admin" | "member") => mutations.setUserRole(member.id, org_role),
    onSuccess: refresh,
  });
  const disable = useMutation({
    mutationFn: () => mutations.disableUser(member.id),
    onSuccess: refresh,
  });

  // Owners are immutable here; people can't manage their own row (avoids
  // locking yourself out of admin by accident).
  const editable = isAdmin && member.org_role !== "owner" && member.id !== selfId;
  const disabled = member.status !== "active";

  return (
    <tr style={disabled ? { opacity: 0.55 } : undefined}>
      <td>{member.display_name}</td>
      <td style={{ fontFamily: "var(--font-mono)", fontSize: 12.5 }}>{member.email}</td>
      <td>
        {editable && !disabled ? (
          <div className="row-actions">
            <select
              value={member.org_role}
              onChange={(e) => setRole.mutate(e.target.value as "admin" | "member")}
              disabled={setRole.isPending}
              aria-label={`Role for ${member.display_name}`}
            >
              <option value="member">member</option>
              <option value="admin">admin</option>
            </select>
          </div>
        ) : (
          <span className={`chip${member.org_role !== "member" ? " brass" : ""}`}>
            {member.org_role}
          </span>
        )}
      </td>
      <td>{member.status}</td>
      <td>
        {editable && !disabled && (
          <button
            className="btn danger"
            style={{ padding: "3px 9px", fontSize: 12 }}
            disabled={disable.isPending}
            onClick={() => {
              if (window.confirm(`Disable ${member.display_name}? They will lose access immediately.`)) {
                disable.mutate();
              }
            }}
          >
            {disable.isPending ? "Disabling…" : "Disable"}
          </button>
        )}
      </td>
    </tr>
  );
}

export default function OrgPage() {
  const org = useQuery({ queryKey: ["org"], queryFn: api.org });
  const members = useQuery({ queryKey: ["org-members"], queryFn: api.orgMembers });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });

  const isAdmin = me.data?.org_role === "owner" || me.data?.org_role === "admin";

  return (
    <main className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">organisation</p>
          <h1>{org.data?.name ?? "Organisation"}</h1>
          {org.data && (
            <p className="sub">
              Plan: {org.data.plan}
              {org.data.aws_region ? ` · deployed in ${org.data.aws_region}` : " · not yet deployed"}
            </p>
          )}
        </div>
        {isAdmin && <InviteButton />}
      </div>

      <p className="eyebrow" style={{ marginBottom: 10 }}>members</p>
      {members.isPending && <div className="state">Loading members…</div>}
      {members.isError && (
        <div className="state error">Couldn&apos;t load members. Refresh to try again.</div>
      )}
      {members.data && (
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Role</th>
              <th>Status</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {members.data.map((m) => (
              <MemberRow key={m.id} member={m} isAdmin={isAdmin} selfId={me.data?.user_id} />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
