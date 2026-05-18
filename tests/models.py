from django.db import models
from tombstone import TombstoneMixin


class Author(TombstoneMixin, models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField()

    tombstone_ref_behavior = {
        "memberships": "delete",
    }

    class Meta:
        app_label = "tests"


class Club(models.Model):
    title = models.CharField(max_length=200)

    class Meta:
        app_label = "tests"


class Book(models.Model):
    title = models.CharField(max_length=200)
    owner = models.ForeignKey(
        Author,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="books",
    )

    class Meta:
        app_label = "tests"


class Membership(models.Model):
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="memberships")
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="memberships")

    class Meta:
        app_label = "tests"


class Product(TombstoneMixin, models.Model):
    """No config — uses TOMBSTONE settings defaults entirely."""
    name = models.CharField(max_length=200)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        app_label = "tests"


class ProductBook(models.Model):
    title = models.CharField(max_length=200)
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product_books",
    )

    class Meta:
        app_label = "tests"


class UniqueCodeItem(TombstoneMixin, models.Model):
    """Tests automatic unique-field constraint handling."""
    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=200)

    class Meta:
        app_label = "tests"


class ArticleWithLabel(TombstoneMixin, models.Model):
    """tombstone_label_field = single string field."""
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")

    tombstone_label_field = "title"

    class Meta:
        app_label = "tests"


class ItemWithLabel(TombstoneMixin, models.Model):
    """tombstone_label_field = list of two generic fields."""
    title = models.CharField(max_length=200, blank=True, default="")
    code = models.CharField(max_length=50, blank=True, default="")

    tombstone_label_field = ["title", "code"]

    class Meta:
        app_label = "tests"


class WidgetWithOptionalLabel(TombstoneMixin, models.Model):
    """tombstone_label_field set, but value may be empty — should fall back to class name."""
    name = models.CharField(max_length=200, blank=True, default="")

    tombstone_label_field = "name"

    class Meta:
        app_label = "tests"


class ProfileWithEmail(TombstoneMixin, models.Model):
    """tombstone_label_field = single email field — value wrapped in brackets."""
    email = models.EmailField(blank=True, default="")

    tombstone_label_field = "email"

    class Meta:
        app_label = "tests"


class RecordWithEmailFallback(TombstoneMixin, models.Model):
    """tombstone_label_field list with generic fields + email as last-resort fallback."""
    title = models.CharField(max_length=200, blank=True, default="")
    code = models.CharField(max_length=50, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")

    tombstone_label_field = ["title", "code", "contact_email"]

    class Meta:
        app_label = "tests"


class MultiFieldRecord(TombstoneMixin, models.Model):
    """Three non-email fields — proves that all available values are joined, not just the first."""
    title = models.CharField(max_length=200, blank=True, default="")
    code = models.CharField(max_length=50, blank=True, default="")
    reference = models.CharField(max_length=50, blank=True, default="")

    tombstone_label_field = ["title", "code", "reference"]

    class Meta:
        app_label = "tests"


class ItemWithAutoNow(TombstoneMixin, models.Model):
    """Tests that auto_now / auto_now_add fields are skipped during clearing."""
    title = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'tests'


class ItemWithPreservedField(TombstoneMixin, models.Model):
    """Tests tombstone_preserve_fields — specified fields survive clearing."""
    title = models.CharField(max_length=200)
    category = models.CharField(max_length=100)

    tombstone_preserve_fields = ['category']

    class Meta:
        app_label = 'tests'


class BookWithAllObjects(models.Model):
    """FK to Author — used to test base_manager_name behaviour."""
    title = models.CharField(max_length=200)
    author = models.ForeignKey(
        Author,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='all_books',
    )

    class Meta:
        app_label = 'tests'
