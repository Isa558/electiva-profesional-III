from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from evaluaciones.models import AnswerOption, Category, Question, Quiz


QUIZZES = (
    (
        'Simulacro Saber TyT - Matemáticas',
        'Matemáticas',
        (
            ('Razonamiento cuantitativo', 'Si 3 lápices cuestan $4.500, ¿cuánto cuestan 8 lápices?', 'La razón constante permite calcular 8 × 1.500 = $12.000.', 'C', [('A', '$10.500'), ('B', '$11.500'), ('C', '$12.000'), ('D', '$13.500')]),
            ('Resolución de problemas', 'Una tienda vendió 15 unidades a $20.000 y obtuvo un ingreso de $300.000. ¿Qué operación permite hallar el ingreso?', 'El ingreso se obtiene multiplicando unidades por precio unitario.', 'A', [('A', '15 × $20.000'), ('B', '15 + $20.000'), ('C', '$20.000 ÷ 15'), ('D', '$300.000 ÷ $20.000')]),
            ('Interpretación y representación', 'Una gráfica muestra que el 40 % de los estudiantes prefieren fútbol. Si hay 50 estudiantes, ¿cuántos prefieren fútbol?', 'El 40 % de 50 es 20.', 'B', [('A', '15'), ('B', '20'), ('C', '25'), ('D', '30')]),
            ('Razonamiento cuantitativo', 'El perímetro de un cuadrado es 36 cm. ¿Cuánto mide cada lado?', 'Cada lado mide 36 ÷ 4 = 9 cm.', 'D', [('A', '6 cm'), ('B', '8 cm'), ('C', '8.5 cm'), ('D', '9 cm')]),
        ),
    ),
    (
        'Simulacro Saber TyT - Español',
        'Español',
        (
            ('Comprensión textual', 'Un texto describe una ciudad que reduce residuos mediante reciclaje y educación ambiental. ¿Cuál es su propósito principal?', 'El propósito es explicar una estrategia ambiental comunitaria.', 'C', [('A', 'Criticar todas las ciudades.'), ('B', 'Promover únicamente el reciclaje privado.'), ('C', 'Mostrar cómo se reducen residuos con educación y reciclaje.'), ('D', 'Narrar la historia de una fábrica.')]),
            ('Lectura crítica', 'Si un artículo afirma que “todos los estudiantes aprenden igual”, ¿qué debilidad presenta?', 'La afirmación generaliza sin considerar ritmos y contextos diversos.', 'D', [('A', 'Es una conclusión muy específica.'), ('B', 'Incluye demasiados datos.'), ('C', 'Es una opinión difícil de comprender.'), ('D', 'Generaliza sin considerar diferencias individuales.')]),
            ('Interpretación de textos', '¿Cuál conector expresa contraste entre dos ideas?', '“Sin embargo” introduce una oposición o contraste.', 'B', [('A', 'Además'), ('B', 'Sin embargo'), ('C', 'Por eso'), ('D', 'Asimismo')]),
            ('Producción textual', '¿Cuál opción presenta una conclusión coherente?', 'Una conclusión debe sintetizar y responder al desarrollo del texto.', 'A', [('A', 'En conclusión, la educación ambiental puede mejorar las comunidades.'), ('B', 'Esto no tiene relación con el tema.'), ('C', 'Se mencionó una idea sin desarrollo.'), ('D', 'La pregunta todavía está pendiente.')]),
        ),
    ),
    (
        'Simulacro Saber TyT - Inglés',
        'Inglés',
        (
            ('Comprensión lectora', 'Choose the correct meaning: “The library is quiet in the morning.”', 'The sentence describes a quiet library in the morning.', 'B', [('A', 'The library closes every morning.'), ('B', 'The library is silent in the morning.'), ('C', 'The library sells books in the morning.'), ('D', 'The library is crowded at night.')]),
            ('Gramática', 'Complete: “She ___ three languages.”', '“Speaks” is the present-tense form for she.', 'C', [('A', 'speak'), ('B', 'speaking'), ('C', 'speaks'), ('D', 'spoke')]),
            ('Vocabulario', 'What is the opposite of “easy”?', 'The opposite of easy is difficult.', 'D', [('A', 'Simple'), ('B', 'Light'), ('C', 'Fast'), ('D', 'Difficult')]),
            ('Comprensión oral escrita', 'Choose the best answer: “Where can you usually borrow books?”', 'A library is the place where books can be borrowed.', 'A', [('A', 'At a library'), ('B', 'At a stadium'), ('C', 'At a bakery'), ('D', 'At a garage')]),
        ),
    ),
    (
        'Simulacro Saber TyT - Naturales',
        'Naturales',
        (
            ('Entorno vivo', '¿Qué proceso permite a las plantas producir alimento usando luz solar?', 'La fotosíntesis transforma agua y dióxido de carbono usando luz.', 'C', [('A', 'Digestión'), ('B', 'Respiración'), ('C', 'Fotosíntesis'), ('D', 'Evaporación')]),
            ('Cuidado ambiental', '¿Qué práctica reduce la contaminación de una fuente de agua?', 'Evitar vertimientos protege directamente el recurso hídrico.', 'D', [('A', 'Aumentar vertimientos'), ('B', 'Deforestar la rivera'), ('C', 'Usar más detergente'), ('D', 'Tratar las aguas residuales')]),
            ('Identidad de la materia', '¿Qué cambio representa una transformación física?', 'Fundirse cambia de estado, pero no la composición química.', 'B', [('A', 'Quemar madera'), ('B', 'Fundir hielo'), ('C', 'Oxidar hierro'), ('D', 'Cocinar un huevo')]),
            ('Entorno físico', '¿Qué fuerza mantiene a los objetos sobre la superficie terrestre?', 'La gravedad atrae los objetos hacia la Tierra.', 'A', [('A', 'Gravedad'), ('B', 'Magnetismo'), ('C', 'Fricción eléctrica'), ('D', 'Tensión')]),
        ),
    ),
    (
        'Simulacro Saber TyT - Ciencias',
        'Ciencias',
        (
            ('Uso comprensivo del conocimiento científico', '¿Cuál afirmación describe mejor el método científico?', 'El método científico combina observación, hipótesis, prueba y análisis.', 'D', [('A', 'Se basa solo en opiniones.'), ('B', 'No admite revisión.'), ('C', 'Evita la experimentación.'), ('D', 'Contrasta hipótesis mediante evidencia y experimentos.')]),
            ('Explicación de fenómenos', '¿Por qué podemos ver la Luna desde la Tierra?', 'La Luna refleja la luz solar.', 'B', [('A', 'La Luna produce toda su luz.'), ('B', 'La Luna refleja luz del Sol.'), ('C', 'La Tierra produce luz lunar.'), ('D', 'Las estrellas iluminan la Luna permanentemente.')]),
            ('Competencias de indagación', 'Antes de aceptar una conclusión científica se debe...', 'Las afirmaciones deben sustentarse con evidencia verificable.', 'C', [('A', 'Ignorar resultados contrarios.'), ('B', 'Aceptar la opinión más popular.'), ('C', 'Analizar la evidencia y su método.'), ('D', 'Cambiar los datos sin explicación.')]),
            ('Aplicación del conocimiento', '¿Qué medida protege mejor los ecosistemas?', 'La conservación combina protección de hábitats y uso responsable.', 'A', [('A', 'Conservar hábitats y regular el uso de recursos.'), ('B', 'Eliminar todas las especies de un área.'), ('C', 'Introducir especies sin estudio.'), ('D', 'Aumentar residuos en zonas naturales.')]),
        ),
    ),
)


