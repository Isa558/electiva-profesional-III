from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from evaluaciones.demo_accounts import DEMO_ACCOUNTS, demo_accounts_are_ready
from evaluaciones.models import AnswerOption, Category, Question, Quiz


QUIZ_TITLE = 'Simulacro de demostración Saber TyT - Matemáticas y Español'
LEGACY_COMPETENCIES = (
    ('La Tierra gira alrededor del Sol.', 'Explicación de fenómenos'),
    ('¿Cuál es el planeta más cercano al Sol?', 'Uso comprensivo del conocimiento científico'),
)
QUESTION_DATA = (
    {
        'category': 'Matemáticas',
        'competency': 'Razonamiento cuantitativo',
        'stem': 'Una biblioteca recibió 240 libros y distribuyó tres octavas partes entre sus sedes. ¿Cuántos libros distribuyó?',
        'feedback': 'Tres octavas partes de 240 equivalen a 90 libros.',
        'correct': 'B',
        'options': [('A', '80 libros'), ('B', '90 libros'), ('C', '120 libros'), ('D', '150 libros')],
    },
    {
        'category': 'Matemáticas',
        'competency': 'Resolución de problemas',
        'stem': 'Un bus recorrió 180 kilómetros en 3 horas a velocidad constante. ¿Cuál fue su velocidad promedio?',
        'feedback': 'La velocidad promedio es distancia dividida entre tiempo: 180 / 3 = 60 km/h.',
        'correct': 'C',
        'options': [('A', '45 km/h'), ('B', '50 km/h'), ('C', '60 km/h'), ('D', '90 km/h')],
    },
    {
        'category': 'Matemáticas',
        'competency': 'Interpretación y representación',
        'stem': 'Un artículo cuesta $80.000 y tiene un descuento del 25 %. ¿Cuál es su precio con descuento?',
        'feedback': 'El descuento es $20.000; el precio final es $60.000.',
        'correct': 'A',
        'options': [('A', '$60.000'), ('B', '$65.000'), ('C', '$70.000'), ('D', '$75.000')],
    },
    {
        'category': 'Español',
        'competency': 'Lectura crítica',
        'base_text': 'En varios barrios, los huertos comunitarios aprovechan espacios sin uso para cultivar alimentos. Además de producir verduras, sus participantes comparten conocimientos y organizan jornadas de trabajo. Por ello, algunas alcaldías apoyan estos proyectos con herramientas y capacitación.',
        'stem': '¿Cuál es la idea principal del texto?',
        'feedback': 'El texto presenta los beneficios comunitarios de los huertos y el apoyo institucional que reciben.',
        'correct': 'D',
        'options': [('A', 'Los huertos reemplazan todos los comercios de alimentos.'), ('B', 'Las alcaldías deben administrar cada huerto.'), ('C', 'Cultivar verduras solo es posible en espacios rurales.'), ('D', 'Los huertos producen alimentos y fortalecen la colaboración comunitaria.')],
    },
    {
        'category': 'Español',
        'competency': 'Comprensión textual',
        'base_text': 'El museo anunció que su sala principal permanecerá cerrada durante dos semanas por trabajos de iluminación. La exposición temporal continuará abierta en el segundo piso y el ingreso será gratuito durante ese periodo.',
        'stem': 'Según el aviso, ¿qué podrán hacer los visitantes durante las reparaciones?',
        'feedback': 'El aviso indica que la exposición temporal seguirá abierta y que el ingreso será gratuito.',
        'correct': 'B',
        'options': [('A', 'Visitar la sala principal con horario limitado.'), ('B', 'Visitar gratis la exposición temporal en el segundo piso.'), ('C', 'Acceder a todas las salas del museo sin restricción.'), ('D', 'Ver la exposición temporal únicamente por internet.')],
    },
    {
        'category': 'Español',
        'competency': 'Interpretación de textos',
        'base_text': 'La bicicleta permite realizar trayectos cortos sin consumir combustible. Sin embargo, para que más personas la utilicen a diario, las ciudades necesitan rutas seguras, señalización y espacios para estacionarla.',
        'stem': '¿Qué condición señala el texto para promover el uso cotidiano de la bicicleta?',
        'feedback': 'El texto sostiene que la infraestructura segura y adecuada facilita el uso diario de la bicicleta.',
        'correct': 'A',
        'options': [('A', 'Contar con rutas seguras, señalización y estacionamientos.'), ('B', 'Eliminar el transporte público de la ciudad.'), ('C', 'Aumentar la distancia de todos los trayectos.'), ('D', 'Restringir el uso de bicicletas a los fines de semana.')],
    },
)


