from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import serializers

from tests.models import (
    Author, Book, Club, Membership,
    Product, ProductBook,
    UniqueCodeItem,
    ArticleWithLabel, ItemWithLabel, WidgetWithOptionalLabel,
    ProfileWithEmail, RecordWithEmailFallback, MultiFieldRecord,
    ItemWithAutoNow, ItemWithPreservedField,
    BookWithAllObjects,
)
from tombstone import AllObjectsManager, TombstoneSerializerMixin
from tombstone.conf import tombstone_settings
from tombstone.exceptions import TombstoneError
from tombstone.signals import pre_tombstone, post_tombstone


class TestDefaultQueryset(TestCase):
    def test_active_excludes_tombstoned_records(self):
        Author.objects.create(name="Alice", email="alice@example.com")
        Author.objects.create(name="Ghost", email="ghost@example.com", is_tombstone=True)
        self.assertEqual(Author.objects.count(), 1)
        self.assertEqual(Author.objects.first().name, "Alice")

    def test_tombstones_returns_only_placeholders(self):
        Author.objects.create(name="Alice", email="a@example.com")
        Author.objects.create(name="Ghost", email="g@example.com", is_tombstone=True)
        self.assertEqual(Author.objects.tombstones().count(), 1)

    def test_all_records_returns_everything(self):
        Author.objects.create(name="Alice", email="a@example.com")
        Author.objects.create(name="Ghost", email="g@example.com", is_tombstone=True)
        self.assertEqual(Author.objects.all_records().count(), 2)


class TestTombstoneInPlace(TestCase):
    """Original row is updated in place — same PK, no new row created."""

    def test_same_pk_after_deletion(self):
        author = Author.objects.create(name="Bob", email="bob@example.com")
        original_pk = author.pk
        tombstone = author.delete()

        self.assertEqual(tombstone.pk, original_pk)

    def test_row_still_exists_in_db(self):
        author = Author.objects.create(name="Carol", email="carol@example.com")
        pk = author.pk
        author.delete()

        self.assertTrue(Author.objects.all_records().filter(pk=pk).exists())

    def test_row_count_unchanged_after_deletion(self):
        Author.objects.create(name="Dave", email="dave@example.com")
        self.assertEqual(Author.objects.all_records().count(), 1)
        Author.objects.first().delete()
        self.assertEqual(Author.objects.all_records().count(), 1)

    def test_is_tombstone_set_to_true(self):
        author = Author.objects.create(name="Eve", email="eve@example.com")
        tombstone = author.delete()
        self.assertTrue(tombstone.is_tombstone)

    def test_tombstoned_at_is_set(self):
        before = timezone.now()
        author = Author.objects.create(name="Frank", email="frank@example.com")
        tombstone = author.delete()
        after = timezone.now()

        self.assertGreaterEqual(tombstone.tombstoned_at, before)
        self.assertLessEqual(tombstone.tombstoned_at, after)

    def test_tombstone_origin_id_equals_original_pk(self):
        author = Author.objects.create(name="Grace", email="grace@example.com")
        pk = author.pk
        tombstone = author.delete()

        self.assertEqual(tombstone.tombstone_origin_id, str(pk))

    def test_tombstone_visible_via_tombstones_manager(self):
        author = Author.objects.create(name="Henry", email="henry@example.com")
        author.delete()

        self.assertEqual(Author.objects.tombstones().count(), 1)
        self.assertEqual(Author.objects.count(), 0)


class TestEmptyShellPlaceholder(TestCase):
    """All business fields are cleared after tombstoning."""

    def test_business_fields_are_empty_after_deletion(self):
        author = Author.objects.create(name="Ivan", email="ivan@example.com")
        tombstone = author.delete()

        self.assertEqual(tombstone.name, "")
        self.assertEqual(tombstone.email, "")

    def test_product_fields_cleared(self):
        product = Product.objects.create(name="Laptop", price="999.00")
        tombstone = product.delete()

        self.assertEqual(tombstone.name, "")
        self.assertEqual(tombstone.price, 0)


