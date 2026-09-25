from django.apps import AppConfig


class ModelKeysConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "model_keys"
    verbose_name = "Bring-your-own model keys"
