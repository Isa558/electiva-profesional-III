from django.contrib.auth import get_user_model

from .models import UserProfile

DEMO_PASSWORD = 'demostracion'
DEMO_ACCOUNTS = (
    {'email': 'admin@sabertyt.edu.co', 'role': 'Administrador', 'role_slug': 'administrador', 'first_name': 'Admin'},
    {'email': 'docente@sabertyt.edu.co', 'role': 'Docente', 'role_slug': 'docente', 'first_name': 'Docente'},
    {'email': 'estudiante@sabertyt.edu.co', 'role': 'Estudiante', 'role_slug': 'estudiante', 'first_name': 'Estudiante'},
)


def demo_accounts_are_ready():
    user_model = get_user_model()
    for account in DEMO_ACCOUNTS:
        matches = user_model.objects.filter(email__iexact=account['email'])
        if matches.count() != 1:
            return False
        user = matches.select_related('profile__role').first()
        try:
            role = user.profile.role
        except UserProfile.DoesNotExist:
            return False
        if (
            not user.is_active
            or not role.is_active
            or role.slug != account['role_slug']
            or not user.check_password(DEMO_PASSWORD)
        ):
            return False
    return True
