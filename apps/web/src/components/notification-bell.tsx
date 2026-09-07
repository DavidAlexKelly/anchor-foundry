"use client";

/**
 * The inbox, in the app bar (Foundry `action-types` p.91; §257).
 *
 * > "they may still view their notifications when logged into Foundry by going
 * > to 'Notifications' and then 'See All' in the Workspace." (p.91)
 *
 * That sentence is the whole surface, and it is deliberately in the *platform*
 * bar rather than on a workspace page: a notification is addressed to a person,
 * and somebody who works in three workspaces has one inbox. Putting it under a
 * workspace would make them check it three times.
 *
 * **Opening the panel does not mark anything read.** p.91's "See All" is a
 * thing somebody does, and a badge that cleared itself because a panel was
 * opened would answer "have you seen this" with "did you glance at the bar".
 * Each notification is marked when it is opened, and the button clears the
 * rest at once.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { notifications as api } from "@/lib/api";
import { badgeLabel, safeNotificationLink } from "@/lib/notifications";
import { formatValue } from "@/lib/value-format";

/** How often the badge asks again.
 *
 * A minute, because a notification is something somebody acts on rather than
 * watches: the difference between hearing about a retriaged alert now and
 * hearing about it in fifty seconds is not a difference, and a shorter poll
 * would be a request per user per few seconds for a number that is usually
 * zero. There is no push channel here to do better with. */
const POLL_MS = 60_000;

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();

  const unread = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: api.unread,
    refetchInterval: POLL_MS,
  });
  const page = useQuery({
    queryKey: ["notifications", "list"],
    queryFn: () => api.list({ limit: 20 }),
    enabled: open,
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["notifications"] });
  };
  const markRead = useMutation({
    mutationFn: (id: string) => api.markRead(id),
    onSuccess: refresh,
  });
  const markAll = useMutation({ mutationFn: api.markAllRead, onSuccess: refresh });

  const badge = badgeLabel(unread.data?.unread ?? 0);
  const items = page.data?.items ?? [];

  return (
    <div className="bell">
      <button
        type="button"
        data-testid="notification-bell"
        aria-label={
          badge ? `Notifications, ${badge} unread` : "Notifications, none unread"
        }
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        Notifications
        {badge && (
          <span className="bell-badge" data-testid="notification-badge">
            {badge}
          </span>
        )}
      </button>
      {open && (
        <div className="bell-panel" data-testid="notification-panel">
          <div className="row-actions" style={{ justifyContent: "space-between" }}>
            <strong>Notifications</strong>
            <button
              type="button"
              className="btn quiet"
              data-testid="notification-read-all"
              disabled={!badge || markAll.isPending}
              onClick={() => markAll.mutate()}
            >
              See all
            </button>
          </div>
          {page.data && items.length === 0 && (
            <p className="field-hint" data-testid="notification-empty">
              Nothing yet. Actions that name you as a recipient will show up
              here.
            </p>
          )}
          {items.map((n) => {
            // §257's link rule: part of a link's URL came from a property
            // value, so anything that is not a path inside this app is not
            // drawn as a button at all.
            const href = safeNotificationLink(n.link_url);
            return (
              <div
                key={n.id}
                className={n.read_at ? "bell-item" : "bell-item unread"}
                data-testid={`notification-${n.id}`}
              >
                <div className="row-actions" style={{ justifyContent: "space-between" }}>
                  <strong>{n.subject}</strong>
                  <span className="slug">
                    {formatValue(n.created_at, {
                      kind: "datetime", style: "relative",
                    })}
                  </span>
                </div>
                {n.body && <p className="field-hint">{n.body}</p>}
                <div className="row-actions">
                  {n.actor_name && (
                    <span className="slug">{n.actor_name}</span>
                  )}
                  {href && n.link_text && (
                    <a
                      className="btn quiet"
                      href={href}
                      data-testid={`notification-link-${n.id}`}
                      onClick={() => markRead.mutate(n.id)}
                    >
                      {n.link_text}
                    </a>
                  )}
                  {!n.read_at && (
                    <button
                      type="button"
                      className="btn quiet"
                      data-testid={`notification-read-${n.id}`}
                      onClick={() => markRead.mutate(n.id)}
                    >
                      Mark read
                    </button>
                  )}
                </div>
              </div>
            );
          })}
          {page.data && page.data.total > items.length && (
            <p className="field-hint" data-testid="notification-more">
              Showing {items.length} of {page.data.total}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
