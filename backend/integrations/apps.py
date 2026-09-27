from django.apps import AppConfig
from django.db.models.signals import post_delete


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"
    verbose_name = "Cloud Integrations"

    def ready(self):
        from .models import AllyBrowser
        from .services.browser import delete_profile

        def _drop_profile(sender, instance, **kwargs):
            if instance.profile_id:
                delete_profile(instance.profile_id)

        post_delete.connect(_drop_profile, sender=AllyBrowser, weak=False)
