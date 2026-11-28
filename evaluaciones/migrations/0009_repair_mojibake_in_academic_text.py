from django.db import migrations


def _build_replacements():
    replacements = {}
    for codepoint in range(0x80, 0x100):
        character = chr(codepoint)
        replacements[character.encode('utf-8').decode('latin-1')] = character
    return sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True)


MOJIBAKE_REPLACEMENTS = _build_replacements()


def repair_text(value):
    while True:
        repaired = value
        for damaged, corrected in MOJIBAKE_REPLACEMENTS:
            repaired = repaired.replace(damaged, corrected)
        if repaired == value:
            return value
        value = repaired


def repair_model_text(apps, model_name, fields, database_alias):
    model = apps.get_model('evaluaciones', model_name)
    queryset = model.objects.using(database_alias)
    for record in queryset.values('pk', *fields).iterator(chunk_size=500):
        updates = {
            field: repaired
            for field in fields
            if (repaired := repair_text(record[field])) != record[field]
        }
        if updates:
            queryset.filter(pk=record['pk']).update(**updates)


def repair_question_data(apps, schema_editor):
    database_alias = schema_editor.connection.alias
    repair_model_text(apps, 'Category', ('name', 'competency'), database_alias)
    repair_model_text(
        apps,
        'Question',
        ('competency', 'base_text', 'stem', 'feedback'),
        database_alias,
    )
    repair_model_text(apps, 'AnswerOption', ('text',), database_alias)
    repair_model_text(apps, 'Quiz', ('title', 'description'), database_alias)


class Migration(migrations.Migration):

    dependencies = [
        ('evaluaciones', '0008_enforce_five_point_grade_scale'),
    ]

    operations = [
        migrations.RunPython(repair_question_data, migrations.RunPython.noop),
    ]
