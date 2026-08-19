from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import AvatarAsset, ExternalIdentity, User, UserProfile


@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ("public_id", "is_active", "is_staff", "date_joined")
    search_fields = ("public_id",)
    readonly_fields = ("public_id", "date_joined")


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(ModelAdmin):
    list_display = ("provider", "subject", "user", "created_at")
    search_fields = ("provider", "subject", "user__public_id")
    readonly_fields = ("provider", "subject", "user", "created_at")


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ("user", "display_name", "updated_at")
    search_fields = ("user__public_id", "display_name")
    readonly_fields = ("user", "current_avatar", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(AvatarAsset)
class AvatarAssetAdmin(ModelAdmin):
    list_display = ("public_id", "user", "status", "created_at")
    search_fields = ("public_id", "user__public_id")
    readonly_fields = ("public_id", "object_key", "created_at")
