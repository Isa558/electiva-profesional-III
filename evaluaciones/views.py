from decimal import Decimal, InvalidOperation
from io import BytesIO
from zipfile import BadZipFile

from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from django.db import DatabaseError, connection
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from rest_framework import status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
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


class ReportView(APIView):
    serializer_class = AttemptSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(name='year', type=int, required=False, description='Año del intento'),
            OpenApiParameter(name='course', type=str, required=False, description='Curso o título del simulacro'),
            OpenApiParameter(name='axis', type=str, required=False, description='Eje temático, categoría o competencia'),
        ],
        responses={200: AttemptSerializer(many=True)},
    )
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

        year = request.query_params.get('year')
        course = request.query_params.get('course')
        axis = request.query_params.get('axis')
        if year:
            try:
                year = int(year)
            except (TypeError, ValueError):
                return Response({'year': 'Debe ser un año válido.'}, status=status.HTTP_400_BAD_REQUEST)
            attempts = attempts.filter(started_at__year=year)
        if course:
            attempts = attempts.filter(
                Q(quiz__title__icontains=course)
                | Q(user__profile__institutional_code__icontains=course)
                | Q(quiz__questions__category__name__icontains=course)
            ).distinct()
        if axis:
            attempts = attempts.filter(
                Q(quiz__questions__competency__icontains=axis)
                | Q(quiz__questions__category__name__icontains=axis)
                | Q(quiz__questions__category__competency__icontains=axis)
            ).distinct()
        return Response({
            'filters': {'year': year, 'course': course, 'axis': axis},
            'count': attempts.count(),
            'results': AttemptSerializer(attempts, many=True).data,
        })


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
        sheet.append(IMPORT_HEADERS)
        sheet.append(['Matemáticas', 'Razonamiento cuantitativo', 'MULTIPLE', '', '¿Cuánto es 2 + 2?', '', 1, '3', '4', '5', '', 'B'])
        instructions = workbook.create_sheet('Instrucciones')
        instructions.append(['Importación de preguntas'])
        instructions.append(['Una pregunta por fila. No modifiques los encabezados de la hoja Plantilla.'])
        instructions.append(['En categoria escribe la materia o asignatura, por ejemplo: Matemáticas, Español, Inglés o Ciencias.'])
        instructions.append(['Al guardar, cada materia se crea o reutiliza como categoría del banco de preguntas.'])
        instructions.append(['competencia es obligatoria e indica la competencia evaluada en esa pregunta.'])
        instructions.append(['puntaje_defecto es obligatorio; usa un número positivo con máximo dos decimales.'])
        instructions.append(['tipo: MULTIPLE o VERDADERO_FALSO.'])
        instructions.append(['Para selección múltiple se requieren opciones consecutivas desde A y correcta A-D.'])
        instructions.append(['Para Verdadero/Falso usa opcion_a = Verdadero, opcion_b = Falso y correcta = V o F.'])
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
        valid, errors = validate_import_rows(rows)
        record = ImportRecord.objects.create(
            file_name=file_name.strip(),
            created_by=request.user,
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
