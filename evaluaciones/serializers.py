from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from drf_spectacular.utils import extend_schema_field

from .models import AnswerOption, Attempt, AttemptAnswer, Category, Question, Quiz, QuizQuestion, Role, ROLE_PERMISSIONS, SystemSettings, UserProfile, ImportRecord

User = get_user_model()
VALID_ROLE_PERMISSIONS = {code for code, _ in ROLE_PERMISSIONS}


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'slug', 'description', 'permissions', 'is_active', 'is_system']
        read_only_fields = ['is_system']

    def validate_permissions(self, value):
        if not isinstance(value, list) or any(
            not isinstance(permission, str) or permission not in VALID_ROLE_PERMISSIONS
            for permission in value
        ):
            raise serializers.ValidationError('Incluye únicamente permisos disponibles en el sistema.')
        return list(dict.fromkeys(value))

    def update(self, instance, validated_data):
        role = super().update(instance, validated_data)
        admin_permissions = {'users.manage', 'roles.manage', 'questions.manage', 'quizzes.manage', 'results.view_all', 'settings.manage'}
        is_staff = bool(admin_permissions.intersection(role.permissions))
        for profile in role.users.select_related('user'):
            if profile.user.is_staff != is_staff:
                profile.user.is_staff = is_staff
                profile.user.save(update_fields=['is_staff'])
        return role


