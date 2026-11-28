from datetime import timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zipfile import BadZipFile

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.db import DatabaseError, connection
from django.db.models import Avg, Count, Max, Min, Q, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet.datavalidation import DataValidation
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, OpenApiTypes, extend_schema, inline_serializer
from rest_framework import serializers

from .models import AnswerOption, Attempt, AttemptAnswer, Category, ImportRecord, Question, Quiz, Role, ROLE_PERMISSIONS, SystemSettings, UserProfile
from .demo_accounts import DEMO_ACCOUNTS, DEMO_PASSWORD, demo_accounts_are_ready
from .permissions import HasRolePermission
from .serializers import (
    AttemptAnswerSerializer,
    AttemptSerializer,
    AvailableQuizSerializer,
    CategorySerializer,
    CurrentUserSerializer,
    EmailOrUsernameTokenSerializer,
    ImportRecordSerializer,
    QuestionSerializer,
    QuizSerializer,
    RoleSerializer,
    SystemSettingsSerializer,
    UserSerializer,
)
from rest_framework_simplejwt.views import TokenObtainPairView

User = get_user_model()
REQUIRED_HEADERS = [
    'categoria', 'competencia', 'tipo', 'texto_base', 'enunciado',
    'retroalimentacion', 'puntaje_defecto', 'opcion_a', 'opcion_b',
    'opcion_c', 'opcion_d', 'correcta',
]
IMPORT_HEADERS = REQUIRED_HEADERS


def application_home(request):
    return render(request, 'evaluaciones/index.html')


