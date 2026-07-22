"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, mutations } from "@/lib/api";
import { Dialog, Field, slugPreview } from "./dialog";

export function CreateProjectButton({
  workspaceId,
  workspaceSlug,
}: {
  workspaceId: string;
  workspaceSlug: string;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const router = useRouter();
  const queryClient = useQueryClient();

  const create = useMutation({
    mutationFn: () => mutations.createProject(workspaceId, { name, description }),
    onSuccess: async (project) => {
      await queryClient.invalidateQueries({ queryKey: ["projects", workspaceId] });
      await queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      setOpen(false);
      router.push(`/${workspaceSlug}/${project.slug}`);
    },
  });

  function close() {
    if (!create.isPending) {
      setOpen(false);
      create.reset();
    }
  }

  return (
    <>
      <button className="btn" onClick={() => setOpen(true)}>
        New project
      </button>
      <Dialog open={open} title="New project" onClose={close}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <Field
            label="Name"
            hint={name ? `slug: ${slugPreview(name) || "—"}` : "Shown across the platform"}
          >
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={120}
              autoFocus
            />
          </Field>
          <Field label="Description" hint="Optional — what this project is for">
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={2000}
            />
          </Field>
          {create.isError && (
            <div className="form-error">
              {create.error instanceof ApiError && create.error.status === 409
                ? "A project with this name already exists in this workspace."
                : "Couldn't create the project. Check the name and try again."}
            </div>
          )}
          <div className="form-actions">
            <button type="button" className="btn quiet" onClick={close}>
              Cancel
            </button>
            <button type="submit" className="btn" disabled={create.isPending || !name.trim()}>
              {create.isPending ? "Creating…" : "Create project"}
            </button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
