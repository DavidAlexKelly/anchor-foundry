-- ============================================================================
-- 0029_richer_property_types.sql - make the typed property system actually
-- typed, and add attachments (roadmap Objects item 4).
--
-- The item says "today's typed properties are presumably basic scalars". The
-- guess is wrong in a more interesting way than it is right: `geopoint` and
-- `timestamp` have been in the `property_data_type` enum since 0003. They
-- are **labels that nothing enforces**:
--
--   * `actions._validate_value` checks integer / float / boolean / string and
--     silently accepts anything at all for date, timestamp, geopoint and
--     json - so a property declared `geopoint` accepts the string "banana";
--   * `instances.extract_rows` writes whatever the mapped column holds,
--     passed through `json_safe`, with no reference to the declared type;
--   * `_DUCK_TO_PROPERTY` never suggests geopoint, so nothing ever produced
--     one on purpose.
--
-- So this item is not "add types", it is "make three existing types mean
-- something, and add the one that is genuinely missing". The enum barely
-- changes; the semantics change a lot, and most of that lives in Python
-- because it is validation and coercion, not storage.
--
-- The one new label: `attachment`
-- ------------------------------
-- A reference to a file in the storage gateway the platform already has
-- (S3 in a deployment, a local directory in dev) - explicitly *not* a new
-- storage mechanism, as the item asks. The stored value is a small JSON
-- object, not a URL:
--
--     {"key": "<storage key>", "filename": "...", "content_type": "...",
--      "size": 12345}
--
-- A key rather than a URL because a URL would either be permanent (and so a
-- public read of private data) or presigned (and so expire inside a stored
-- value that claims to be stable). The key is resolved to bytes at read time
-- by a route that runs the caller's own permission check first, which is the
-- only point at which "may this person see this file" can honestly be
-- answered.
--
-- What this deliberately does not do
-- ---------------------------------
--   * No new table. An attachment is a property *value*, so it lives in the
--     instance's properties JSON like every other value. Giving it a table
--     would mean instances in OpenSearch (§35) referencing rows in Postgres,
--     which is the cross-store reference the link work (§37) already refused.
--   * No ontology-only properties. An attachment property must be mapped to
--     a dataset column like every other property, and the write-back stores
--     the whole reference as JSON text in that column. This is not a
--     limitation that could be lifted by relaxing a check: object instances
--     are re-materialised from their dataset on every sync (mark-and-sweep,
--     §14), so a value that existed only in the ontology would be deleted by
--     the next sync. "Attach a file to an object" therefore means "write a
--     reference into the data that object is made of", which is the same
--     thing every other action already does.
--   * No garbage collection of orphaned files. Replacing an attachment leaves
--     the old object in storage. Deleting it would mean deleting data on a
--     write-back that any prior version of the instance still refers to, and
--     the platform has no reference counting to make that safe. Recorded in
--     STATUS rather than half-done.
--   * No image thumbnailing, no content sniffing, no virus scanning. The
--     content type is what the uploader declared.
--   * `timestamp` stays a single label rather than splitting into
--     timestamp/timestamptz. See the note below.
--
-- On "timestamp-with-timezone if not already distinct from a plain string"
-- ---------------------------------------------------------------------
-- It was not distinct - nothing validated it. It is now: a timestamp value
-- must parse as ISO-8601, and an offset is *preserved* if present and simply
-- absent if not. A separate `timestamptz` label was considered and rejected:
-- the values arrive from CSV and Parquet columns whose own timezone
-- awareness varies by file, so a type that promised "always has an offset"
-- would be a promise the ingest path cannot keep. One label that accepts
-- both, and says so, is the honest version.
-- ============================================================================

-- ADD VALUE IF NOT EXISTS: an enum label cannot be dropped, so a migration
-- that adds one must be re-appliable after an edit (STATUS rough edges).
ALTER TYPE property_data_type ADD VALUE IF NOT EXISTS 'attachment';

COMMENT ON TYPE property_data_type IS
    'Object property types. geopoint values are {"lat": float, "lon": float}; '
    'attachment values are {"key", "filename", "content_type", "size"} '
    'referencing the storage gateway; date/timestamp are ISO-8601 text, with '
    'an offset preserved when the source has one. Validated in '
    'services/ontology.py::coerce_property_value, not by the database - the '
    'values live inside a jsonb blob and may not live in Postgres at all '
    '(migration 0026 moved instances to OpenSearch).';
