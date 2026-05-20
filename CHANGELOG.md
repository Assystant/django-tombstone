# Changelog

## Unreleased

### Added
- `AllObjectsManager` — returns all rows (live + tombstoned) while still exposing
  `.active()`, `.tombstones()`, and `.all_records()` from `TombstoneQuerySet`.
- `all_objects = AllObjectsManager()` on `TombstoneMixin` — available on every
  subclass automatically, no per-model setup required.
- `base_manager_name = 'all_objects'` in `TombstoneMixin.Meta` — ensures Django's
  internal ORM operations (related accessors, `prefetch_related`, `select_related`)
  use `AllObjectsManager` so tombstoned records are never silently dropped from
  related queries.
- `TombstoneSerializerMixin` in `tombstone/serializers.py` — a DRF
  `ModelSerializer` mixin that replaces the full field set with a minimal tombstone
  placeholder shape when the instance is a tombstone, preventing serializer errors
  on cleared business fields. File is importable without DRF installed.
- `use_in_migrations = True` on both `TombstoneManager` and `AllObjectsManager` —
  suppresses Django's migration warning about custom managers.

### Exports
`AllObjectsManager` and `TombstoneSerializerMixin` are now exported from the
top-level `tombstone` package.

## [1.0.0] - 2026-05-18

Initial release.

