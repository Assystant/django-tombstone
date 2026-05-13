# django-tombstone

A reusable Django mixin that replaces `delete()` with a **tombstone-first hard delete**: a placeholder row is written to the same table before the original is removed. FK/M2M references are reassigned to the placeholder automatically — zero config required.

## Installation

```bash
pip install -e .
```

The `tombstone` package has no migrations of its own — the three tombstone columns (`is_tombstone`, `tombstoned_at`, `tombstone_origin_id`) are added to your model's own table when you run `makemigrations`.

---

## Zero-config usage

No configuration needed. Just inherit and migrate:

```python
from django.db import models
from tombstone import TombstoneMixin


class Order(TombstoneMixin, models.Model):
    number = models.CharField(max_length=50)
    total  = models.DecimalField(max_digits=10, decimal_places=2)
```

```bash
python manage.py makemigrations myapp
python manage.py migrate
```

```python
order = Order.objects.get(pk=1)
placeholder = order.delete()

# placeholder.is_tombstone        == True
# placeholder.tombstoned_at       == <datetime>
# placeholder.tombstone_origin_id == "1"   (original pk)
# placeholder.number              == ""    (empty — default behaviour)
# original row pk=1 is gone
```

**Default behaviour (no config):**
- Placeholder is an **empty shell** — no business fields retained.
- All reverse FK/M2M references are **reassigned to the placeholder**.

---

## Global defaults via settings.py

Works exactly like `REST_FRAMEWORK` or `SIMPLE_JWT` — add to your `settings.py`:

```python
TOMBSTONE = {
    'DEFAULT_RETAINED_FIELDS': [],        # [] = empty placeholder (default)
    'DEFAULT_REF_BEHAVIOR':    'tombstone', # reassign all FKs (default)
    'DEFAULT_UNIQUE_FIELDS':   [],
}
```

| Key | Default | Effect |
|---|---|---|
| `DEFAULT_RETAINED_FIELDS` | `[]` | Fields copied to every placeholder when not set on the model |
| `DEFAULT_REF_BEHAVIOR` | `"tombstone"` | FK/M2M policy for any relation not listed on the model |
| `DEFAULT_UNIQUE_FIELDS` | `[]` | Unique fields to UUID-suffix on every placeholder when not set on the model |

**Resolution order — highest to lowest:**
```
Model class attribute  →  TOMBSTONE in settings.py  →  built-in default
```

---

## Per-model configuration

Override defaults on any model that needs a different policy:

```python
class User(TombstoneMixin, models.Model):
    name  = models.CharField(max_length=200)
    email = models.EmailField(unique=True)

    # Fields copied to the placeholder (None = copy all fields)
    tombstone_retained_fields = ["name", "email"]

    # Per-relation policy (unlisted relations use DEFAULT_REF_BEHAVIOR)
    tombstone_ref_behavior = {
        "projects":   "tombstone",  # reassign FK → placeholder
        "sessions":   "delete",     # cascade-delete related rows
        "audit_logs": "keep",       # no-op — our code does not touch it
    }

    # Unique fields that need a UUID suffix so the slot can be reused
    tombstone_unique_fields = ["email"]
```

---

## How delete() works

```python
user = User.objects.get(pk=42)
placeholder = user.delete()
```

Steps inside a **single atomic transaction**:

1. `pre_tombstone` signal fires.
2. Placeholder row inserted — `is_tombstone=True`, `tombstoned_at=now()`, `tombstone_origin_id="42"`, retained fields copied.
3. Each reverse FK/M2M handled per `tombstone_ref_behavior`.
4. Original row hard-deleted.
5. `post_tombstone` signal fires with the placeholder.

The placeholder record is returned.

---

## Configuration reference

### `tombstone_retained_fields`

| Value | Behaviour |
|---|---|
| Not set (default) | Uses `DEFAULT_RETAINED_FIELDS` from `TOMBSTONE` settings (default: `[]`) |
| `None` | Copies **all** concrete non-PK fields to the placeholder |
| `["field_a", "field_b"]` | Only the listed fields are copied; all others use their model default or `null` |

