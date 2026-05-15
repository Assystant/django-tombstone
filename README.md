# django-tombstone

A reusable Django mixin that replaces `delete()` with a **tombstone-first hard delete**: a placeholder row is written to the same table before the original is removed. FK/M2M references are reassigned to the placeholder automatically — zero config required.

## Installation

```bash
pip install -e .
```

The `tombstone` package has no migrations of its own — the four tombstone columns (`is_tombstone`, `tombstoned_at`, `tombstone_origin_id`, `tombstone_label`) are added to your model's own table when you run `makemigrations`.

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
# placeholder.tombstone_origin_id == "1"       (original pk)
# placeholder.tombstone_label     == "Deleted - Order"
# placeholder.number              == ""        (cleared — default behaviour)
# same row pk=1 still exists, updated in place
```

**Default behaviour (no config):**
- Original row is **updated in place** — same PK, no new row created.
- All business fields are cleared to their defaults.
- FK references remain valid automatically because the PK never changes.

---

## Global defaults via settings.py

Works exactly like `REST_FRAMEWORK` or `SIMPLE_JWT` — add to your `settings.py`:

```python
TOMBSTONE = {
    'DEFAULT_REF_BEHAVIOR': 'keep',        # 'keep' | 'delete'
    'DELETED_LABEL_FORMAT': 'Deleted - %', # % is replaced by the resolved label value
}
```

| Key | Default | Effect |
|---|---|---|
| `DEFAULT_REF_BEHAVIOR` | `"keep"` | FK/M2M policy for any relation not listed on the model (`"keep"` or `"delete"`) |
| `DELETED_LABEL_FORMAT` | `"Deleted - %"` | Format string for the tombstone label; `%` is replaced by the resolved label value |

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

    # Per-relation policy (unlisted relations use DEFAULT_REF_BEHAVIOR)
    tombstone_ref_behavior = {
        "sessions":   "delete",  # cascade-delete related rows
        "audit_logs": "keep",    # no-op — leave untouched
    }

    # Field(s) used to build the human-readable tombstone label
    tombstone_label_field = "name"                                  # single field
    # tombstone_label_field = ["title", "code", "contact_email"]   # or multiple
```

---

## How delete() works

```python
user = User.objects.get(pk=42)
placeholder = user.delete()
```

Steps inside a **single atomic transaction**:

1. `pre_tombstone` signal fires.
2. `tombstone_label` is built from the live field values (before clearing).
3. All business fields on the row are cleared to their defaults.
4. `is_tombstone=True`, `tombstoned_at=now()`, `tombstone_origin_id="42"` are set.
5. The row is saved — same PK, no new row created.
6. Related FK/M2M objects are handled per `tombstone_ref_behavior`.
7. `post_tombstone` signal fires with the updated placeholder.

The same object (now a tombstone) is returned.

---

## Configuration reference

### `tombstone_ref_behavior`

Maps the **related accessor name** to a behaviour.
Unlisted relations fall back to `DEFAULT_REF_BEHAVIOR` from `TOMBSTONE` settings (default: `"keep"`).

| Behaviour | FK effect | M2M effect |
|---|---|---|
| `"delete"` | Related rows deleted | Through-table rows deleted |
| `"keep"` | No-op | No-op |

```python
tombstone_ref_behavior = {
    "memberships": "delete",  # cascade-delete when this record is tombstoned
    "books":       "keep",    # leave books untouched
}
```

### Unique fields

Fields with `unique=True` are automatically UUID-suffixed when the row is tombstoned, freeing the slot for future records. No configuration needed.

```python
# Before: code = "SKU-001"
# After:  code = "__tombstoned__a3f9...uuid...7c1"
```

### `tombstone_label_field`

Specifies which field(s) to read when building the human-readable label stored in `tombstone_label`. Values are read **before** business fields are cleared.

**Single field** — point at any field on any model:

```python
# Invoice
tombstone_label_field = "invoice_number"
# placeholder.tombstone_label → "Deleted - INV-0042"

# Project
tombstone_label_field = "project_name"
# placeholder.tombstone_label → "Deleted - Website Redesign"

# Any field whose name contains 'email' → value wrapped in brackets
tombstone_label_field = "contact_email"
# placeholder.tombstone_label → "Deleted - (billing@acme.com)"
```

**Multiple fields — smart fallback chain:**

When a list is provided, the system collects values and applies this chain:

1. Join **all non-empty non-email fields** (whatever is available — one, some, or all)
2. If no non-email field has a value, use any **email field** wrapped in brackets
3. If nothing has a value, use the **model class name**

```python
# Works for any model — invoice, project, order, subscription, etc.
tombstone_label_field = ["title", "code", "reference", "contact_email"]
```

| Scenario | `tombstone_label` value |
|---|---|
| `title="Project Alpha"`, `code="PRJ-001"`, `reference="REF-001"` | `"Project Alpha PRJ-001 REF-001"` |
| `title="Project Alpha"`, `code=""`, `reference="REF-001"` | `"Project Alpha REF-001"` |
| `title=""`, `code="PRJ-001"`, `reference=""` | `"PRJ-001"` |
| `title=""`, `code=""`, `reference=""`, `contact_email="ops@co.com"` | `"(ops@co.com)"` |
| All fields empty | Model class name |

**Format controlled globally via `DELETED_LABEL_FORMAT`:**

```python
TOMBSTONE = {
    'DELETED_LABEL_FORMAT': 'Deleted - %',  # default — % replaced by label value
}
```

| Format | Label value | Result |
|---|---|---|
| `"Deleted - %"` | `"INV-0042"` | `"Deleted - INV-0042"` |
| `"Archived: %"` | `"Project Alpha"` | `"Archived: Project Alpha"` |
| `"%"` | `"Order"` | `"Order"` |

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
| Invalid value in `tombstone_ref_behavior` | `TombstoneError` |
| Recursive deletion cycle (A → B → A) | Cycle detected and broken automatically |

---

## Onboarding an existing model

1. Add `TombstoneMixin` as the **first** base class before `models.Model`.
2. Run `makemigrations` / `migrate` — three columns are added; existing rows are unaffected.
3. Optionally configure `tombstone_ref_behavior` and `tombstone_label_field` per model.
4. Optionally set global defaults in `settings.py` under `TOMBSTONE`.

```python
# Minimal onboarding — zero config
class Invoice(TombstoneMixin, models.Model):
    number = models.CharField(max_length=50, unique=True)
    total  = models.DecimalField(max_digits=10, decimal_places=2)


# Full onboarding — explicit per-model policy
class Invoice(TombstoneMixin, models.Model):
    number = models.CharField(max_length=50, unique=True)
    total  = models.DecimalField(max_digits=10, decimal_places=2)

    tombstone_label_field = "number"
    tombstone_ref_behavior = {
        "line_items": "delete",
        "payments":   "keep",
    }
```

---

## Known limitations

| Limitation | Detail |
|---|---|
| **GenericForeignKey / GenericRelation** | Not supported. Handle via `post_tombstone` signal manually. |
| **Bulk delete performance** | `QuerySet.delete()` iterates per object. Correct but not optimal for very large sets. |
| **Non-integer PKs** | `tombstone_origin_id` stores `str(pk)` — works with UUID and integer PKs alike. |
| **tombstone_label max length** | `tombstone_label` is capped at 512 characters. Truncate long field values before tombstoning if needed. |

---

## Running the tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e . pytest pytest-django
pytest
```