class TestUniqueFieldAutoHandling(TestCase):
    """Unique-constrained fields are auto-suffixed — no config needed."""

    def test_unique_field_suffixed_on_tombstone(self):
        item = UniqueCodeItem.objects.create(code="SKU-001", label="Widget")
        tombstone = item.delete()

        self.assertIn("__tombstoned__", tombstone.code)

    def test_new_record_can_reuse_code_after_tombstone(self):
        item = UniqueCodeItem.objects.create(code="SKU-002", label="Gadget")
        item.delete()

        new_item = UniqueCodeItem.objects.create(code="SKU-002", label="New Gadget")
        self.assertIsNotNone(new_item.pk)

    def test_multiple_tombstones_dont_conflict(self):
        UniqueCodeItem.objects.create(code="SKU-003", label="A")
        UniqueCodeItem.objects.create(code="SKU-004", label="B")
        UniqueCodeItem.objects.all().delete()

        self.assertEqual(UniqueCodeItem.objects.tombstones().count(), 2)


class TestFKReferenceBehaviour(TestCase):
    def test_fk_stays_valid_after_tombstone(self):
        """FK references remain valid — same PK, no reassignment needed."""
        author = Author.objects.create(name="Judy", email="judy@example.com")
        book = Book.objects.create(title="Judy's Book", owner=author)
        pk = author.pk

        author.delete()

        book.refresh_from_db()
        self.assertEqual(book.owner_id, pk)

    def test_ref_delete_removes_related_objects(self):
        author = Author.objects.create(name="Karl", email="karl@example.com")
        club = Club.objects.create(title="Writers Club")
        Membership.objects.create(author=author, club=club)

        author.delete()

        self.assertEqual(Membership.objects.filter(club=club).count(), 0)

    def test_default_ref_keep_leaves_related_untouched(self):
        """No tombstone_ref_behavior = DEFAULT_REF_BEHAVIOR = 'keep'."""
        product = Product.objects.create(name="Chair", price="50.00")
        pb = ProductBook.objects.create(title="Manual", product=product)
        pk = product.pk

        product.delete()

        pb.refresh_from_db()
        self.assertEqual(pb.product_id, pk)


class TestTombstoneSettings(TestCase):
    def tearDown(self):
        tombstone_settings.reload()

    def test_default_ref_behavior_is_keep(self):
        self.assertEqual(tombstone_settings.DEFAULT_REF_BEHAVIOR, "keep")

    def test_settings_override_ref_behavior_to_delete(self):
        with override_settings(TOMBSTONE={"DEFAULT_REF_BEHAVIOR": "delete"}):
            tombstone_settings.reload()
            product = Product.objects.create(name="Table", price="100.00")
            ProductBook.objects.create(title="Manual", product=product)

            product.delete()

            self.assertEqual(ProductBook.objects.count(), 0)


class TestBulkDelete(TestCase):
    def test_queryset_delete_tombstones_all(self):
        Author.objects.create(name="A", email="a@example.com")
        Author.objects.create(name="B", email="b@example.com")

        Author.objects.all().delete()

        self.assertEqual(Author.objects.count(), 0)
        self.assertEqual(Author.objects.tombstones().count(), 2)

    def test_queryset_delete_returns_count(self):
        Author.objects.create(name="A", email="a@example.com")
        Author.objects.create(name="B", email="b@example.com")

        count, _ = Author.objects.all().delete()

        self.assertEqual(count, 2)

    def test_queryset_delete_skips_existing_tombstones(self):
        Author.objects.create(name="A", email="a@example.com", is_tombstone=True)

        count, _ = Author.objects.all_records().delete()

        self.assertEqual(count, 0)


class TestSignals(TestCase):
    def test_pre_tombstone_fires(self):
        received = []

        def handler(sender, instance, **kwargs):
            received.append(instance.pk)

        pre_tombstone.connect(handler, sender=Author)
        try:
            author = Author.objects.create(name="A", email="a@example.com")
            original_pk = author.pk
            author.delete()
            self.assertEqual(received, [original_pk])
        finally:
            pre_tombstone.disconnect(handler, sender=Author)

    def test_post_tombstone_fires_with_same_instance(self):
        received = []

        def handler(sender, instance, placeholder, **kwargs):
            received.append(placeholder)

        post_tombstone.connect(handler, sender=Author)
        try:
            author = Author.objects.create(name="B", email="b@example.com")
            tombstone = author.delete()
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].pk, tombstone.pk)
        finally:
            post_tombstone.disconnect(handler, sender=Author)


class TestIsIdentifiableAsPlaceholder(TestCase):
    def test_tombstone_flag_set_after_deletion(self):
        author = Author.objects.create(name="Laura", email="laura@example.com")
        tombstone = author.delete()
        self.assertTrue(tombstone.is_tombstone)

    def test_live_record_is_not_tombstone(self):
        author = Author.objects.create(name="Mallory", email="m@example.com")
        self.assertFalse(author.is_tombstone)


