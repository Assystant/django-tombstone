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
