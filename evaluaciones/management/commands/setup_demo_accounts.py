from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from evaluaciones.demo_accounts import DEMO_ACCOUNTS, DEMO_PASSWORD, demo_accounts_are_ready
from evaluaciones.models import Role, UserProfile


class Command(BaseCommand):
    help = 'Crea las cuentas locales para demostrar los roles del simulador.'

    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.DEMO_ACCOUNTS_ENABLED:
            raise CommandError('Las cuentas de demostración solo se pueden preparar con DJANGO_DEBUG=true y ENABLE_DEMO_ACCOUNTS=true.')

        if demo_accounts_are_ready():
            self.stdout.write(self.style.SUCCESS('Las tres cuentas de demostración ya están preparadas.'))
            return

        user_model = get_user_model()
        administrative_permissions = {
            'users.manage', 'roles.manage', 'questions.manage', 'quizzes.manage',
            'results.view_all', 'settings.manage',
        }

        with transaction.atomic():
            users_to_create = []
            for account in DEMO_ACCOUNTS:
                role = Role.objects.filter(slug=account['role_slug'], is_active=True).first()
                if role is None:
                    raise CommandError(f'El rol activo "{account["role"]}" no existe. Ejecuta primero las migraciones.')

                matches = user_model.objects.filter(email__iexact=account['email'])
                if matches.count():
                    raise CommandError(
                        f'Ya existe una cuenta con el correo {account["email"]}, pero no coincide con la cuenta demo esperada. '
                        'No se modificó ninguna cuenta existente.'
                    )
                if user_model.objects.filter(username=account['email']).exists():
                    raise CommandError(
                        f'El nombre de usuario {account["email"]} ya está ocupado. '
                        'No se modificó ninguna cuenta existente.'
                    )
                users_to_create.append((account, role))

            for account, role in users_to_create:
                user = user_model.objects.create_user(
                    username=account['email'],
                    email=account['email'],
                    password=DEMO_PASSWORD,
                    first_name=account['first_name'],
                    is_staff=bool(administrative_permissions.intersection(role.permissions)),
                )
                UserProfile.objects.create(user=user, role=role)

        self.stdout.write(self.style.SUCCESS('Cuentas listas para la demostración:'))
        for account in DEMO_ACCOUNTS:
            self.stdout.write(f'  {account["role"]}: {account["email"]}')
        self.stdout.write('  Contraseña compartida: demostracion')