class TestGuardRails(TestCase):
    def test_cannot_tombstone_already_tombstoned_record(self):
        author = Author.objects.create(name="Niaj", email="n@example.com")
        author.delete()

        with self.assertRaises(TombstoneError):
            author.delete()

    def test_invalid_behaviour_raises(self):
        author = Author.objects.create(name="Oscar", email="o@example.com")
        author.tombstone_ref_behavior = {"memberships": "explode"}
        Club.objects.create(title="Club")

        with self.assertRaises(TombstoneError):
            author.delete()


class TestDeletedLabel(TestCase):
    def tearDown(self):
        tombstone_settings.reload()

    # -- basic label building --------------------------------------------------

    def test_single_field_label(self):
        obj = ArticleWithLabel.objects.create(title="My Article", body="some content")
        tombstone = obj.delete()
        self.assertIn("My Article", tombstone.tombstone_label)

    def test_multiple_field_label(self):
        obj = ItemWithLabel.objects.create(title="Invoice Q1", code="INV-001")
        tombstone = obj.delete()
        self.assertIn("Invoice Q1", tombstone.tombstone_label)
        self.assertIn("INV-001", tombstone.tombstone_label)

    def test_empty_field_falls_back_to_class_name(self):
        obj = WidgetWithOptionalLabel.objects.create(name="")
        tombstone = obj.delete()
        self.assertIn("WidgetWithOptionalLabel", tombstone.tombstone_label)

    def test_no_label_field_falls_back_to_class_name(self):
        author = Author.objects.create(name="Alice", email="alice@example.com")
        tombstone = author.delete()
        self.assertIn("Author", tombstone.tombstone_label)

    # -- DELETED_LABEL_FORMAT -------------------------------------------------

    def test_default_format_applied(self):
        obj = ArticleWithLabel.objects.create(title="Test Article", body="")
        tombstone = obj.delete()
        self.assertEqual(tombstone.tombstone_label, "Deleted - Test Article")

    def test_format_percent_replaced(self):
        with override_settings(TOMBSTONE={"DELETED_LABEL_FORMAT": "Archived: %"}):
            tombstone_settings.reload()
            obj = ArticleWithLabel.objects.create(title="Widget", body="")
            tombstone = obj.delete()
            self.assertEqual(tombstone.tombstone_label, "Archived: Widget")

    def test_format_with_no_prefix(self):
        with override_settings(TOMBSTONE={"DELETED_LABEL_FORMAT": "%"}):
            tombstone_settings.reload()
            obj = ArticleWithLabel.objects.create(title="Widget", body="")
            tombstone = obj.delete()
            self.assertEqual(tombstone.tombstone_label, "Widget")

    # -- email detection ------------------------------------------------------

    def test_single_email_field_wrapped_in_brackets(self):
        obj = ProfileWithEmail.objects.create(email="alice@example.com")
        tombstone = obj.delete()
        self.assertIn("(alice@example.com)", tombstone.tombstone_label)

    def test_single_empty_email_field_falls_back_to_class_name(self):
        obj = ProfileWithEmail.objects.create(email="")
        tombstone = obj.delete()
        self.assertIn("ProfileWithEmail", tombstone.tombstone_label)

    # -- smart fallback chain -------------------------------------------------

    def test_fallback_chain_all_fields_combined(self):
        """All non-email fields non-empty → joined together."""
        obj = RecordWithEmailFallback.objects.create(
            title="Project Alpha", code="PRJ-001", contact_email="ops@example.com"
        )
        tombstone = obj.delete()
        self.assertIn("Project Alpha PRJ-001", tombstone.tombstone_label)

    def test_fallback_chain_first_field_only(self):
        """Second non-email field empty → uses first field alone."""
        obj = RecordWithEmailFallback.objects.create(
            title="Project Alpha", code="", contact_email="ops@example.com"
        )
        tombstone = obj.delete()
        self.assertIn("Project Alpha", tombstone.tombstone_label)
        self.assertNotIn("(ops@example.com)", tombstone.tombstone_label)

    def test_fallback_chain_second_field_only(self):
        """First non-email field empty → uses second field alone."""
        obj = RecordWithEmailFallback.objects.create(
            title="", code="PRJ-001", contact_email="ops@example.com"
        )
        tombstone = obj.delete()
        self.assertIn("PRJ-001", tombstone.tombstone_label)

    def test_fallback_chain_email_when_other_fields_empty(self):
        """All non-email fields empty → falls back to email wrapped in brackets."""
        obj = RecordWithEmailFallback.objects.create(
            title="", code="", contact_email="ops@example.com"
        )
        tombstone = obj.delete()
        self.assertIn("(ops@example.com)", tombstone.tombstone_label)

    def test_fallback_chain_class_name_when_all_empty(self):
        """All fields empty → falls back to model class name."""
        obj = RecordWithEmailFallback.objects.create(
            title="", code="", contact_email=""
        )
        tombstone = obj.delete()
        self.assertIn("RecordWithEmailFallback", tombstone.tombstone_label)

    def test_fallback_chain_joins_all_available_fields(self):
        """Partial data: joins ALL non-empty non-email fields, not just the first."""
        obj = MultiFieldRecord.objects.create(title="Project Alpha", code="", reference="REF-001")
        tombstone = obj.delete()
        self.assertEqual(tombstone.tombstone_label, "Deleted - Project Alpha REF-001")


