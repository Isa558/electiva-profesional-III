from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


ROLE_PERMISSIONS = [
    ('users.manage', 'Administrar usuarios'),
    ('roles.manage', 'Administrar roles y permisos'),
    ('questions.manage', 'Gestionar e importar preguntas'),
    ('quizzes.manage', 'Configurar cuestionarios'),
    ('results.view_all', 'Consultar todos los resultados'),
    ('results.view_assigned', 'Consultar resultados de cuestionarios asignados'),
    ('settings.manage', 'Configurar el sistema'),
    ('quizzes.take', 'Responder cuestionarios'),
    ('results.view_own', 'Consultar resultados propios'),
]


class Role(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_system = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='users')
    institutional_code = models.CharField(max_length=40, blank=True, unique=True, null=True)

    def __str__(self):
        return f'{self.user.username} - {self.role.name}'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    competency = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Question(models.Model):
    class Type(models.TextChoices):
        MULTIPLE = 'MULTIPLE', 'Selección múltiple'
        TRUE_FALSE = 'VERDADERO_FALSO', 'Verdadero / Falso'

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='questions')
    competency = models.CharField(max_length=120, blank=True)
    type = models.CharField(max_length=24, choices=Type.choices, default=Type.MULTIPLE)
    base_text = models.TextField(blank=True)
    stem = models.TextField()
    feedback = models.TextField(blank=True)
    default_score = models.DecimalField(max_digits=5, decimal_places=2, default=1, validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('999.99'))])
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.stem[:90]


class AnswerOption(models.Model):
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='options')
    letter = models.CharField(max_length=1)
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ['letter']
        constraints = [
            models.UniqueConstraint(fields=['question', 'letter'], name='unique_question_option_letter'),
        ]

    def __str__(self):
        return f'{self.letter}. {self.text}'


class Quiz(models.Model):
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_quizzes', null=True, blank=True)
    questions = models.ManyToManyField(Question, through='QuizQuestion', related_name='quizzes')
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    attempts_allowed = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    max_grade = models.DecimalField(max_digits=5, decimal_places=2, default=5, validators=[MinValueValidator(Decimal('0.01')), MaxValueValidator(Decimal('100'))])
    passing_grade = models.DecimalField(max_digits=5, decimal_places=2, default=3, validators=[MinValueValidator(Decimal('0')), MaxValueValidator(Decimal('100'))])
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title

    def is_available(self, at=None):
        from django.utils import timezone

        at = at or timezone.now()
        return self.is_active and self.opens_at <= at <= self.closes_at


class QuizQuestion(models.Model):
    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name='quiz_questions')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='quiz_questions')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['quiz', 'question'], name='unique_quiz_question'),
        ]


class Attempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = 'IN_PROGRESS', 'En progreso'
        COMPLETED = 'COMPLETED', 'Finalizado'

    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name='attempts')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='quiz_attempts')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    grade = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['-started_at', '-id']

    def __str__(self):
        return f'{self.user.username} - {self.quiz.title} ({self.status})'


class AttemptAnswer(models.Model):
    attempt = models.ForeignKey(Attempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='attempt_answers')
    selected_option = models.ForeignKey(AnswerOption, on_delete=models.PROTECT, related_name='attempt_answers', null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['attempt', 'question'], name='unique_attempt_question'),
        ]


class ImportRecord(models.Model):
    file_name = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='question_imports')
    destination_quiz = models.ForeignKey(Quiz, on_delete=models.SET_NULL, related_name='imports', null=True, blank=True)
    total_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    error_rows = models.PositiveIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class SystemSettings(models.Model):
    system_name = models.CharField(max_length=120, default='Simulador Saber TyT')
    institution_name = models.CharField(max_length=160, default='Institución Universitaria del Putumayo')
    support_email = models.EmailField(default='soporte@sabertyt.edu.co')
    time_zone = models.CharField(max_length=50, default='America/Bogota')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.system_name