class Command(BaseCommand):
    help = 'Prepara preguntas y un cuestionario reutilizables para una demostración local.'

    def handle(self, *args, **options):
        if not settings.DEBUG or not settings.DEMO_ACCOUNTS_ENABLED:
            raise CommandError(
                'Los datos de demostración solo se pueden preparar con DJANGO_DEBUG=true '
                'y ENABLE_DEMO_ACCOUNTS=true.'
            )
        if not demo_accounts_are_ready():
            raise CommandError('Primero ejecuta python manage.py setup_demo_accounts.')

        user_model = get_user_model()
        admin_email = next(account['email'] for account in DEMO_ACCOUNTS if account['role_slug'] == 'administrador')
        admin = user_model.objects.get(email__iexact=admin_email)

        with transaction.atomic():
            completed_competencies = self._complete_legacy_competencies()
            questions = [self._get_or_create_question(data) for data in QUESTION_DATA]
            quiz = Quiz.objects.filter(title=QUIZ_TITLE).first()
            if quiz:
                if (
                    not quiz.is_active
                    or set(quiz.questions.values_list('id', flat=True)) != {question.id for question in questions}
                ):
                    raise CommandError(
                        f'Ya existe un cuestionario llamado "{QUIZ_TITLE}" con otra configuración. '
                        'No se modificó.'
                    )
                created = False
            else:
                now = timezone.now()
                quiz = Quiz.objects.create(
                    title=QUIZ_TITLE,
                    description='Práctica de demostración con preguntas de razonamiento cuantitativo y lectura.',
                    created_by=admin,
                    opens_at=now - timedelta(days=1),
                    closes_at=now + timedelta(days=365),
                    duration_minutes=30,
                    attempts_allowed=3,
                    max_grade=Decimal('5.00'),
                    passing_grade=Decimal('3.00'),
                    is_active=True,
                )
                quiz.questions.set(questions)
                created = True

        action = 'creado' if created else 'ya estaba preparado'
        self.stdout.write(self.style.SUCCESS(
            f'Cuestionario {action}: {quiz.title} ({len(questions)} preguntas, disponible hasta '
            f'{timezone.localtime(quiz.closes_at).strftime("%Y-%m-%d %H:%M")}).'
        ))
        self.stdout.write('Materias incluidas: Matemáticas y Español.')
        if completed_competencies:
            self.stdout.write(f'Competencias completadas en {completed_competencies} preguntas heredadas de Ciencias.')
        self.stdout.write('Inicia sesión como estudiante para realizar el intento y guardar una calificación real.')

    def _complete_legacy_competencies(self):
        updated = 0
        for stem, competency in LEGACY_COMPETENCIES:
            updated += Question.objects.filter(
                category__name__iexact='Ciencias',
                stem__iexact=stem,
                competency='',
            ).update(competency=competency)
        return updated

    def _get_or_create_question(self, data):
        category = Category.objects.filter(name__iexact=data['category']).first()
        if category is None:
            category = Category.objects.create(name=data['category'])
        elif not category.is_active:
            raise CommandError(f'La categoría "{category.name}" está inactiva; no se modificó.')

        question = Question.objects.filter(category=category, stem__iexact=data['stem']).first()
        if question:
            expected_options = [
                (letter, text, letter == data['correct'])
                for letter, text in data['options']
            ]
            stored_options = list(
                question.options.order_by('letter').values_list('letter', 'text', 'is_correct')
            )
            if (
                not question.is_active
                or question.competency != data['competency']
                or question.type != Question.Type.MULTIPLE
                or stored_options != expected_options
            ):
                raise CommandError(
                    f'La pregunta existente "{data["stem"]}" difiere de los datos de demostración. '
                    'No se modificó.'
                )
            return question

        question = Question.objects.create(
            category=category,
            competency=data['competency'],
            type=Question.Type.MULTIPLE,
            base_text=data.get('base_text', ''),
            stem=data['stem'],
            feedback=data['feedback'],
            default_score=Decimal('1.00'),
        )
        AnswerOption.objects.bulk_create([
            AnswerOption(
                question=question,
                letter=letter,
                text=text,
                is_correct=letter == data['correct'],
            )
            for letter, text in data['options']
        ])
        return question
