from django.http import HttpResponseForbidden

from .models import UserProfile


class ActiveRoleAdminMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/admin/') and request.user.is_authenticated and request.user.is_staff and not request.user.is_superuser:
            try:
                role_active = request.user.profile.role.is_active
            except UserProfile.DoesNotExist:
                role_active = False
            if not role_active:
                return HttpResponseForbidden('El rol de esta cuenta está desactivado.')
        return self.get_response(request)
