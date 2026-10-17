-- Search a workspace's resources by name (§990).
--
-- The workspace-wide search matches a name anywhere in it - "orders" finds
-- "Daily orders" and "orders_clean" - which a b-tree cannot answer, so every
-- search read the whole table. A trigram index answers it for a name of two
-- letters or more. Only the resources not in the trash, which are all the
-- search ever asks for. pg_trgm is a trusted extension (Postgres 13 and on),
-- which the database's owner may create, and RDS supports.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX idx_resources_name_trgm ON resources
    USING gin (lower(name) gin_trgm_ops) WHERE trashed_at IS NULL;
