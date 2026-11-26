from decimal import Decimal

from django.db import migrations


def import_legacy_question_bank(apps, schema_editor):
    connection = schema_editor.connection
    alias = connection.alias
    tables = set(connection.introspection.table_names())
    required_tables = {'categorias', 'preguntas', 'opciones_respuesta'}
    if not required_tables.issubset(tables):
        return

    Category = apps.get_model('evaluaciones', 'Category')
    Question = apps.get_model('evaluaciones', 'Question')
    AnswerOption = apps.get_model('evaluaciones', 'AnswerOption')
    quote = connection.ops.quote_name

    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT id, nombre, activo FROM {quote("categorias")}'
        )
        categories = {
            row[0]: Category.objects.using(alias).get_or_create(
                name=row[1],
                defaults={'is_active': bool(row[2])},
            )[0]
            for row in cursor.fetchall()
        }

        cursor.execute(
            f'SELECT id, categoria_id, tipo, texto_base, enunciado, '
            f'retroalimentacion, puntaje_defecto, activo FROM {quote("preguntas")}'
        )
        legacy_questions = cursor.fetchall()
        question_map = {}
        for row in legacy_questions:
            category = categories.get(row[1])
            if category is None:
                continue
            question_type = row[2] if row[2] in ('MULTIPLE', 'VERDADERO_FALSO') else 'MULTIPLE'
            question, _ = Question.objects.using(alias).get_or_create(
                category=category,
                stem=row[4],
                defaults={
                    'type': question_type,
                    'base_text': row[3] or '',
                    'feedback': row[5] or '',
                    'default_score': Decimal(str(row[6] or 1)),
                    'is_active': bool(row[7]),
                },
            )
            question_map[row[0]] = question

        cursor.execute(
            f'SELECT pregunta_id, letra, texto, es_correcta '
            f'FROM {quote("opciones_respuesta")}'
        )
        for question_id, letter, text, is_correct in cursor.fetchall():
            question = question_map.get(question_id)
            if question is None:
                continue
            AnswerOption.objects.using(alias).get_or_create(
                question=question,
                letter=letter,
                defaults={'text': text, 'is_correct': bool(is_correct)},
            )


class Migration(migrations.Migration):
    dependencies = [('evaluaciones', '0003_alter_question_default_score_alter_quiz_max_grade')]
    operations = [migrations.RunPython(import_legacy_question_bank, migrations.RunPython.noop)]
