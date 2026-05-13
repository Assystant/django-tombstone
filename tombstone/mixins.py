import threading
import uuid

from django.db import models, transaction
from django.db.models.fields.related import ManyToOneRel, ManyToManyRel
from django.utils import timezone

from .conf import tombstone_settings
from .managers import TombstoneManager
from .exceptions import TombstoneError
from .signals import pre_tombstone, post_tombstone

_MIXIN_FIELDS = frozenset({"is_tombstone", "tombstoned_at", "tombstone_origin_id"})

REF_DELETE = "delete"
REF_KEEP   = "keep"
_VALID_BEHAVIOURS = {REF_DELETE, REF_KEEP}

_processing = threading.local()


class _Unset:
    pass


_UNSET = _Unset()


def _active_keys():
    if not hasattr(_processing, "keys"):
        _processing.keys = set()
    return _processing.keys


class TombstoneMixin(models.Model):
    """
    Abstract mixin — tombstones a record by updating it in place.

    The original row keeps its PK. All business fields are cleared to
    their defaults. No new row is created. FK references remain valid
    naturally because the PK never changes.

    Class-level configuration (optional):
        tombstone_ref_behavior (dict[str, str]):
            Maps related accessor name → 'delete' | 'keep'.
            'delete' — cascade-delete related objects when this record is tombstoned.
            'keep'   — leave related objects untouched (default).
            Unlisted relations use DEFAULT_REF_BEHAVIOR from TOMBSTONE settings.

    Global defaults via settings.py:
        TOMBSTONE = {
            'DEFAULT_REF_BEHAVIOR': 'keep',
        }
    """

    is_tombstone = models.BooleanField(default=False, db_index=True)
    tombstoned_at = models.DateTimeField(null=True, blank=True, db_index=True)
    tombstone_origin_id = models.CharField(max_length=255, null=True, blank=True)

    objects = TombstoneManager()

    tombstone_ref_behavior = _UNSET

    class Meta:
        abstract = True

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def delete(self, using=None, keep_parents=False):
        if self.is_tombstone:
            raise TombstoneError("Record is already tombstoned.")

        db = using or self._state.db
        key = (self.__class__, self.pk)
        active = _active_keys()

        if key in active:
            return None

        active.add(key)
        try:
            pre_tombstone.send(sender=self.__class__, instance=self)
            with transaction.atomic(using=db):
                self._clear_business_fields()
                self.is_tombstone = True
                self.tombstoned_at = timezone.now()
                self.tombstone_origin_id = str(self.pk)
                self.save(using=db)
                self._handle_delete_refs(db)
            post_tombstone.send(sender=self.__class__, instance=self, placeholder=self)
        finally:
            active.discard(key)

        return self

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clear_business_fields(self):
        for field in self._meta.concrete_fields:
            if field.primary_key or field.name in _MIXIN_FIELDS:
                continue

            if field.is_relation:
                if field.null:
                    setattr(self, field.attname, None)
                continue

            if getattr(field, 'unique', False) and not field.null:
                setattr(self, field.attname, f"__tombstoned__{uuid.uuid4().hex}")
            elif field.null:
                setattr(self, field.attname, None)
            else:
                setattr(self, field.attname, field.get_default())

    def _handle_delete_refs(self, db):
        for field in self._meta.get_fields():
            if not field.is_relation:
                continue
            if isinstance(field, ManyToOneRel):
                if self._resolved_behaviour(field.get_accessor_name()) == REF_DELETE:
                    field.related_model._base_manager.using(db).filter(
                        **{field.field.name: self.pk}
                    ).delete()
            elif isinstance(field, ManyToManyRel):
                if self._resolved_behaviour(field.get_accessor_name()) == REF_DELETE:
                    field.through._default_manager.using(db).filter(
                        **{field.field.m2m_field_name(): self.pk}
                    ).delete()

    def _resolved_behaviour(self, accessor: str) -> str:
        ref_behavior = self.tombstone_ref_behavior
        if isinstance(ref_behavior, _Unset):
            behaviour = tombstone_settings.DEFAULT_REF_BEHAVIOR
        else:
            behaviour = ref_behavior.get(accessor, tombstone_settings.DEFAULT_REF_BEHAVIOR)

        if behaviour not in _VALID_BEHAVIOURS:
            raise TombstoneError(
                f"Invalid tombstone_ref_behavior '{behaviour}' for '{accessor}'. "
                f"Must be one of: {sorted(_VALID_BEHAVIOURS)}."
            )
        return behaviour
