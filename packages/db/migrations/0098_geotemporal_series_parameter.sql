-- ============================================================================
-- 0098_geotemporal_series_parameter.sql
-- Geotemporal series as an action parameter type (§427; `action-types` p.131).
--
-- > "Property type | Parameter type | Supported ... Geotemporal series
-- >  reference | Geotemporal series reference | Yes (OSv2 only)"
--
-- The OSv2 caveat is a Foundry storage-backend distinction this platform has
-- no counterpart for - instances live in OpenSearch (db 0026) and there is one
-- backend - so the row reads as a plain Yes here.
--
-- Its own migration, and the reason is the same as 0095's: every edit to an
-- instance goes through an action, so a type that could be declared and synced
-- but never typed would be half a type - and `property_data_type` and
-- `action_parameter_type` are two enums on purpose (db 0044), guarded against
-- drift by `test_every_property_type_can_be_an_action_parameter`.
-- ============================================================================

ALTER TYPE action_parameter_type ADD VALUE IF NOT EXISTS 'geotemporal_series';
