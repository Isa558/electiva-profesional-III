from django.db import migrations


def create_docente_role(apps, schema_editor):
    Role = apps.get_model('evaluaciones', 'Role')
    Role.objects.using(schema_editor.connection.alias).get_or_create(
        slug='docente',
        defaults={
            'name': 'Docente',
            'description': 'Gestiona preguntas, configura cuestionarios y consulta sus propios resultados.',
            'permissions': [
                'questions.manage',
                'quizzes.manage',
                'results.view_assigned',
            ],
            'is_active': True,
            'is_system': False,
        },
    )


class Migration(migrations.Migration):
    dependencies = [('evaluaciones', '0005_systemsettings_quiz_created_by_quiz_passing_grade_and_more')]
    operations = [migrations.RunPython(create_docente_role, migrations.RunPython.noop)]
