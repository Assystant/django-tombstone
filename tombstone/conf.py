from django.conf import settings
from django.test.signals import setting_changed

DEFAULTS = {
    'DEFAULT_REF_BEHAVIOR': 'keep',  # FK stays valid naturally — no action needed
}


class TombstoneSettings:
    """
    Reads from Django's TOMBSTONE setting dict, falling back to DEFAULTS.

    Example settings.py:
        TOMBSTONE = {
            'DEFAULT_REF_BEHAVIOR': 'keep',   # 'keep' | 'delete'
        }
    """

    def __init__(self, defaults=None):
        self._defaults = defaults or DEFAULTS
        self._cache = {}

    def __getattr__(self, attr):
        if attr not in self._defaults:
            raise AttributeError(f"Invalid tombstone setting: '{attr}'")
        if attr not in self._cache:
            user_settings = getattr(settings, 'TOMBSTONE', {})
            self._cache[attr] = user_settings.get(attr, self._defaults[attr])
        return self._cache[attr]

    def reload(self):
        self._cache.clear()


tombstone_settings = TombstoneSettings()


def _reload_on_change(*, setting, **kwargs):
    if setting == 'TOMBSTONE':
        tombstone_settings.reload()


setting_changed.connect(_reload_on_change)