class Command(BaseCommand):
    help = 'Crea varios cuestionarios por materia para la sustentación.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Este comando solo debe ejecutarse en modo demostración local.')

        user = get_user_model().objects.filter(
            profile__role__slug='administrador',
            is_active=True,
        ).first()
        if user is None:
            raise CommandError('Crea primero una cuenta administradora.')

        created_questions = 0
        created_quizzes = 0

        with transaction.atomic():
            for title, category_name, questions_data in QUIZZES:
                category = Category.objects.filter(name__iexact=category_name).first()
                if category is None:
                    category = Category.objects.create(name=category_name)

                questions = []
                for competency, stem, feedback, correct, options in questions_data:
                    question = Question.objects.filter(category=category, stem=stem).first()
                    if question is None:
                        question = Question.objects.create(
                            category=category,
                            competency=competency,
                            stem=stem,
                            feedback=feedback,
                            default_score=Decimal('1.00'),
                        )
                        AnswerOption.objects.bulk_create([
                            AnswerOption(
                                question=question,
                                letter=letter,
                                text=text,
                                is_correct=letter == correct,
                            )
                            for letter, text in options
                        ])
                        created_questions += 1
                    questions.append(question)

                quiz = Quiz.objects.filter(title=title).first()
                if quiz is None:
                    now = timezone.now()
                    quiz = Quiz.objects.create(
                        title=title,
                        description=f'Simulacro de demostración de {category_name}.',
                        created_by=user,
                        opens_at=now - timedelta(days=1),
                        closes_at=now + timedelta(days=365),
                        duration_minutes=30,
                        attempts_allowed=3,
                        max_grade=Decimal('5.00'),
                        passing_grade=Decimal('3.00'),
                        is_active=True,
                    )
                    quiz.questions.set(questions)
                    created_quizzes += 1

        self.stdout.write(self.style.SUCCESS(
            f'Preparado: {created_quizzes} nuevos cuestionarios y {created_questions} nuevas preguntas.'
        ))
