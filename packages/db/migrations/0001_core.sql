-- ============================================================================
-- 0001_core.sql
-- Extensions, enum types, and core tables:
--   organisations, users, groups, group_members
-- Spec: §16 "Core Tables"
-- ============================================================================

-- pgcrypto for gen_random_uuid() on older PG; PG16 has it built in, but the
-- extension is harmless and keeps the schema portable to PG13+.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- citext for case-insensitive email uniqueness.
CREATE EXTENSION IF NOT EXISTS citext;

-- ----------------------------------------------------------------------------
-- Enum types (spec §9 "Roles at each level")
-- ----------------------------------------------------------------------------
CREATE TYPE org_role AS ENUM ('owner', 'admin', 'member');
CREATE TYPE workspace_role AS ENUM ('admin', 'editor', 'viewer');
-- 'none' = explicitly no access; overrides the workspace grant (spec §9).
CREATE TYPE project_role AS ENUM ('owner', 'editor', 'viewer', 'none');
CREATE TYPE project_permission_mode AS ENUM ('inherited', 'custom');
CREATE TYPE user_status AS ENUM ('invited', 'active', 'disabled');

-- Deployment lifecycle for the org's customer stack (spec §6).
CREATE TYPE stack_status AS ENUM (
    'pending', 'provisioning', 'ready', 'updating', 'failed', 'destroying', 'destroyed'
);

-- ----------------------------------------------------------------------------
-- organisations — one per customer. Maps to one AWS account. (spec §4, §16)
-- In a deployed customer stack this table contains exactly one row; the
-- schema still models it as a table so control-plane tooling and tests can
-- share the same migrations.
-- ----------------------------------------------------------------------------
CREATE TABLE organisations (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    slug             text NOT NULL UNIQUE
                         CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$'),
    -- AWS deployment info (spec §16: "stores AWS deployment info, plan, licence key")
    aws_account_id   text CHECK (aws_account_id ~ '^[0-9]{12}$'),
    aws_region       text CHECK (aws_region ~ '^[a-z]{2}(-[a-z]+)+-[0-9]$'),
    platform_url     text,
    stack_status     stack_status NOT NULL DEFAULT 'pending',
    stack_version    text,
    cognito_user_pool_id   text,
    cognito_client_id      text,
    -- Plan / licensing
    plan             text NOT NULL DEFAULT 'standard',
    -- Licence key is a bearer credential for the licence API. We store only a
    -- SHA-256 hash; the plaintext key is shown once at issuance and validated
    -- by hashing. Conservative choice: the spec says "stores ... licence key"
    -- but storing it plaintext in the metadata DB would make the DB a
    -- credential store, which §10 forbids in spirit. Flagged for review.
    licence_key_hash text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

-- ----------------------------------------------------------------------------
-- users — mirrors the Cognito user pool, linked by cognito_sub (spec §16).
-- Cognito owns authentication; this table owns platform identity + org role.
-- ----------------------------------------------------------------------------
CREATE TABLE users (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id  uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    -- Nullable until the invited user completes first sign-in and we learn
    -- their Cognito sub from the JWT.
    cognito_sub      text UNIQUE,
    email            citext NOT NULL,
    display_name     text NOT NULL DEFAULT '',
    org_role         org_role NOT NULL DEFAULT 'member',
    status           user_status NOT NULL DEFAULT 'invited',
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organisation_id, email)
);

CREATE INDEX idx_users_org ON users (organisation_id);
-- Hot path: JWT middleware resolves users by cognito_sub on every request (§9).
CREATE INDEX idx_users_cognito_sub ON users (cognito_sub) WHERE cognito_sub IS NOT NULL;

-- ----------------------------------------------------------------------------
-- groups — named user collections for permission management (spec §9, §16).
-- ----------------------------------------------------------------------------
CREATE TABLE groups (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organisation_id  uuid NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 200),
    description      text NOT NULL DEFAULT '',
    created_by       uuid REFERENCES users(id) ON DELETE SET NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organisation_id, name)
);

CREATE TABLE group_members (
    group_id         uuid NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    added_by         uuid REFERENCES users(id) ON DELETE SET NULL,
    added_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, user_id)
);

CREATE INDEX idx_group_members_user ON group_members (user_id);

-- ----------------------------------------------------------------------------
-- updated_at trigger, reused by later migrations.
-- ----------------------------------------------------------------------------
CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_organisations_updated BEFORE UPDATE ON organisations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_users_updated BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_groups_updated BEFORE UPDATE ON groups
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
