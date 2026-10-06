-- Which of the object index's workspace prefixes no workspace owns (§876).
--
-- Deleting a workspace removes its rows, its schema (0010) and since §864 its
-- files. When objects live in OpenSearch (§811) it also owns an index per
-- object type, named from its search prefix (`ws-<id>-objects-<type id>`),
-- and nothing removed those: deleting a type through the API drops its index,
-- and deleting the workspace deletes its types by cascade, which no route
-- sees. Every object the workspace held stayed searchable on the domain, by
-- nobody, and kept its shards and storage for the life of the stack.
--
-- The worker lists the domain's workspace indices and asks here which of the
-- prefixes they carry belong to no workspace, then deletes those indices. An
-- orphan sweep, like the schemas', rather than a tombstone like the files':
-- the domain can be asked what it holds, and the sweep also finds what was
-- left by every workspace deleted before this existed. The worker cannot read
-- every workspace row (RLS), so the question is answered here.
CREATE FUNCTION orphaned_search_prefixes(p_prefixes text[])
RETURNS SETOF text
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
    SELECT DISTINCT p
      FROM unnest(p_prefixes) AS p
     WHERE p ~ '^ws-[0-9a-f]{12}-$'
       AND NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.search_prefix = p)
     ORDER BY 1
$$;

REVOKE EXECUTE ON FUNCTION orphaned_search_prefixes(text[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION orphaned_search_prefixes(text[]) TO platform_app;
