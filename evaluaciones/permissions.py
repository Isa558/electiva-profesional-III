from rest_framework.permissions import BasePermission

from .models import UserProfile


class HasRolePermission(BasePermission):
    message = 'Tu rol no tiene permiso para realizar esta acción.'

    def has_permission(self, request, view):
        required = getattr(view, 'required_permission', None)
        if not request.user or not request.user.is_authenticated or not required:
            return False
        if request.user.is_superuser:
            return True
        try:
            profile = request.user.profile
        except UserProfile.DoesNotExist:
            return False
        return profile.role.is_active and required in profile.role.permissions
