class TombstoneSerializerMixin:
    """
    Add to any DRF ModelSerializer to render tombstone placeholder records.

    When the instance is a tombstone, the full field set is replaced with
    a minimal placeholder containing only tombstone metadata. This prevents
    serializer errors caused by cleared/nulled business fields and gives the
    frontend a consistent shape to detect and display deleted-record labels.

    Usage:
        class ProjectSerializer(TombstoneSerializerMixin, serializers.ModelSerializer):
            ...
    """

    def to_representation(self, instance):
        if getattr(instance, 'is_tombstone', False):
            return {
                'id': instance.pk,
                'is_tombstone': True,
                'tombstone_label': instance.tombstone_label,
                'tombstone_origin_id': instance.tombstone_origin_id,
                'tombstoned_at': instance.tombstoned_at.isoformat() if instance.tombstoned_at else None,
            }
        return super().to_representation(instance)
