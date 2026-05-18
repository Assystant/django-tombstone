import threading
import uuid

from django.db import models, transaction
from django.db.models.fields.related import ManyToOneRel, ManyToManyRel
from django.utils import timezone

from .conf import tombstone_settings
from .managers import TombstoneManager, AllObjectsManager
from .exceptions import TombstoneError
from .signals import pre_tombstone, post_tombstone

_MIXIN_FIELDS = frozenset({"is_tombstone", "tombstoned_at", "tombstone_origin_id", "tombstone_label"})

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
    tombstone_label = models.CharField(max_length=512, null=True, blank=True)

    objects = TombstoneManager()
    all_objects = AllObjectsManager()

    tombstone_ref_behavior = _UNSET
    tombstone_label_field = _UNSET
    tombstone_preserve_fields = _UNSET

    class Meta:
        abstract = True
        base_manager_name = 'all_objects'

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
                self.tombstone_label = self._build_deleted_label()
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
        preserve = set()
        if not isinstance(self.tombstone_preserve_fields, _Unset):
            preserve = set(self.tombstone_preserve_fields)

        for field in self._meta.concrete_fields:
            if field.primary_key or field.name in _MIXIN_FIELDS:
                continue
            if field.name in preserve or field.attname in preserve:
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

    def _build_deleted_label(self) -> str:
        fmt = tombstone_settings.DELETED_LABEL_FORMAT
        label_field = self.tombstone_label_field

        if isinstance(label_field, _Unset):
            value = self.__class__.__name__
        elif isinstance(label_field, str):
            raw = str(getattr(self, label_field, "") or "")
            if raw:
                value = f"({raw})" if "email" in label_field else raw
            else:
                value = self.__class__.__name__
        else:
            value = self._resolve_label_from_fields(list(label_field))

        return fmt.replace("%", value)

    def _resolve_label_from_fields(self, field_names: list) -> str:
        email_fields = [f for f in field_names if "email" in f]
        other_fields = [f for f in field_names if "email" not in f]

        if other_fields:
            available = [
                str(getattr(self, f, "") or "")
                for f in other_fields
                if str(getattr(self, f, "") or "")
            ]
            if available:
                return " ".join(available)

        for f in email_fields:
            v = str(getattr(self, f, "") or "")
            if v:
                return f"({v})"

        return self.__class__.__name__

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
