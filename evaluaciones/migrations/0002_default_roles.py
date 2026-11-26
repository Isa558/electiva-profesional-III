from django.db import migrations


ADMIN_PERMISSIONS = [
    'users.manage',
    'roles.manage',
    'questions.manage',
    'quizzes.manage',
    'results.view_all',
    'quizzes.take',
    'results.view_own',
]


def create_default_roles(apps, schema_editor):
    Role = apps.get_model('evaluaciones', 'Role')
    Role.objects.using(schema_editor.connection.alias).get_or_create(
        slug='administrador',
        defaults={
            'name': 'Administrador',
            'description': 'Administra usuarios, roles, preguntas, cuestionarios y resultados.',
            'permissions': ADMIN_PERMISSIONS,
            'is_active': True,
            'is_system': True,
        },
    )
    Role.objects.using(schema_editor.connection.alias).get_or_create(
        slug='estudiante',
        defaults={
            'name': 'Estudiante',
            'description': 'Responde cuestionarios y consulta sus propias calificaciones.',
            'permissions': ['quizzes.take', 'results.view_own'],
            'is_active': True,
            'is_system': True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [('evaluaciones', '0001_initial')]
    operations = [migrations.RunPython(create_default_roles, migrations.RunPython.noop)]