class TestAllObjectsManager(TestCase):
    def test_all_objects_includes_tombstones(self):
        author = Author.objects.create(name="Alice", email="alice@example.com")
        author.delete()
        self.assertEqual(Author.objects.count(), 0)
        self.assertEqual(Author.all_objects.count(), 1)

    def test_objects_excludes_tombstones(self):
        Author.objects.create(name="Alice", email="alice@example.com")
        author2 = Author.objects.create(name="Bob", email="bob@example.com")
        author2.delete()
        self.assertEqual(Author.objects.count(), 1)

    def test_all_objects_manager_type(self):
        self.assertIsInstance(Author.all_objects, AllObjectsManager)

    def test_related_accessor_includes_tombstoned_record_via_base_manager(self):
        author = Author.objects.create(name="Carol", email="carol@example.com")
        book = BookWithAllObjects.objects.create(title="Test Book", author=author)
        author.delete()

        book.refresh_from_db()
        self.assertIsNotNone(book.author)
        self.assertTrue(book.author.is_tombstone)


class TestTombstoneSerializerMixin(TestCase):
    class _ArticleSerializer(TombstoneSerializerMixin, serializers.ModelSerializer):
        class Meta:
            model = ArticleWithLabel
            fields = [
                'id', 'title', 'body',
                'is_tombstone', 'tombstone_label',
                'tombstone_origin_id', 'tombstoned_at',
            ]

    def test_to_representation_returns_placeholder_for_tombstone(self):
        obj = ArticleWithLabel.objects.create(title="Gone", body="content")
        tombstone = obj.delete()

        data = self._ArticleSerializer(tombstone).data

        self.assertSetEqual(
            set(data.keys()),
            {'id', 'is_tombstone', 'tombstone_label', 'tombstone_origin_id', 'tombstoned_at'},
        )
        self.assertTrue(data['is_tombstone'])
        self.assertIn('T', data['tombstoned_at'])  # ISO 8601 separator

    def test_to_representation_passes_through_for_active_record(self):
        obj = ArticleWithLabel.objects.create(title="Active Article", body="content")

        data = self._ArticleSerializer(obj).data

        self.assertFalse(data['is_tombstone'])
        self.assertEqual(data['title'], "Active Article")


class TestClearBusinessFields(TestCase):
    def test_auto_now_add_field_not_cleared(self):
        item = ItemWithAutoNow.objects.create(title="Test")
        tombstone = item.delete()
        self.assertIsNotNone(tombstone.created_at)

    def test_auto_now_field_not_cleared(self):
        item = ItemWithAutoNow.objects.create(title="Test")
        tombstone = item.delete()
        self.assertIsNotNone(tombstone.updated_at)

    def test_auto_now_field_not_in_tombstone_as_none(self):
        item = ItemWithAutoNow.objects.create(title="Test")
        tombstone = item.delete()
        # title is cleared, auto fields are untouched
        self.assertEqual(tombstone.title, "")
        self.assertIsNotNone(tombstone.updated_at)

    def test_preserve_fields_survive_clearing(self):
        item = ItemWithPreservedField.objects.create(
            title="Widget", category="Electronics"
        )
        tombstone = item.delete()
        self.assertEqual(tombstone.category, "Electronics")

    def test_non_preserved_fields_are_cleared(self):
        item = ItemWithPreservedField.objects.create(
            title="Widget", category="Electronics"
        )
        tombstone = item.delete()
        self.assertEqual(tombstone.title, "")