class DatabaseHealthView(APIView):
    serializer_class = serializers.Serializer
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except DatabaseError:
            return Response(
                {'connected': False, 'message': 'No se pudo conectar con la base de datos.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({'connected': True, 'engine': connection.vendor})


class EmailOrUsernameTokenView(TokenObtainPairView):
    serializer_class = EmailOrUsernameTokenSerializer


class LoginRoleOptionsView(APIView):
    serializer_class = serializers.Serializer
    permission_classes = [AllowAny]

    def get(self, request):
        roles = Role.objects.filter(is_active=True).values('name', 'slug').order_by('name')
        return Response(list(roles))


class DemoAccountsView(APIView):
    serializer_class = serializers.Serializer
    permission_classes = [AllowAny]

    def get(self, request):
        if not settings.DEBUG or not settings.DEMO_ACCOUNTS_ENABLED or not demo_accounts_are_ready():
            return Response({'enabled': False})
        return Response({
            'enabled': True,
            'accounts': [
                {'email': account['email'], 'role': account['role'], 'role_slug': account['role_slug']}
                for account in DEMO_ACCOUNTS
            ],
            'password': DEMO_PASSWORD,
        })


class LogoutView(APIView):
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'Se requiere el token de renovación.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return Response({'detail': 'El token de renovación no es válido.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_205_RESET_CONTENT)


class CurrentUserView(APIView):
    serializer_class = CurrentUserSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.is_superuser:
            try:
                if not request.user.profile.role.is_active:
                    return Response({'detail': 'El rol de esta cuenta está desactivado.'}, status=status.HTTP_403_FORBIDDEN)
            except UserProfile.DoesNotExist:
                return Response({'detail': 'La cuenta no tiene un rol asignado.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(CurrentUserSerializer(request.user).data)

    def patch(self, request):
        serializer = CurrentUserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ChangePasswordView(APIView):
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    def post(self, request):
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')
        if not isinstance(current_password, str) or not request.user.check_password(current_password):
            return Response({'current_password': ['La contraseña actual no es correcta.']}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(new_password, str):
            return Response({'new_password': ['La nueva contraseña es obligatoria.']}, status=status.HTTP_400_BAD_REQUEST)
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            validate_password(new_password, request.user)
        except ValidationError as error:
            return Response({'new_password': list(error.messages)}, status=status.HTTP_400_BAD_REQUEST)
        request.user.set_password(new_password)
        request.user.save(update_fields=['password'])
        return Response({'detail': 'La contraseña se actualizó correctamente.'})


class SystemSettingsView(APIView):
    serializer_class = SystemSettingsSerializer
    required_permission = 'settings.manage'
    permission_classes = [HasRolePermission]

    def get(self, request):
        settings, _ = SystemSettings.objects.get_or_create(pk=1)
        return Response(SystemSettingsSerializer(settings).data)

    def patch(self, request):
        settings, _ = SystemSettings.objects.get_or_create(pk=1)
        serializer = SystemSettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class RoleListCreateView(APIView):
    serializer_class = RoleSerializer
    required_permission = 'roles.manage'
    permission_classes = [HasRolePermission]

    def get(self, request):
        return Response(RoleSerializer(Role.objects.all(), many=True).data)

    def post(self, request):
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RolePermissionCatalogView(APIView):
    serializer_class = serializers.Serializer
    required_permission = 'roles.manage'
    permission_classes = [HasRolePermission]

    def get(self, request):
        return Response([{'code': code, 'label': label} for code, label in ROLE_PERMISSIONS])


class RoleDetailView(APIView):
    serializer_class = RoleSerializer
    required_permission = 'roles.manage'
    permission_classes = [HasRolePermission]

    def get_object(self, pk):
        return get_object_or_404(Role, pk=pk)

    def get(self, request, pk):
        return Response(RoleSerializer(self.get_object(pk)).data)

    def put(self, request, pk):
        role = self.get_object(pk)
        serializer = RoleSerializer(role, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def patch(self, request, pk):
        role = self.get_object(pk)
        serializer = RoleSerializer(role, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        role = self.get_object(pk)
        if role.is_system:
            return Response({'detail': 'Los roles predeterminados no se pueden eliminar; puedes desactivarlos.'}, status=status.HTTP_400_BAD_REQUEST)
        if role.users.exists():
            return Response({'detail': 'Reasigna los usuarios de este rol antes de eliminarlo.'}, status=status.HTTP_400_BAD_REQUEST)
        role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListCreateView(APIView):
    serializer_class = UserSerializer
    required_permission = 'users.manage'
    permission_classes = [HasRolePermission]

    def get(self, request):
        users = User.objects.select_related('profile__role').all().order_by('username')
        return Response(UserSerializer(users, many=True).data)

    def post(self, request):
        serializer = UserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(UserSerializer(serializer.save()).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    serializer_class = UserSerializer
    required_permission = 'users.manage'
    permission_classes = [HasRolePermission]

    def get_object(self, pk):
        return get_object_or_404(User.objects.select_related('profile__role'), pk=pk)

    def get(self, request, pk):
        return Response(UserSerializer(self.get_object(pk)).data)

    def put(self, request, pk):
        serializer = UserSerializer(self.get_object(pk), data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(UserSerializer(serializer.save()).data)

    def patch(self, request, pk):
        serializer = UserSerializer(self.get_object(pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(UserSerializer(serializer.save()).data)

    def delete(self, request, pk):
        user = self.get_object(pk)
        if user.is_superuser or user.quiz_attempts.exists() or user.created_quizzes.exists() or user.question_imports.exists():
            return Response({'detail': 'No se puede eliminar esta cuenta porque conserva historial asociado; desactívala para mantener los registros.'}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [HasRolePermission]
    required_permission = 'questions.manage'
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']


class QuestionViewSet(viewsets.ModelViewSet):
    queryset = Question.objects.select_related('category').prefetch_related('options')
    serializer_class = QuestionSerializer
    permission_classes = [HasRolePermission]
    required_permission = 'questions.manage'

    def perform_destroy(self, instance):
        if instance.quiz_questions.exists() or instance.attempt_answers.exists():
            from rest_framework.exceptions import ValidationError

            raise ValidationError('No se puede eliminar una pregunta utilizada; desactívala para conservar el historial.')
        instance.delete()


class QuizViewSet(viewsets.ModelViewSet):
    queryset = Quiz.objects.select_related('created_by').prefetch_related('questions')
    serializer_class = QuizSerializer
    permission_classes = [HasRolePermission]
    required_permission = 'quizzes.manage'
    http_method_names = ['get', 'post', 'put', 'patch', 'head', 'options']

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.is_superuser:
            return queryset
        try:
            permissions = self.request.user.profile.role.permissions
        except UserProfile.DoesNotExist:
            return queryset.none()
        if 'results.view_all' not in permissions:
            return queryset.filter(created_by=self.request.user)
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class QuizAvailableView(APIView):
    serializer_class = AvailableQuizSerializer
    required_permission = 'quizzes.take'
    permission_classes = [HasRolePermission]

    @extend_schema(responses={200: AvailableQuizSerializer(many=True)})
    def get(self, request):
        now = timezone.now()
        quizzes = Quiz.objects.filter(is_active=True, opens_at__lte=now, closes_at__gte=now).annotate(
            available_questions=Count('questions', filter=Q(questions__is_active=True), distinct=True),
        ).filter(available_questions__gt=0).prefetch_related('questions')
        quizzes = [quiz for quiz in quizzes if Attempt.objects.filter(quiz=quiz, user=request.user).count() < quiz.attempts_allowed]
        return Response(AvailableQuizSerializer(quizzes, many=True, context={'request': request}).data)


class AttemptStartView(APIView):
    serializer_class = AttemptSerializer
    required_permission = 'quizzes.take'
    permission_classes = [HasRolePermission]

    @extend_schema(responses={201: AttemptSerializer})
    @transaction.atomic
    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz.objects.select_for_update().prefetch_related('questions'), pk=quiz_id)
        if not quiz.is_available():
            return Response({'detail': 'El cuestionario no está habilitado o está fuera de su disponibilidad.'}, status=status.HTTP_400_BAD_REQUEST)
        if not quiz.questions.filter(is_active=True).exists():
            return Response({'detail': 'El cuestionario no tiene preguntas activas.'}, status=status.HTTP_400_BAD_REQUEST)
        if Attempt.objects.filter(quiz=quiz, user=request.user).count() >= quiz.attempts_allowed:
            return Response({'detail': 'Ya alcanzaste el número máximo de intentos.'}, status=status.HTTP_400_BAD_REQUEST)
        attempt = Attempt.objects.create(quiz=quiz, user=request.user)
        return Response(AttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)


class AttemptCreateView(APIView):
    serializer_class = AttemptSerializer
    required_permission = 'quizzes.take'
    permission_classes = [HasRolePermission]

    @extend_schema(
        request=inline_serializer(
            name='CreateAttemptRequest',
            fields={'quiz_id': serializers.IntegerField(min_value=1)},
        ),
        responses={201: AttemptSerializer},
    )
    @transaction.atomic
    def post(self, request):
        quiz_id = request.data.get('quiz_id')
        if not isinstance(quiz_id, int):
            try:
                quiz_id = int(quiz_id)
            except (TypeError, ValueError):
                return Response({'quiz_id': 'Debe indicar un identificador válido.'}, status=status.HTTP_400_BAD_REQUEST)
        quiz = get_object_or_404(Quiz.objects.select_for_update().prefetch_related('questions'), pk=quiz_id)
        if not quiz.is_available():
            return Response({'detail': 'El cuestionario no está habilitado o está fuera de su disponibilidad.'}, status=status.HTTP_400_BAD_REQUEST)
        if not quiz.questions.filter(is_active=True).exists():
            return Response({'detail': 'El cuestionario no tiene preguntas activas.'}, status=status.HTTP_400_BAD_REQUEST)
        if Attempt.objects.filter(quiz=quiz, user=request.user).count() >= quiz.attempts_allowed:
            return Response({'detail': 'Ya alcanzaste el número máximo de intentos.'}, status=status.HTTP_400_BAD_REQUEST)
        attempt = Attempt.objects.create(quiz=quiz, user=request.user)
        return Response(AttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)


class AttemptListView(APIView):
    serializer_class = AttemptSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: AttemptSerializer(many=True)})
    def get(self, request):
        if request.user.is_superuser:
            attempts = Attempt.objects.select_related('quiz', 'user').all()
        else:
            try:
                role = request.user.profile.role
            except UserProfile.DoesNotExist:
                return Response({'detail': 'La cuenta no tiene un rol asignado.'}, status=status.HTTP_403_FORBIDDEN)
            if not role.is_active:
                return Response({'detail': 'El rol de esta cuenta está desactivado.'}, status=status.HTTP_403_FORBIDDEN)
            if 'results.view_all' in role.permissions:
                attempts = Attempt.objects.select_related('quiz', 'user').all()
            elif 'results.view_assigned' in role.permissions:
                attempts = Attempt.objects.select_related('quiz', 'user').filter(quiz__created_by=request.user)
            elif 'results.view_own' in role.permissions:
                attempts = Attempt.objects.select_related('quiz', 'user').filter(user=request.user)
            else:
                return Response({'detail': 'Tu rol no puede consultar resultados.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(AttemptSerializer(attempts, many=True).data)


def _report_attempts_for_user(user):
    attempts = Attempt.objects.select_related('quiz', 'user', 'user__profile').prefetch_related('answers')
    if user.is_superuser:
        return attempts, None
    try:
        role = user.profile.role
    except UserProfile.DoesNotExist:
        return None, Response({'detail': 'La cuenta no tiene un rol asignado.'}, status=status.HTTP_403_FORBIDDEN)
    if not role.is_active:
        return None, Response({'detail': 'El rol de esta cuenta está desactivado.'}, status=status.HTTP_403_FORBIDDEN)
    if 'results.view_all' in role.permissions:
        return attempts, None
    if 'results.view_assigned' in role.permissions:
        return attempts.filter(quiz__created_by=user), None
    if 'results.view_own' in role.permissions:
        return attempts.filter(user=user), None
    return None, Response({'detail': 'Tu rol no puede consultar resultados.'}, status=status.HTTP_403_FORBIDDEN)


def _filtered_report_attempts(attempts, params):
    filters = {
        'year': params.get('year') or '',
        'period': params.get('period') or '',
        'course': params.get('group') or params.get('course') or '',
        'axis': params.get('axis') or '',
        'student': params.get('student') or '',
    }
    if filters['year']:
        try:
            filters['year'] = int(filters['year'])
        except (TypeError, ValueError):
            return None, filters, Response({'year': 'Debe ser un año válido.'}, status=status.HTTP_400_BAD_REQUEST)
        if not 2000 <= filters['year'] <= 2100:
            return None, filters, Response({'year': 'El año debe estar entre 2000 y 2100.'}, status=status.HTTP_400_BAD_REQUEST)
        attempts = attempts.filter(started_at__year=filters['year'])
    if filters['period']:
        attempts = attempts.filter(quiz__academic_period=filters['period'])
    if filters['course']:
        if params.get('group'):
            attempts = attempts.filter(quiz__course_group=filters['course'])
        else:
            attempts = attempts.filter(
                Q(quiz__course_group__icontains=filters['course'])
                | Q(quiz__title__icontains=filters['course'])
                | Q(user__profile__institutional_code__icontains=filters['course'])
            )
    if filters['axis']:
        quizzes_with_axis = Quiz.objects.filter(
            Q(questions__competency__icontains=filters['axis'])
            | Q(questions__category__name__icontains=filters['axis'])
            | Q(questions__category__competency__icontains=filters['axis'])
        )
        attempts = attempts.filter(quiz_id__in=Subquery(quizzes_with_axis.values('pk')))
    if filters['student']:
        attempts = attempts.filter(
            Q(user__username__icontains=filters['student'])
            | Q(user__first_name__icontains=filters['student'])
            | Q(user__last_name__icontains=filters['student'])
            | Q(user__profile__institutional_code__icontains=filters['student'])
        )
    return attempts.distinct(), filters, None


def _report_facets(attempts, filters):
    years = list(attempts.values_list('started_at__year', flat=True).distinct().order_by('started_at__year'))
    period_scope = attempts.filter(started_at__year=filters['year']) if filters['year'] else attempts
    periods = list(period_scope.exclude(quiz__academic_period='').order_by('quiz__academic_period').values_list('quiz__academic_period', flat=True).distinct())
    group_scope = period_scope.filter(quiz__academic_period=filters['period']) if filters['period'] else period_scope
    groups = list(group_scope.exclude(quiz__course_group='').order_by('quiz__course_group').values_list('quiz__course_group', flat=True).distinct())
    selected_group_scope = group_scope.filter(quiz__course_group=filters['course']) if filters['course'] else group_scope
    axis_rows = selected_group_scope.values_list(
        'quiz__questions__competency', 'quiz__questions__category__competency', 'quiz__questions__category__name',
    ).distinct()
    axes = sorted({
        competency or category_competency or category_name
        for competency, category_competency, category_name in axis_rows
        if competency or category_competency or category_name
    }, key=str.casefold)
    student_scope = selected_group_scope
    if filters['axis']:
        axis_quizzes = Quiz.objects.filter(
            Q(questions__competency__icontains=filters['axis'])
            | Q(questions__category__name__icontains=filters['axis'])
            | Q(questions__category__competency__icontains=filters['axis'])
        ).values('pk')
        student_scope = student_scope.filter(quiz_id__in=Subquery(axis_quizzes))
    student_rows = student_scope.order_by('user__last_name', 'user__first_name', 'user__username').values(
        'user__username', 'user__first_name', 'user__last_name', 'user__profile__institutional_code',
    ).distinct()
    students = [{
        'username': row['user__username'],
        'name': ' '.join(filter(None, [row['user__first_name'], row['user__last_name']])) or row['user__username'],
        'code': row['user__profile__institutional_code'] or '',
    } for row in student_rows]
    return {'years': years, 'periods': periods, 'courses': groups, 'axes': axes, 'students': students}


def _report_aggregates(attempts, axis_filter=''):
    completed = attempts.filter(status=Attempt.Status.COMPLETED, grade__isnull=False)
    summary = completed.aggregate(average=Avg('grade'), minimum=Min('grade'), maximum=Max('grade'))
    rows = list(completed.values('grade', 'quiz__passing_grade', 'user_id'))
    passed = sum(1 for row in rows if row['grade'] >= row['quiz__passing_grade'])
    period_rows = list(completed.values('started_at__year', 'quiz__academic_period').annotate(
        attempts=Count('id', distinct=True),
        students=Count('user_id', distinct=True),
        average=Avg('grade'),
        minimum=Min('grade'),
        maximum=Max('grade'),
    ).order_by('started_at__year', 'quiz__academic_period'))
    course_rows = list(completed.values(
        'quiz__course_group', 'started_at__year', 'quiz__academic_period',
    ).annotate(
        attempts=Count('id', distinct=True),
        students=Count('user_id', distinct=True),
        average=Avg('grade'),
        minimum=Min('grade'),
        maximum=Max('grade'),
    ).order_by('quiz__course_group', 'started_at__year', 'quiz__academic_period'))
    student_rows = list(completed.values(
        'user_id', 'user__username', 'user__first_name', 'user__last_name',
    ).annotate(
        attempts=Count('id', distinct=True),
        average=Avg('grade'),
        minimum=Min('grade'),
        maximum=Max('grade'),
    ).order_by('user__last_name', 'user__first_name', 'user__username'))
    answers = AttemptAnswer.objects.filter(
        attempt__in=completed,
        selected_option__isnull=False,
    )
    if axis_filter:
        answers = answers.filter(
            Q(question__competency__icontains=axis_filter)
            | Q(question__category__name__icontains=axis_filter)
            | Q(question__category__competency__icontains=axis_filter)
        )
    axis_rows = answers.values('question__competency', 'question__category__competency', 'question__category__name').annotate(
        total=Count('id'),
        correct=Count('id', filter=Q(selected_option__is_correct=True)),
    ).order_by('question__category__name', 'question__competency')
    axes = []
    for row in axis_rows:
        label = row['question__competency'] or row['question__category__competency'] or row['question__category__name']
        axes.append({
            'axis': label,
            'responses': row['total'],
            'correct': row['correct'],
            'incorrect': row['total'] - row['correct'],
            'accuracy_percent': round(row['correct'] * 100 / row['total'], 2) if row['total'] else 0,
        })
    question_rows = answers.values('question_id', 'question__stem', 'question__competency', 'question__category__name').annotate(
        total=Count('id'),
        correct=Count('id', filter=Q(selected_option__is_correct=True)),
    ).order_by('question__competency', 'question__category__name', 'question_id')
    difficulty = [{
        'question_id': row['question_id'],
        'question': row['question__stem'],
        'axis': row['question__competency'] or row['question__category__name'],
        'responses': row['total'],
        'correct': row['correct'],
        'incorrect': row['total'] - row['correct'],
        'accuracy_percent': round(row['correct'] * 100 / row['total'], 2) if row['total'] else 0,
    } for row in question_rows]
    difficulty.sort(key=lambda row: (row['accuracy_percent'], -row['responses'], row['question_id']))
    return {
        'students_evaluated': len({row['user_id'] for row in rows}),
        'completed_attempts': len(rows),
        'average_grade': round(float(summary['average']), 2) if summary['average'] is not None else None,
        'minimum_grade': float(summary['minimum']) if summary['minimum'] is not None else None,
        'maximum_grade': float(summary['maximum']) if summary['maximum'] is not None else None,
        'passed': passed,
        'failed': len(rows) - passed,
        'by_period': [{
            'year': row['started_at__year'],
            'period': row['quiz__academic_period'],
            'attempts': row['attempts'],
            'students': row['students'],
            'average': round(float(row['average']), 2) if row['average'] is not None else None,
            'minimum': float(row['minimum']) if row['minimum'] is not None else None,
            'maximum': float(row['maximum']) if row['maximum'] is not None else None,
        } for row in period_rows],
        'by_course': [{
            'course': row['quiz__course_group'] or 'Sin curso/grupo',
            'year': row['started_at__year'],
            'period': row['quiz__academic_period'],
            'attempts': row['attempts'],
            'students': row['students'],
            'average': round(float(row['average']), 2) if row['average'] is not None else None,
            'minimum': float(row['minimum']) if row['minimum'] is not None else None,
            'maximum': float(row['maximum']) if row['maximum'] is not None else None,
        } for row in course_rows],
        'by_student': [{
            'student_id': row['user_id'],
            'student': ' '.join(filter(None, [row['user__first_name'], row['user__last_name']])) or row['user__username'],
            'username': row['user__username'],
            'attempts': row['attempts'],
            'average': round(float(row['average']), 2) if row['average'] is not None else None,
            'minimum': float(row['minimum']) if row['minimum'] is not None else None,
            'maximum': float(row['maximum']) if row['maximum'] is not None else None,
        } for row in student_rows],
    }, axes, difficulty


class ReportView(APIView):
    serializer_class = AttemptSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='year', type=int, required=False, description='Año del intento'),
            OpenApiParameter(name='period', type=str, required=False, description='Período académico del cuestionario'),
            OpenApiParameter(name='course', type=str, required=False, description='Curso, grupo o título del simulacro'),
            OpenApiParameter(name='group', type=str, required=False, description='Curso/grupo exacto del cuestionario'),
            OpenApiParameter(name='axis', type=str, required=False, description='Eje temático, categoría o competencia'),
            OpenApiParameter(name='student', type=str, required=False, description='Nombre, usuario o identificación'),
            OpenApiParameter(name='page', type=int, required=False, description='Página de resultados'),
            OpenApiParameter(name='page_size', type=int, required=False, description='Filas por página (máximo 100)'),
        ],
        responses={200: inline_serializer(
            name='EvaluationReportResponse',
            fields={
                'filters': serializers.DictField(child=serializers.CharField(allow_blank=True)),
                'facets': serializers.DictField(),
                'summary': serializers.DictField(),
                'axes': serializers.ListField(child=serializers.DictField()),
                'difficulty': serializers.ListField(child=serializers.DictField()),
                'count': serializers.IntegerField(),
                'page': serializers.IntegerField(),
                'page_size': serializers.IntegerField(),
                'pages': serializers.IntegerField(),
                'results': AttemptSerializer(many=True),
            },
        )},
    )
    def get(self, request):
        attempts, error = _report_attempts_for_user(request.user)
        if error:
            return error
        all_attempts = attempts
        attempts, filters, error = _filtered_report_attempts(attempts, request.query_params)
        if error:
            return error
        summary, axes, difficulty = _report_aggregates(attempts, filters['axis'])
        page = request.query_params.get('page', '1')
        page_size = request.query_params.get('page_size', '10')
        try:
            page = int(page)
            page_size = int(page_size)
        except (TypeError, ValueError):
            return Response({'detail': 'La página y el tamaño deben ser números enteros.'}, status=status.HTTP_400_BAD_REQUEST)
        if page < 1 or page_size < 1 or page_size > 100:
            return Response({'detail': 'La página debe ser positiva y el tamaño debe estar entre 1 y 100.'}, status=status.HTTP_400_BAD_REQUEST)
        count = attempts.count()
        start = (page - 1) * page_size
        results = attempts.order_by('-started_at', '-id')[start:start + page_size]
        return Response({
            'filters': filters,
            'facets': _report_facets(all_attempts, filters),
            'summary': summary,
            'axes': axes,
            'difficulty': difficulty,
            'count': count,
            'page': page,
            'page_size': page_size,
            'pages': (count + page_size - 1) // page_size,
            'results': AttemptSerializer(results, many=True, context={'request': request}).data,
        })


class ReportExportView(APIView):
    serializer_class = serializers.Serializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='year', type=int, required=False, description='Año del intento'),
            OpenApiParameter(name='period', type=str, required=False, description='Período académico'),
            OpenApiParameter(name='group', type=str, required=False, description='Curso/grupo exacto'),
            OpenApiParameter(name='axis', type=str, required=False, description='Eje temático'),
            OpenApiParameter(name='student', type=str, required=False, description='Nombre, usuario o identificación'),
        ],
        responses={
            (200, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'): OpenApiTypes.BINARY,
            400: OpenApiResponse(description='Filtros inválidos.'),
            401: OpenApiResponse(description='Autenticación requerida.'),
        },
    )
    def get(self, request, report_type):
        if report_type not in {'consolidated', 'axes', 'history'}:
            return Response({'detail': 'Tipo de informe no válido.'}, status=status.HTTP_404_NOT_FOUND)
        attempts, error = _report_attempts_for_user(request.user)
        if error:
            return error
        attempts, filters, error = _filtered_report_attempts(attempts, request.query_params)
        if error:
            return error
        summary, axes, difficulty = _report_aggregates(attempts, filters['axis'])
        workbook = Workbook()
        sheet = workbook.active
        report_names = {
            'consolidated': 'Consolidado general',
            'axes': 'Desempeño por eje',
            'history': 'Historial individual',
        }
        sheet.title = report_names[report_type][:31]
        sheet.append([report_names[report_type]])
        sheet.append([f'Generado: {timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")}'])
        sheet.append([f'Filtros: {filters}'])
        if report_type == 'axes':
            sheet.append(['Eje temático', 'Respuestas registradas', 'Aciertos', 'Errores', 'Porcentaje de aciertos'])
            for row in axes:
                sheet.append([row['axis'], row['responses'], row['correct'], row['incorrect'], row['accuracy_percent']])
        elif report_type == 'history':
            sheet.append(['Estudiante', 'Identificación', 'Curso/grupo', 'Período', 'Simulacro', 'Fecha', 'Preguntas respondidas', 'Aciertos', 'Errores', 'Nota final', 'Estado'])
            answer_stats = {
                row['attempt_id']: row
                for row in AttemptAnswer.objects.filter(attempt__in=attempts, selected_option__isnull=False)
                .values('attempt_id').annotate(
                    answered=Count('id'),
                    correct=Count('id', filter=Q(selected_option__is_correct=True)),
                )
            }
            for attempt in attempts.order_by('started_at', 'id'):
                answers = answer_stats.get(attempt.id, {})
                try:
                    code = attempt.user.profile.institutional_code or ''
                except UserProfile.DoesNotExist:
                    code = ''
                sheet.append([
                    attempt.user.get_full_name() or attempt.user.username, code,
                    attempt.quiz.course_group, attempt.quiz.academic_period, attempt.quiz.title,
                    timezone.localtime(attempt.submitted_at or attempt.started_at).strftime('%Y-%m-%d %H:%M:%S'),
                    answers.get('answered', 0), answers.get('correct', 0),
                    answers.get('answered', 0) - answers.get('correct', 0),
                    float(attempt.grade) if attempt.grade is not None else None, attempt.get_status_display(),
                ])
        else:
            sheet.append(['Año', 'Período', 'Curso/grupo', 'Estudiante', 'Identificación', 'Simulacro', 'Fecha', 'Calificación', 'Estado'])
            for attempt in attempts.order_by('-started_at', '-id'):
                try:
                    code = attempt.user.profile.institutional_code or ''
                except UserProfile.DoesNotExist:
                    code = ''
                sheet.append([
                    attempt.started_at.year, attempt.quiz.academic_period, attempt.quiz.course_group,
                    attempt.user.get_full_name() or attempt.user.username, code, attempt.quiz.title,
                    timezone.localtime(attempt.submitted_at or attempt.started_at).strftime('%Y-%m-%d %H:%M:%S'),
                    float(attempt.grade) if attempt.grade is not None else None, attempt.get_status_display(),
                ])
            difficulty_sheet = workbook.create_sheet('Preguntas difíciles')
            difficulty_sheet.append(['Pregunta ID', 'Eje temático', 'Pregunta', 'Respuestas', 'Aciertos', 'Errores', 'Porcentaje de aciertos'])
            for row in difficulty:
                difficulty_sheet.append([
                    row['question_id'], row['axis'], row['question'], row['responses'],
                    row['correct'], row['incorrect'], row['accuracy_percent'],
                ])
            summary_sheet = workbook.create_sheet('Resumen')
            summary_sheet.append(['Indicador', 'Valor'])
            scalar_summary = {key: value for key, value in summary.items() if not isinstance(value, list)}
            for key, value in scalar_summary.items():
                summary_sheet.append([key.replace('_', ' ').title(), value])
            period_sheet = workbook.create_sheet('Por período')
            period_sheet.append(['Año', 'Período', 'Intentos', 'Estudiantes', 'Promedio', 'Mínima', 'Máxima'])
            for row in summary['by_period']:
                period_sheet.append([row['year'], row['period'], row['attempts'], row['students'], row['average'], row['minimum'], row['maximum']])
            course_sheet = workbook.create_sheet('Por curso')
            course_sheet.append(['Curso/grupo', 'Año', 'Período', 'Intentos', 'Estudiantes', 'Promedio', 'Mínima', 'Máxima'])
            for row in summary['by_course']:
                course_sheet.append([row['course'], row['year'], row['period'], row['attempts'], row['students'], row['average'], row['minimum'], row['maximum']])
            student_sheet = workbook.create_sheet('Por estudiante')
            student_sheet.append(['Estudiante', 'Usuario', 'Intentos', 'Promedio', 'Mínima', 'Máxima'])
            for row in summary['by_student']:
                student_sheet.append([row['student'], row['username'], row['attempts'], row['average'], row['minimum'], row['maximum']])
        for current_sheet in workbook.worksheets:
            header_row = 4 if current_sheet is sheet else 1
            current_sheet.freeze_panes = f'A{header_row + 1}'
            current_sheet.auto_filter.ref = f'A{header_row}:{current_sheet.cell(current_sheet.max_row, current_sheet.max_column).coordinate}'
            for cell in current_sheet[header_row]:
                cell.font = cell.font.copy(bold=True)
            for column in current_sheet.columns:
                current_sheet.column_dimensions[column[0].column_letter].width = min(
                    max(14, max(len(str(cell.value or '')) for cell in column) + 2), 60,
                )
                for cell in column:
                    if isinstance(cell.value, float):
                        cell.number_format = '0.00'
        buffer = BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="reporte-{report_type}-{timezone.localdate().isoformat()}.xlsx"'
        return response


class AttemptDetailView(APIView):
    serializer_class = AttemptSerializer
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        attempt = get_object_or_404(Attempt.objects.select_related('quiz', 'user'), pk=pk)
        if attempt.user_id != request.user.id:
            if request.user.is_superuser:
                pass
            else:
                try:
                    role = request.user.profile.role
                except UserProfile.DoesNotExist:
                    return Response({'detail': 'No tienes permiso para consultar este intento.'}, status=status.HTTP_403_FORBIDDEN)
                can_view_assigned = 'results.view_assigned' in role.permissions and attempt.quiz.created_by_id == request.user.id
                if not role.is_active or not ('results.view_all' in role.permissions or can_view_assigned):
                    return Response({'detail': 'No tienes permiso para consultar este intento.'}, status=status.HTTP_403_FORBIDDEN)
        elif not request.user.is_superuser:
            try:
                role = request.user.profile.role
            except UserProfile.DoesNotExist:
                return Response({'detail': 'La cuenta no tiene un rol asignado.'}, status=status.HTTP_403_FORBIDDEN)
            if not role.is_active or (
                attempt.status == Attempt.Status.IN_PROGRESS and 'quizzes.take' not in role.permissions
            ) or (
                attempt.status == Attempt.Status.COMPLETED and 'results.view_own' not in role.permissions
            ):
                return Response({'detail': 'Tu rol no puede consultar resultados.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(AttemptSerializer(attempt).data)


class AttemptAnswerView(APIView):
    serializer_class = AttemptAnswerSerializer
    required_permission = 'quizzes.take'
    permission_classes = [HasRolePermission]

    def post(self, request, pk):
        attempt = get_object_or_404(Attempt, pk=pk, user=request.user)
        if attempt.status == Attempt.Status.COMPLETED:
            return Response({'detail': 'El intento ya fue finalizado.'}, status=status.HTTP_400_BAD_REQUEST)
        deadline = attempt.started_at + timedelta(minutes=attempt.quiz.duration_minutes)
        if timezone.now() >= deadline:
            return Response({'detail': 'El tiempo del intento terminó; envía la evaluación para calificar las respuestas guardadas.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = AttemptAnswerSerializer(data=request.data, context={'attempt': attempt})
        serializer.is_valid(raise_exception=True)
        answer, _ = AttemptAnswer.objects.update_or_create(
            attempt=attempt,
            question=serializer.validated_data['question'],
            defaults={'selected_option': serializer.validated_data['selected_option']},
        )
        return Response({'question_id': answer.question_id, 'saved': True})


class AttemptSubmitView(APIView):
    serializer_class = AttemptSerializer
    required_permission = 'quizzes.take'
    permission_classes = [HasRolePermission]

    @transaction.atomic
    def post(self, request, pk):
        attempt = get_object_or_404(Attempt.objects.select_for_update().select_related('quiz'), pk=pk, user=request.user)
        if attempt.status == Attempt.Status.COMPLETED:
            return Response(AttemptSerializer(attempt).data)
        total = Decimal('0')
        earned = Decimal('0')
        for question in attempt.quiz.questions.filter(is_active=True).prefetch_related('options'):
            total += question.default_score
            answer = attempt.answers.filter(question=question).select_related('selected_option').first()
            if answer and answer.selected_option and answer.selected_option.is_correct:
                earned += question.default_score
        grade = (earned / total * attempt.quiz.max_grade).quantize(Decimal('0.01')) if total else Decimal('0.00')
        attempt.grade = min(grade, attempt.quiz.max_grade)
        attempt.status = Attempt.Status.COMPLETED
        attempt.submitted_at = timezone.now()
        attempt.save(update_fields=['grade', 'status', 'submitted_at'])
        return Response(AttemptSerializer(attempt).data)


def _cell_text(value):
    return '' if value is None else str(value).strip()


def validate_import_rows(rows):
    errors_by_row = []
    valid = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            errors_by_row.append({'rowNumber': None, 'errors': ['La fila debe ser un objeto con número y valores.']})
            continue
        row_number = row.get('rowNumber')
        values = row.get('values', {})
        if not isinstance(values, dict):
            errors_by_row.append({'rowNumber': row_number, 'errors': ['Los datos de la fila no tienen un formato válido.']})
            continue
        data = {str(key).strip().lower(): _cell_text(value) for key, value in values.items()}
        errors = []
        category = data.get('categoria', '')
        competency = data.get('competencia', '')
        question_type = data.get('tipo', '').upper()
        stem = data.get('enunciado', '')
        correct_input = data.get('correcta', '').upper()
        correct = {'V': 'A', 'F': 'B'}.get(correct_input, correct_input) if question_type == Question.Type.TRUE_FALSE else correct_input
        score_raw = data.get('puntaje_defecto', '')
        options = [
            {'letter': letter, 'text': data.get(f'opcion_{letter.lower()}', '')}
            for letter in 'ABCD' if data.get(f'opcion_{letter.lower()}', '')
        ]
        score = None
        if not score_raw:
            errors.append('El puntaje es obligatorio.')
        else:
            try:
                score = Decimal(score_raw.replace(',', '.'))
            except InvalidOperation:
                errors.append('El puntaje debe ser un número válido.')
        if not category:
            errors.append('La categoría es obligatoria.')
        if len(category) > 100:
            errors.append('La categoría no puede superar 100 caracteres.')
        if not competency:
            errors.append('La competencia es obligatoria.')
        if len(competency) > 120:
            errors.append('La competencia no puede superar 120 caracteres.')
        if question_type not in [Question.Type.MULTIPLE, Question.Type.TRUE_FALSE]:
            errors.append('El tipo debe ser MULTIPLE o VERDADERO_FALSO.')
        if not stem:
            errors.append('El enunciado es obligatorio.')
        if score is not None:
            if not score.is_finite() or score <= 0:
                errors.append('El puntaje debe ser un número mayor que cero.')
            elif score > Decimal('999.99'):
                errors.append('El puntaje no puede superar 999.99.')
            elif score.as_tuple().exponent < -2:
                errors.append('El puntaje admite como máximo dos decimales.')
        if question_type == Question.Type.TRUE_FALSE:
            if correct_input not in ['V', 'F']:
                errors.append('En Verdadero/Falso, correcta debe ser V o F.')
            if len(options) != 2 or [o['letter'] for o in options] != ['A', 'B'] or [o['text'].lower() for o in options] != ['verdadero', 'falso']:
                errors.append('Verdadero/Falso requiere A = Verdadero y B = Falso.')
        elif question_type == Question.Type.MULTIPLE:
            if correct not in list('ABCD'):
                errors.append('En selección múltiple, correcta debe ser A, B, C o D.')
            if len(options) < 2:
                errors.append('Una pregunta de selección múltiple requiere al menos dos opciones.')
            if [o['letter'] for o in options] != list('ABCD')[:len(options)]:
                errors.append('Las opciones deben estar completas y consecutivas desde A.')
        if any(len(option['text']) > 500 for option in options):
            errors.append('El texto de cada opción no puede superar 500 caracteres.')
        if correct and not any(option['letter'] == correct for option in options):
            errors.append('La opción marcada como correcta no tiene texto.')
        signature = (category.casefold(), stem.casefold())
        if signature in seen or Question.objects.filter(category__name__iexact=category, stem__iexact=stem).exists():
            errors.append('Ya existe una pregunta con la misma categoría y enunciado.')
        seen.add(signature)
        if errors:
            errors_by_row.append({'rowNumber': row_number, 'errors': errors})
        else:
            valid.append({
                'rowNumber': row_number,
                'category': category,
                'competency': competency,
                'type': question_type,
                'base_text': data.get('texto_base', ''),
                'stem': stem,
                'feedback': data.get('retroalimentacion', ''),
                'score': score,
                'options': options,
                'correct': correct,
            })
    return valid, errors_by_row


class ImportTemplateView(APIView):
    serializer_class = serializers.Serializer
    required_permission = 'questions.manage'
    permission_classes = [HasRolePermission]

    def get(self, request):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Plantilla'
        sheet.sheet_view.showGridLines = False
        sheet.sheet_view.zoomScale = 80
        sheet.sheet_properties.tabColor = '16877D'
        sheet.freeze_panes = 'A2'
        sheet.append(IMPORT_HEADERS)
        sheet.append(['Matemáticas', 'Razonamiento cuantitativo', 'MULTIPLE', '', '¿Cuánto es 2 + 2?', '', 1, '3', '4', '5', '', 'B'])

        required_headers = {
            'categoria', 'competencia', 'tipo', 'enunciado',
            'puntaje_defecto', 'opcion_a', 'opcion_b', 'correcta',
        }
        header_fill = PatternFill('solid', fgColor='173B57')
        optional_header_fill = PatternFill('solid', fgColor='55788B')
        sample_fill = PatternFill('solid', fgColor='EEF6F4')
        header_border = Border(bottom=Side(style='medium', color='32A18F'))
        header_descriptions = {
            'categoria': 'Obligatorio. Materia o asignatura; se creará o reutilizará como categoría.',
            'competencia': 'Obligatorio. Competencia evaluada.',
            'tipo': 'Obligatorio. MULTIPLE o VERDADERO_FALSO.',
            'texto_base': 'Opcional. Texto de lectura, contexto o estímulo compartido.',
            'enunciado': 'Obligatorio. Pregunta que verá el estudiante.',
            'retroalimentacion': 'Opcional. Explicación que se mostrará al revisar el resultado.',
            'puntaje_defecto': 'Obligatorio. Número positivo con máximo dos decimales.',
            'opcion_a': 'Obligatoria. Para Verdadero/Falso escribe Verdadero.',
            'opcion_b': 'Obligatoria. Para Verdadero/Falso escribe Falso.',
            'opcion_c': 'Opcional. Si se usa, las opciones deben ser consecutivas.',
            'opcion_d': 'Opcional. Si se usa, las opciones deben ser consecutivas.',
            'correcta': 'Obligatorio. A, B, C o D; para Verdadero/Falso, V o F.',
        }
        column_widths = {
            'categoria': 22,
            'competencia': 30,
            'tipo': 23,
            'texto_base': 38,
            'enunciado': 44,
            'retroalimentacion': 38,
            'puntaje_defecto': 19,
            'opcion_a': 28,
            'opcion_b': 28,
            'opcion_c': 28,
            'opcion_d': 28,
            'correcta': 14,
        }
        for column_number, header in enumerate(IMPORT_HEADERS, start=1):
            cell = sheet.cell(row=1, column=column_number)
            cell.fill = header_fill if header in required_headers else optional_header_fill
            cell.font = Font(name='Aptos', size=10, bold=True, color='FFFFFF')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = header_border
            cell.comment = Comment(header_descriptions[header], 'Simulador Saber TyT')
            sheet.column_dimensions[cell.column_letter].width = column_widths[header]

            sample = sheet.cell(row=2, column=column_number)
            sample.fill = sample_fill
            sample.font = Font(name='Aptos', size=10, color='50656E', italic=True)
            sample.alignment = Alignment(vertical='top', wrap_text=True)
        sheet.row_dimensions[1].height = 38
        sheet.row_dimensions[2].height = 46
        sheet.auto_filter.ref = 'A1:L2'

        type_validation = DataValidation(
            type='list',
            formula1='"MULTIPLE,VERDADERO_FALSO"',
            allow_blank=False,
        )
        type_validation.error = 'Selecciona MULTIPLE o VERDADERO_FALSO.'
        type_validation.errorTitle = 'Tipo no válido'
        type_validation.prompt = 'Selecciona el formato de la pregunta.'
        type_validation.promptTitle = 'Tipo de pregunta'
        sheet.add_data_validation(type_validation)
        type_validation.add('C2:C5001')

        answer_validation = DataValidation(
            type='list',
            formula1='"A,B,C,D,V,F"',
            allow_blank=False,
        )
        answer_validation.error = 'Usa A, B, C o D; para Verdadero/Falso, usa V o F.'
        answer_validation.errorTitle = 'Respuesta no válida'
        sheet.add_data_validation(answer_validation)
        answer_validation.add('L2:L5001')

        instructions = workbook.create_sheet('Instrucciones')
        instructions.sheet_view.showGridLines = False
        instructions.sheet_view.zoomScale = 90
        instructions.sheet_properties.tabColor = 'E5A33B'
        instructions.freeze_panes = 'A5'
        instructions.merge_cells('A1:D1')
        instructions['A1'] = 'Plantilla para importar preguntas'
        instructions['A1'].font = Font(name='Aptos Display', size=20, bold=True, color='FFFFFF')
        instructions['A1'].fill = PatternFill('solid', fgColor='173B57')
        instructions['A1'].alignment = Alignment(vertical='center')
        instructions.row_dimensions[1].height = 42
        instructions.merge_cells('A2:D2')
        instructions['A2'] = 'Guía rápida para preparar y validar el banco de preguntas del Simulador Saber TyT.'
        instructions['A2'].font = Font(name='Aptos', size=11, color='50656E', italic=True)
        instructions['A2'].alignment = Alignment(wrap_text=True, vertical='center')
        instructions.row_dimensions[2].height = 30

        for column, width in {'A': 25, 'B': 15, 'C': 64, 'D': 42}.items():
            instructions.column_dimensions[column].width = width

        instruction_headers = ['Campo', 'Requerido', 'Qué debes escribir', 'Ejemplo']
        for column_number, header in enumerate(instruction_headers, start=1):
            cell = instructions.cell(row=4, column=column_number, value=header)
            cell.fill = header_fill
            cell.font = Font(name='Aptos', size=10, bold=True, color='FFFFFF')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
        instructions.row_dimensions[4].height = 28

        field_guidance = [
            ('categoria', 'Sí', 'Materia o asignatura. Se crea o reutiliza como categoría.', 'Matemáticas, Español o Ciencias'),
            ('competencia', 'Sí', 'Competencia que evalúa la pregunta.', 'Razonamiento cuantitativo'),
            ('tipo', 'Sí', 'Usa MULTIPLE o VERDADERO_FALSO.', 'MULTIPLE'),
            ('texto_base', 'No', 'Texto de lectura, contexto o estímulo compartido.', 'Lectura breve o situación problema'),
            ('enunciado', 'Sí', 'Enunciado que verá el estudiante.', '¿Cuánto es 2 + 2?'),
            ('retroalimentacion', 'No', 'Explicación para revisar después de responder.', 'Se suman las dos cantidades.'),
            ('puntaje_defecto', 'Sí', 'Número mayor que cero; admite hasta dos decimales.', '1 o 0.50'),
            ('opcion_a / opcion_b', 'Sí', 'Escribe al menos dos opciones para MULTIPLE.', '3 / 4'),
            ('opcion_c / opcion_d', 'No', 'Opciones adicionales, consecutivas y sin saltos.', '5 / 6'),
            ('correcta', 'Sí', 'MULTIPLE: letra A-D. Verdadero/Falso: V o F.', 'B o V'),
        ]
        for row_number, values in enumerate(field_guidance, start=5):
            for column_number, value in enumerate(values, start=1):
                cell = instructions.cell(row=row_number, column=column_number, value=value)
                cell.fill = PatternFill(
                    'solid',
                    fgColor='F1F6F8' if row_number % 2 else 'FFFFFF',
                )
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                cell.border = Border(bottom=Side(style='hair', color='D8E3E8'))
            instructions.row_dimensions[row_number].height = 34

        instructions.merge_cells('A16:D16')
        instructions['A16'] = 'Antes de importar'
        instructions['A16'].font = Font(name='Aptos', size=12, bold=True, color='FFFFFF')
        instructions['A16'].fill = PatternFill('solid', fgColor='16877D')
        instructions['A16'].alignment = Alignment(vertical='center')
        instructions.row_dimensions[16].height = 28

        quick_steps = [
            '1. Completa una pregunta por fila en la hoja Plantilla y conserva intactos los encabezados.',
            '2. La fila 2 es solo un ejemplo: elimínala antes de importar para no guardar esa pregunta de muestra.',
            '3. En selección múltiple, las opciones deben empezar en A y estar completas/consecutivas hasta la última usada.',
            '4. Para Verdadero/Falso escribe opcion_a = Verdadero, opcion_b = Falso y correcta = V o F.',
            '5. Usa la vista previa del sistema; corrige cualquier fila señalada antes de confirmar la importación.',
        ]
        for row_number, text in enumerate(quick_steps, start=17):
            instructions.merge_cells(start_row=row_number, start_column=1, end_row=row_number, end_column=4)
            cell = instructions.cell(row=row_number, column=1, value=text)
            cell.fill = PatternFill('solid', fgColor='F1F6F8' if row_number % 2 else 'FFFFFF')
            cell.font = Font(name='Aptos', size=10, color='304B59')
            cell.alignment = Alignment(vertical='center', wrap_text=True)
            cell.border = Border(bottom=Side(style='hair', color='D8E3E8'))
            instructions.row_dimensions[row_number].height = 30

        buffer = BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="plantilla_banco_preguntas.xlsx"'
        return response


class ImportPreviewView(APIView):
    serializer_class = serializers.Serializer
    parser_classes = [MultiPartParser, FormParser]
    required_permission = 'questions.manage'
    permission_classes = [HasRolePermission]

    def post(self, request):
        upload = request.FILES.get('file')
        if not upload or not upload.name.lower().endswith('.xlsx'):
            return Response({'detail': 'Selecciona un archivo .xlsx válido.'}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > 10 * 1024 * 1024:
            return Response({'detail': 'El archivo supera el límite de 10 MB.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            workbook = load_workbook(upload, read_only=True, data_only=True)
            sheet = workbook.active
            iterator = sheet.iter_rows(values_only=True)
            headers = [_cell_text(value).lower() for value in next(iterator, ())]
            missing = [header for header in REQUIRED_HEADERS if header not in headers]
            if missing:
                return Response({'detail': f'Faltan encabezados obligatorios: {", ".join(missing)}.'}, status=status.HTTP_400_BAD_REQUEST)
            rows = []
            for row_number, cells in enumerate(iterator, start=2):
                if not any(_cell_text(value) for value in cells):
                    continue
                values = {
                    header: _cell_text(cells[headers.index(header)]) if header in headers and headers.index(header) < len(cells) else ''
                    for header in IMPORT_HEADERS
                }
                rows.append({'rowNumber': row_number, 'values': values})
                if len(rows) > 5000:
                    return Response({'detail': 'El archivo no puede contener más de 5000 preguntas.'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, OSError, KeyError, BadZipFile, InvalidFileException) as error:
            return Response({'detail': f'No fue posible leer el archivo Excel: {error}'}, status=status.HTTP_400_BAD_REQUEST)
        valid, errors = validate_import_rows(rows)
        return Response({'total': len(rows), 'valid': len(valid), 'failed': len(errors), 'errors': errors, 'rows': rows})


class ImportCommitView(APIView):
    serializer_class = serializers.Serializer
    parser_classes = [JSONParser]
    required_permission = 'questions.manage'
    permission_classes = [HasRolePermission]

    @transaction.atomic
    def post(self, request):
        file_name = request.data.get('file_name')
        rows = request.data.get('rows')
        if not isinstance(file_name, str) or not file_name.strip() or len(file_name) > 255:
            return Response({'detail': 'El nombre del archivo no es válido.'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(rows, list) or not rows or len(rows) > 5000:
            return Response({'detail': 'La importación debe contener entre 1 y 5000 filas.'}, status=status.HTTP_400_BAD_REQUEST)
        quiz_id = request.data.get('quiz_id')
        destination_quiz = None
        if quiz_id not in (None, ''):
            try:
                quiz_id = int(quiz_id)
            except (TypeError, ValueError):
                return Response({'quiz_id': 'Selecciona un cuestionario válido.'}, status=status.HTTP_400_BAD_REQUEST)
            destination_quiz = get_object_or_404(Quiz.objects.select_for_update(), pk=quiz_id)
            if not request.user.is_superuser:
                try:
                    role = request.user.profile.role
                except UserProfile.DoesNotExist:
                    return Response({'detail': 'La cuenta no tiene un rol asignado.'}, status=status.HTTP_403_FORBIDDEN)
                if (
                    not role.is_active
                    or 'quizzes.manage' not in role.permissions
                    or ('results.view_all' not in role.permissions and destination_quiz.created_by_id != request.user.id)
                ):
                    return Response({'detail': 'No tienes permiso para agregar preguntas a ese cuestionario.'}, status=status.HTTP_403_FORBIDDEN)
            if destination_quiz.attempts.exists():
                return Response({'detail': 'No se pueden agregar preguntas a un cuestionario con intentos iniciados.'}, status=status.HTTP_400_BAD_REQUEST)
        valid, errors = validate_import_rows(rows)
        record = ImportRecord.objects.create(
            file_name=file_name.strip(),
            created_by=request.user,
            destination_quiz=destination_quiz,
            total_rows=len(rows),
            imported_rows=0,
            duplicate_rows=sum(
                1 for row_error in errors
                if any('Ya existe una pregunta' in message for message in row_error.get('errors', []))
            ),
            error_rows=len(errors),
            errors=errors,
        )
        if errors:
            return Response({'detail': 'Corrige los errores antes de guardar; no se importó ninguna pregunta.', 'errors': errors}, status=status.HTTP_400_BAD_REQUEST)
        imported_questions = []
        for row in valid:
            category, _ = Category.objects.get_or_create(
                name__iexact=row['category'],
                defaults={'name': row['category']},
            )
            question = Question.objects.create(
                category=category,
                competency=row['competency'],
                type=row['type'],
                base_text=row['base_text'],
                stem=row['stem'],
                feedback=row['feedback'],
                default_score=row['score'],
            )
            AnswerOption.objects.bulk_create([
                AnswerOption(question=question, letter=option['letter'], text=option['text'], is_correct=option['letter'] == row['correct'])
                for option in row['options']
            ])
            imported_questions.append(question)
        if destination_quiz:
            destination_quiz.questions.add(*imported_questions)
        record.imported_rows = len(valid)
        record.save(update_fields=['imported_rows'])
        return Response({'total': len(rows), 'successful': len(valid), 'failed': 0, 'id': record.id}, status=status.HTTP_201_CREATED)


class ImportHistoryView(APIView):
    serializer_class = ImportRecordSerializer
    required_permission = 'questions.manage'
    permission_classes = [HasRolePermission]

    def get(self, request):
        records = ImportRecord.objects.select_related('created_by', 'destination_quiz')
        return Response(ImportRecordSerializer(records, many=True).data)
