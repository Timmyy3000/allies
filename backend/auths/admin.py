from django.contrib import admin

from .models import Actor, AvatarAsset, ExternalIdentity, UserProfile


@admin.register(Actor)
class ActorAdmin(admin.ModelAdmin):
    list_display = ("public_id", "is_active", "is_staff", "date_joined")
    search_fields = ("public_id",)
    readonly_fields = ("public_id", "date_joined")


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("provider", "subject", "actor", "created_at")
    search_fields = ("provider", "subject", "actor__public_id")
    readonly_fields = ("provider", "subject", "actor", "created_at")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("actor", "display_name", "updated_at")
    search_fields = ("actor__public_id", "display_name")
    readonly_fields = ("actor", "current_avatar", "updated_at")

    def has_add_permission(self, request):
        return False


@admin.register(AvatarAsset)
class AvatarAssetAdmin(admin.ModelAdmin):
    list_display = ("public_id", "actor", "status", "created_at")
    search_fields = ("public_id", "actor__public_id")
    readonly_fields = ("public_id", "object_key", "created_at")