### `tombstone_ref_behavior`

Maps the **related accessor name** to one of three behaviours.
Unlisted relations fall back to `DEFAULT_REF_BEHAVIOR` from `TOMBSTONE` settings (default: `"tombstone"`).

| Behaviour | FK effect | M2M effect |
|---|---|---|
| `"tombstone"` | `UPDATE related SET fk = placeholder.pk` | Through-table rows updated to placeholder |
| `"delete"` | Related rows deleted | Through-table rows deleted |
| `"keep"` | No-op | No-op |

### `tombstone_unique_fields`

Fields with `unique=True` get a UUID suffix on the placeholder, freeing the slot for future records.

```python
tombstone_unique_fields = ["email"]
# placeholder.email = "alice@example.com__a3f9...uuid...7c1__tombstoned"
```

### `tombstone_origin_id`

Automatically set on every placeholder. Stores the original `pk` as a string — useful for audit trails and restoration.

```python
placeholder.tombstone_origin_id  # "42"
```

---

## Querysets

The default manager excludes tombstone records automatically. Bulk `.delete()` also goes through tombstone creation — it does not issue a raw SQL `DELETE`.

```python
User.objects.all()                            # live records only
User.objects.tombstones()                     # placeholder records only
User.objects.all_records()                    # everything (migrations / admin)

User.objects.filter(is_active=False).delete() # creates tombstones, not raw DELETE
```

---

## Signals

```python
from tombstone import pre_tombstone, post_tombstone

def on_post(sender, instance, placeholder, **kwargs):
    cache.delete(f"user:{instance.pk}")   # cache invalidation
    search_index.remove(instance.pk)      # search index cleanup

post_tombstone.connect(on_post, sender=User)
```

| Signal | Arguments | When |
|---|---|---|
| `pre_tombstone` | `sender`, `instance` | Before transaction begins |
| `post_tombstone` | `sender`, `instance`, `placeholder` | After transaction commits |

---

## Guard rails

```python
from tombstone import TombstoneError
```

| Scenario | Result |
|---|---|
| `.delete()` called on a placeholder | `TombstoneError` |
| Unknown field in `tombstone_retained_fields` | `TombstoneError` |
| Invalid value in `tombstone_ref_behavior` | `TombstoneError` |
| Recursive deletion cycle (A → B → A) | Cycle detected and broken automatically |

---

## Onboarding an existing model

1. Add `TombstoneMixin` as the **first** base class before `models.Model`.
2. Run `makemigrations` / `migrate` — three columns are added; existing rows are unaffected.
3. Optionally configure `tombstone_retained_fields`, `tombstone_ref_behavior`, `tombstone_unique_fields` per model.
4. Optionally set global defaults in `settings.py` under `TOMBSTONE`.

```python
# Minimal onboarding — zero config, uses global defaults
class Invoice(TombstoneMixin, models.Model):
    number = models.CharField(max_length=50, unique=True)
    total  = models.DecimalField(max_digits=10, decimal_places=2)


# Full onboarding — explicit per-model policy
class Invoice(TombstoneMixin, models.Model):
    number = models.CharField(max_length=50, unique=True)
    total  = models.DecimalField(max_digits=10, decimal_places=2)

    tombstone_retained_fields = ["number", "total"]
    tombstone_unique_fields   = ["number"]
    tombstone_ref_behavior    = {
        "line_items": "tombstone",
        "payments":   "keep",
    }
```

---

## Known limitations

| Limitation | Detail |
|---|---|
| **GenericForeignKey / GenericRelation** | Not supported. Handle via `post_tombstone` signal manually. |
| **Large relation updates** | `"tombstone"` policy issues a single `UPDATE` — may lock large tables. Consider batching via `post_tombstone` at scale. |
| **Bulk delete performance** | `QuerySet.delete()` iterates per object. Correct but not optimal for very large sets. |
| **Non-integer PKs** | `tombstone_origin_id` stores `str(pk)` — works with UUID and integer PKs alike. |

---

## Running the tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e . pytest pytest-django
pytest
```
