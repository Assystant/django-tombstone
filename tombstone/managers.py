from django.db import models


class TombstoneQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_tombstone=False)

    def tombstones(self):
        return self.filter(is_tombstone=True)

    def all_records(self):
        return self

    def delete(self):
        """
        Override bulk delete so each object goes through tombstone creation.
        Falls back to Django's delete() for tombstone placeholder rows.
        """
        active = self.filter(is_tombstone=False)
        count = 0
        for obj in active:
            obj.delete()
            count += 1
        return count, {self.model._meta.label: count}


class TombstoneManager(models.Manager):
    def get_queryset(self):
        return TombstoneQuerySet(self.model, using=self._db).active()

    def tombstones(self):
        return TombstoneQuerySet(self.model, using=self._db).tombstones()

    def all_records(self):
        return TombstoneQuerySet(self.model, using=self._db)
