-- Commenting on an object (§322; `ontology.md` §4.2; `object-views` p.137).
--
--     "Multiple users often work with a particular object. To facilitate this
--      cooperation, Object Explorer allows users to comment on an object,
--      mention other users, and attach files and images.
--
--      You can open the Comments Helper for any object using the View comments
--      button in the header of any Object View.
--
--      Object Explorer comments on an object are not related to the Comment
--      widget in Workshop." (p.137)
--
-- One page, three capabilities and a placement, and every one of them is here.
-- p.137's last line is worth keeping in view while reading this file: these are
-- **not** Workshop's Comment widget, which is a thing a builder drops into a
-- module. A comment here belongs to an object and follows it onto every screen
-- that shows it.
--
-- **No foreign key to the object**, for db 0074's reason: an instance lives in
-- the instance store (Postgres or OpenSearch, db 0035) and is not a row this
-- schema can reference. So a comment can outlive what it is about — a real
-- state rather than a defect, and the thread says so rather than vanishing.
-- The *type* is referenced, because that is a real row: deleting an object type
-- takes its comments with it, which is right, since nothing could render them.
--
-- **Mentions are resolved when the comment is written, and stored.** Three
-- reasons, in order of how much they cost to get wrong:
--
--   * A mention decided the notification. Who was told is a fact about what
--     happened, and recomputing it later from the text would let a rename or a
--     departure change the record of who was called.
--   * The browser must not re-resolve them. That is §146's rule — "a browser
--     that re-derived it would be a second matcher, free to disagree with the
--     one that decided the row belonged in the list" — and here a disagreement
--     shows as a mention highlighted on the wrong name.
--   * Spans are stored with the ids, so the thread can mark the exact
--     characters. A comment is never edited (p.137 does not describe editing),
--     so a span cannot go stale.
--
-- **Attachments are the `AttachmentOut` shape, as a list.** p.137's "attach
-- files and images" needs no new storage: the attachment upload route has
-- existed since roadmap Objects item 4 and returns a storage key that the
-- download route exchanges for bytes *after* checking the caller. Putting a
-- key here rather than a URL is that route's own argument — a permanent URL
-- would be a public read of private bytes, and a presigned one would expire
-- inside a value that claims to be stable.

CREATE TABLE object_comments (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id    uuid NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    object_type_id  uuid NOT NULL REFERENCES object_types(id) ON DELETE CASCADE,
    instance_id     uuid NOT NULL,
    -- **Nullable, and the null is not an absence of authorship**: somebody
    -- leaving does not unsay what they said. The thread renders an unknown
    -- author rather than dropping the comment, which is the same choice db
    -- 0077 makes about a read with no person behind it.
    author_id       uuid REFERENCES users(id) ON DELETE SET NULL,
    body            text NOT NULL CHECK (length(body) BETWEEN 1 AND 10000),
    -- [{"user_id", "label", "start", "end"}, ...] — see the header.
    mentions        jsonb NOT NULL DEFAULT '[]'::jsonb,
    -- [{"key", "filename", "content_type", "size"}, ...]
    attachments     jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- The read this table exists for: one object's thread, oldest first. A
-- conversation is read in the order it was said, which is the opposite of
-- every other listing here (db 0074's favourites, db 0073's history) — those
-- are lists of *your* things, where the most recent is what you want first.
CREATE INDEX idx_object_comments_thread
    ON object_comments (object_type_id, instance_id, created_at);

-- One hop to object_types, through the SECURITY DEFINER helper rather than a
-- subselect that could recurse — the shape db 0006 gives every child of an
-- object type.
ALTER TABLE object_comments ENABLE ROW LEVEL SECURITY;
CREATE POLICY oc_isolation ON object_comments
    USING (EXISTS (SELECT 1 FROM object_types ot
                   WHERE ot.id = object_type_id
                     AND rls_can_access_workspace(ot.workspace_id)));

GRANT SELECT, INSERT, UPDATE, DELETE ON object_comments TO platform_app;