class UserSerializer(serializers.ModelSerializer):
    role_id = serializers.PrimaryKeyRelatedField(queryset=Role.objects.filter(is_active=True), source='profile.role', write_only=True)
    assigned_role_id = serializers.IntegerField(source='profile.role_id', read_only=True)
    role = serializers.SerializerMethodField()
    institutional_code = serializers.CharField(source='profile.institutional_code', required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'institutional_code', 'is_active', 'role', 'assigned_role_id', 'role_id', 'password']
        read_only_fields = ['id']

    def get_role(self, user):
        try:
            return user.profile.role.name
        except UserProfile.DoesNotExist:
            return None

    def validate_email(self, value):
        if value and User.objects.filter(email__iexact=value).exclude(pk=getattr(self.instance, 'pk', None)).exists():
            raise serializers.ValidationError('Este correo ya está asignado a otra cuenta.')
        return value

    def validate_institutional_code(self, value):
        if value and UserProfile.objects.filter(institutional_code__iexact=value).exclude(user_id=getattr(self.instance, 'pk', None)).exists():
            raise serializers.ValidationError('Este código institucional ya está asignado a otra cuenta.')
        return value

    def create(self, validated_data):
        profile_data = validated_data.pop('profile')
        password = validated_data.pop('password')
        role = profile_data['role']
        institutional_code = profile_data.get('institutional_code') or None
        user = User(**validated_data)
        user.set_password(password)
        user.is_staff = bool({'users.manage', 'roles.manage', 'questions.manage', 'quizzes.manage', 'results.view_all', 'settings.manage'}.intersection(role.permissions))
        user.save()
        UserProfile.objects.create(user=user, role=role, institutional_code=institutional_code)
        return user

    def validate(self, attrs):
        if self.instance is None and not attrs.get('password'):
            raise serializers.ValidationError({'password': 'La contraseña es obligatoria al crear un usuario.'})
        return attrs

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        password = validated_data.pop('password', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if profile_data:
            if 'role' in profile_data:
                instance.profile.role = profile_data['role']
                instance.is_staff = bool({
                    'users.manage', 'roles.manage', 'questions.manage', 'quizzes.manage', 'results.view_all', 'settings.manage',
                }.intersection(profile_data['role'].permissions))
            if 'institutional_code' in profile_data:
                instance.profile.institutional_code = profile_data['institutional_code'] or None
            instance.profile.save()
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name', 'competency', 'is_active']


class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerOption
        fields = ['id', 'letter', 'text', 'is_correct']

    def validate_letter(self, value):
        return value.upper()


class QuestionSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = Question
        fields = ['id', 'category', 'category_name', 'competency', 'type', 'base_text', 'stem', 'feedback', 'default_score', 'is_active', 'options']

    def validate(self, attrs):
        category = attrs.get('category', getattr(self.instance, 'category', None))
        competency = attrs.get('competency', getattr(self.instance, 'competency', '')).strip()
        if competency:
            attrs['competency'] = competency
        if (self.instance is None or 'competency' in attrs) and not competency:
            raise serializers.ValidationError({'competency': 'La competencia es obligatoria.'})
        stem = attrs.get('stem', getattr(self.instance, 'stem', '')).strip()
        if stem:
            attrs['stem'] = stem
        if category and stem:
            duplicates = Question.objects.filter(category=category, stem__iexact=stem)
            if self.instance:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({
                    'stem': 'Ya existe una pregunta con el mismo enunciado en esta categoría.'
                })
        if self.instance and 'options' not in attrs:
            options = [
                {'letter': option.letter, 'text': option.text, 'is_correct': option.is_correct}
                for option in self.instance.options.all()
            ]
        else:
            options = attrs.get('options', [])
        question_type = attrs.get('type', getattr(self.instance, 'type', Question.Type.MULTIPLE))
        letters = [option.get('letter', '').upper() for option in options]
        correct_count = sum(bool(option.get('is_correct')) for option in options)
        if len(options) < 2 or letters != list('ABCD')[:len(options)] or len(set(letters)) != len(letters):
            raise serializers.ValidationError({'options': 'Agrega opciones consecutivas desde A con letras únicas.'})
        if correct_count != 1:
            raise serializers.ValidationError({'options': 'Debes marcar exactamente una respuesta correcta.'})
        if question_type == Question.Type.TRUE_FALSE and (
            len(options) != 2 or letters != ['A', 'B']
            or options[0].get('text', '').strip().lower() != 'verdadero'
            or options[1].get('text', '').strip().lower() != 'falso'
        ):
            raise serializers.ValidationError({'options': 'Verdadero/Falso requiere A = Verdadero y B = Falso.'})
        return attrs

    def create(self, validated_data):
        options = validated_data.pop('options')
        question = Question.objects.create(**validated_data)
        AnswerOption.objects.bulk_create([
            AnswerOption(question=question, **option) for option in options
        ])
        return question

    def update(self, instance, validated_data):
        has_attempts = instance.quiz_questions.filter(quiz__attempts__isnull=False).exists() or instance.attempt_answers.exists()
        if has_attempts and (set(validated_data) - {'is_active'} or 'options' in validated_data):
            raise serializers.ValidationError('Una pregunta con intentos registrados no se puede editar; solo se puede activar o desactivar.')
        if (
            validated_data.get('is_active') is False
            and instance.quiz_questions.filter(quiz__attempts__status='IN_PROGRESS').exists()
        ):
            raise serializers.ValidationError({'is_active': 'No se puede desactivar una pregunta mientras haya intentos en curso.'})
        options = validated_data.pop('options', None)
        if options is not None and instance.attempt_answers.exists():
            raise serializers.ValidationError({'options': 'No se pueden cambiar las opciones de una pregunta que ya tiene respuestas registradas.'})
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if options is not None:
            instance.options.all().delete()
            AnswerOption.objects.bulk_create([
                AnswerOption(question=instance, **option) for option in options
            ])
        return instance


class QuizSerializer(serializers.ModelSerializer):
    question_ids = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Question.objects.all(), source='questions',
    )
    question_count = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'created_by_name', 'question_ids', 'question_count', 'opens_at', 'closes_at', 'duration_minutes', 'attempts_allowed', 'max_grade', 'passing_grade', 'is_active']

    @extend_schema_field(serializers.CharField())
    def get_created_by_name(self, quiz):
        if not quiz.created_by_id:
            return ''
        return quiz.created_by.get_full_name() or quiz.created_by.get_username()

    @extend_schema_field(serializers.IntegerField())
    def get_question_count(self, quiz):
        return quiz.questions.filter(is_active=True).count()

    def validate(self, attrs):
        opens_at = attrs.get('opens_at', getattr(self.instance, 'opens_at', None))
        closes_at = attrs.get('closes_at', getattr(self.instance, 'closes_at', None))
        max_grade = attrs.get('max_grade', getattr(self.instance, 'max_grade', None))
        passing_grade = attrs.get('passing_grade', getattr(self.instance, 'passing_grade', None))
        if opens_at and closes_at and closes_at <= opens_at:
            raise serializers.ValidationError({'closes_at': 'La fecha de cierre debe ser posterior a la apertura.'})
        if max_grade is not None and passing_grade is not None and passing_grade > max_grade:
            raise serializers.ValidationError({'passing_grade': 'La nota mínima no puede superar la nota máxima.'})
        questions = attrs.get('questions')
        if questions is not None and not questions:
            raise serializers.ValidationError({'question_ids': 'Selecciona al menos una pregunta.'})
        active = attrs.get('is_active', self.instance.is_active if self.instance else False)
        if active and questions is not None and not any(question.is_active for question in questions):
            raise serializers.ValidationError({'question_ids': 'Un cuestionario habilitado debe tener preguntas activas.'})
        if active and self.instance and questions is None and not self.instance.questions.filter(is_active=True).exists():
            raise serializers.ValidationError({'is_active': 'Un cuestionario habilitado debe tener preguntas activas.'})
        if self.instance and questions is not None and self.instance.attempts.exists():
            raise serializers.ValidationError({'question_ids': 'No puedes cambiar las preguntas después de iniciar intentos.'})
        if self.instance and self.instance.attempts.exists() and set(attrs) - {'is_active'}:
            raise serializers.ValidationError('No puedes modificar la configuración tras iniciar intentos; solo puedes habilitar o deshabilitar el cuestionario.')
        return attrs

    def create(self, validated_data):
        questions = validated_data.pop('questions')
        quiz = Quiz.objects.create(**validated_data)
        quiz.questions.set(questions)
        return quiz

    def update(self, instance, validated_data):
        questions = validated_data.pop('questions', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if questions is not None:
            instance.questions.set(questions)
        return instance


class AvailableQuizSerializer(serializers.ModelSerializer):
    question_count = serializers.SerializerMethodField()
    attempts_remaining = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = ['id', 'title', 'description', 'created_by_name', 'opens_at', 'closes_at', 'duration_minutes', 'attempts_allowed', 'max_grade', 'passing_grade', 'question_count', 'attempts_remaining']

    @extend_schema_field(serializers.IntegerField())
    def get_attempts_remaining(self, quiz):
        user = self.context['request'].user
        used = Attempt.objects.filter(quiz=quiz, user=user).count()
        return max(0, quiz.attempts_allowed - used)

    @extend_schema_field(serializers.IntegerField())
    def get_question_count(self, quiz):
        return quiz.questions.filter(is_active=True).count()

    @extend_schema_field(serializers.CharField())
    def get_created_by_name(self, quiz):
        if not quiz.created_by_id:
            return ''
        return quiz.created_by.get_full_name() or quiz.created_by.get_username()


class StudentOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnswerOption
        fields = ['id', 'letter', 'text']


class StudentQuestionSerializer(serializers.ModelSerializer):
    options = StudentOptionSerializer(many=True)
    category = serializers.CharField(source='category.name')

    class Meta:
        model = Question
        fields = ['id', 'stem', 'base_text', 'type', 'category', 'options']


class AttemptSerializer(serializers.ModelSerializer):
    quiz_title = serializers.CharField(source='quiz.title', read_only=True)
    student_username = serializers.CharField(source='user.username', read_only=True)
    student_name = serializers.SerializerMethodField()
    student_code = serializers.SerializerMethodField()
    attempt_number = serializers.SerializerMethodField()
    elapsed_minutes = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(source='quiz.duration_minutes', read_only=True)
    max_grade = serializers.DecimalField(source='quiz.max_grade', max_digits=5, decimal_places=2, read_only=True)
    passing_grade = serializers.DecimalField(source='quiz.passing_grade', max_digits=5, decimal_places=2, read_only=True)
    questions = serializers.SerializerMethodField()
    saved_answers = serializers.SerializerMethodField()

    class Meta:
        model = Attempt
        fields = ['id', 'quiz', 'quiz_title', 'student_username', 'student_name', 'student_code', 'attempt_number', 'elapsed_minutes', 'duration_minutes', 'max_grade', 'passing_grade', 'status', 'started_at', 'submitted_at', 'grade', 'questions', 'saved_answers']
        read_only_fields = fields

    @extend_schema_field(StudentQuestionSerializer(many=True))
    def get_questions(self, attempt):
        if attempt.status != Attempt.Status.IN_PROGRESS:
            return []
        return StudentQuestionSerializer(attempt.quiz.questions.filter(is_active=True), many=True).data

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField(), allow_null=True))
    def get_saved_answers(self, attempt):
        if attempt.status != Attempt.Status.IN_PROGRESS:
            return {}
        return {
            str(answer.question_id): answer.selected_option_id
            for answer in attempt.answers.exclude(selected_option=None)
        }

    @extend_schema_field(serializers.CharField())
    def get_student_name(self, attempt):
        return attempt.user.get_full_name() or attempt.user.get_username()

    @extend_schema_field(serializers.CharField())
    def get_student_code(self, attempt):
        try:
            return attempt.user.profile.institutional_code or ''
        except UserProfile.DoesNotExist:
            return ''

    @extend_schema_field(serializers.IntegerField())
    def get_attempt_number(self, attempt):
        from django.db.models import Q

        return Attempt.objects.filter(
            quiz_id=attempt.quiz_id,
            user_id=attempt.user_id,
        ).filter(
            Q(started_at__lt=attempt.started_at)
            | Q(started_at=attempt.started_at, pk__lte=attempt.pk)
        ).count()

    @extend_schema_field(serializers.IntegerField())
    def get_elapsed_minutes(self, attempt):
        ended_at = attempt.submitted_at or timezone.now()
        elapsed = max(0, (ended_at - attempt.started_at).total_seconds())
        return int(elapsed // 60)


class SystemSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSettings
        fields = ['system_name', 'institution_name', 'support_email', 'time_zone', 'updated_at']
        read_only_fields = ['updated_at']


class ImportRecordSerializer(serializers.ModelSerializer):
    destination_title = serializers.CharField(source='destination_quiz.title', read_only=True, default='')
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ImportRecord
        fields = ['id', 'file_name', 'created_by_name', 'destination_quiz', 'destination_title', 'total_rows', 'imported_rows', 'duplicate_rows', 'error_rows', 'errors', 'created_at']

    def get_created_by_name(self, record):
        return record.created_by.get_full_name() or record.created_by.get_username()


class CurrentUserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    role_slug = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    institutional_code = serializers.CharField(source='profile.institutional_code', required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'institutional_code', 'role', 'role_slug', 'permissions']
        read_only_fields = ['id', 'username', 'role', 'role_slug', 'permissions']

    def get_role(self, user):
        if user.is_superuser:
            return 'Administrador'
        return user.profile.role.name

    def get_role_slug(self, user):
        if user.is_superuser:
            return 'administrador'
        return user.profile.role.slug

    def get_permissions(self, user):
        if user.is_superuser:
            return ['*']
        return user.profile.role.permissions

    def validate_email(self, value):
        if value and User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('Este correo ya está asignado a otra cuenta.')
        return value

    def validate_institutional_code(self, value):
        if value and UserProfile.objects.filter(institutional_code__iexact=value).exclude(user_id=self.instance.pk).exists():
            raise serializers.ValidationError('Este código institucional ya está asignado a otra cuenta.')
        return value

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if profile_data:
            try:
                profile = instance.profile
            except UserProfile.DoesNotExist:
                if not instance.is_superuser:
                    raise serializers.ValidationError({'detail': 'La cuenta no tiene un rol asignado.'})
                role = Role.objects.get(slug='administrador', is_active=True)
                profile = UserProfile.objects.create(user=instance, role=role)
            if 'institutional_code' in profile_data:
                profile.institutional_code = profile_data['institutional_code'] or None
                profile.save(update_fields=['institutional_code'])
        instance.save()
        return instance


class EmailOrUsernameTokenSerializer(TokenObtainPairSerializer):
    default_error_messages = {
        'no_active_account': 'No se encontró una cuenta activa con esas credenciales.',
    }

    def validate(self, attrs):
        login = attrs.get(self.username_field, '')
        if '@' in login:
            matches = User.objects.filter(email__iexact=login)
            if matches.count() == 1:
                attrs[self.username_field] = matches.first().get_username()
        return super().validate(attrs)


class AttemptAnswerSerializer(serializers.ModelSerializer):
    question_id = serializers.PrimaryKeyRelatedField(queryset=Question.objects.all(), source='question')
    option_id = serializers.PrimaryKeyRelatedField(queryset=AnswerOption.objects.all(), source='selected_option')

    class Meta:
        model = AttemptAnswer
        fields = ['question_id', 'option_id']

    def validate(self, attrs):
        question = attrs['question']
        option = attrs['selected_option']
        attempt = self.context['attempt']
        if not attempt.quiz.questions.filter(pk=question.pk).exists():
            raise serializers.ValidationError('La pregunta no pertenece a este cuestionario.')
        if option.question_id != question.pk:
            raise serializers.ValidationError('La opción seleccionada no pertenece a la pregunta.')
        if attempt.status != Attempt.Status.IN_PROGRESS:
            raise serializers.ValidationError('El intento ya fue finalizado.')
        elapsed = (timezone.now() - attempt.started_at).total_seconds()
        if elapsed > attempt.quiz.duration_minutes * 60:
            raise serializers.ValidationError('El tiempo disponible para este intento ha terminado.')
        return attrs
