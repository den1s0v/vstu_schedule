from django.contrib import admin

from apps.panel.models import Scope, Occurrence, CorrectObject, Resolution


@admin.register(Scope)
class ScopeAdmin(admin.ModelAdmin):
    """Административный интерфейс для Scope."""
    
    list_display = ["id", "description", "updated_at"]
    list_filter = ["updated_at"]
    search_fields = ["description"]
    readonly_fields = ["updated_at"]
    
    fieldsets = (
        ("Основная информация", {
            "fields": ("description",)
        }),
        ("Системная информация", {
            "fields": ("updated_at",),
            "classes": ("collapse",)
        }),
    )


@admin.register(Occurrence)
class OccurrenceAdmin(admin.ModelAdmin):
    """Административный интерфейс для Occurrence."""
    
    list_display = ["id", "value", "scope", "resolved_to", "approved", "updated_at"]
    list_filter = ["scope", "approved", "manual", "updated_at"]
    search_fields = ["value"]
    readonly_fields = ["updated_at"]
    raw_id_fields = ["scope", "resolved_to"]
    
    fieldsets = (
        ("Основная информация", {
            "fields": ("value", "context", "scope")
        }),
        ("Разрешение", {
            "fields": ("resolved_to",)
        }),
        ("Метаданные", {
            "fields": ("score", "approved", "manual")
        }),
        ("Системная информация", {
            "fields": ("updated_at",),
            "classes": ("collapse",)
        }),
    )


@admin.register(CorrectObject)
class CorrectObjectAdmin(admin.ModelAdmin):
    """Административный интерфейс для CorrectObject."""
    
    list_display = ["id", "value", "external_id", "scope", "approved", "updated_at"]
    list_filter = ["scope", "approved", "manual", "updated_at"]
    search_fields = ["value", "external_id", "name", "description"]
    readonly_fields = ["updated_at"]
    raw_id_fields = ["scope"]
    
    fieldsets = (
        ("Основная информация", {
            "fields": ("value", "external_id", "name", "description", "scope")
        }),
        ("Контекст", {
            "fields": ("required_context_elements", "context")
        }),
        ("Метаданные", {
            "fields": ("score", "approved", "manual")
        }),
        ("Системная информация", {
            "fields": ("updated_at",),
            "classes": ("collapse",)
        }),
    )


@admin.register(Resolution)
class ResolutionAdmin(admin.ModelAdmin):
    """Административный интерфейс для Resolution."""
    
    list_display = ["id", "occurrence", "correct_object", "status", "score", "manual", "created_at"]
    list_filter = ["status", "scope", "manual", "created_at", "updated_at"]
    search_fields = ["occurrence__value", "correct_object__value"]
    readonly_fields = ["created_at", "updated_at"]
    raw_id_fields = ["occurrence", "correct_object", "scope"]
    
    fieldsets = (
        ("Основная информация", {
            "fields": ("occurrence", "correct_object", "scope")
        }),
        ("Статус и оценка", {
            "fields": ("status", "score", "manual")
        }),
        ("Системная информация", {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",)
        }),
    )
    
    def get_queryset(self, request):
        """Оптимизация запросов."""
        return super().get_queryset(request).select_related("occurrence", "correct_object", "scope")
