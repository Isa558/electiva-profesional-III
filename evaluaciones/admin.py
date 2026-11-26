from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError
from django.forms import CheckboxSelectMultiple, ModelForm, MultipleChoiceField
from django.forms.models import BaseInlineFormSet

from .models import AnswerOption, Attempt, AttemptAnswer, Category, ImportRecord, Question, Quiz, QuizQuestion, Role, ROLE_PERMISSIONS, SystemSettings, UserProfile

User = get_user_model()
MODEL_PERMISSIONS = {
    User: 'users.manage',
    UserProfile: 'users.manage',
    Role: 'roles.manage',
    Category: 'questions.manage',
    Question: 'questions.manage',
    AnswerOption: 'questions.manage',
    Quiz: 'quizzes.manage',
    QuizQuestion: 'quizzes.manage',
    Attempt: 'results.view_all',
    AttemptAnswer: 'results.view_all',
    ImportRecord: 'questions.manage',
    SystemSettings: 'settings.manage',
}


def role_allows(request, permission):
    if request.user.is_superuser:
        return True
    try:
        role = request.user.profile.role
    except UserProfile.DoesNotExist:
        return False
    return role.is_active and permission in role.permissions


class RoleAwareAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return role_allows(request, MODEL_PERMISSIONS[self.model])

    def has_view_permission(self, request, obj=None):
        return role_allows(request, MODEL_PERMISSIONS[self.model])

    def has_add_permission(self, request):
        permission = MODEL_PERMISSIONS[self.model]
        return permission != 'results.view_all' and role_allows(request, permission)

    def has_change_permission(self, request, obj=None):
        return role_allows(request, MODEL_PERMISSIONS[self.model])

    def has_delete_permission(self, request, obj=None):
        permission = MODEL_PERMISSIONS[self.model]
        return permission != 'results.view_all' and role_allows(request, permission)


class RoleAwareInline(admin.TabularInline):
    def has_add_permission(self, request, obj=None):
        return role_allows(request, MODEL_PERMISSIONS[self.model])

    def has_change_permission(self, request, obj=None):
        return role_allows(request, MODEL_PERMISSIONS[self.model])

    def has_delete_permission(self, request, obj=None):
        return role_allows(request, MODEL_PERMISSIONS[self.model])


class AnswerOptionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(form.errors for form in self.forms):
            return
        options = [
            form.cleaned_data for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE') and form.cleaned_data.get('text')
        ]
        letters = [option.get('letter') for option in options]
        if (
            len(options) < 2
            or letters != list('ABCD')[:len(options)]
            or len(set(letters)) != len(letters)
        ):
            raise ValidationError('Agrega al menos dos opciones con letras únicas entre A y D.')
        if sum(bool(option.get('is_correct')) for option in options) != 1:
            raise ValidationError('Debes marcar exactamente una respuesta correcta.')
        if self.instance.type == Question.Type.TRUE_FALSE and (
            len(options) != 2 or letters != ['A', 'B']
            or [option['text'].strip().lower() for option in options] != ['verdadero', 'falso']
        ):
            raise ValidationError('Verdadero/Falso requiere A = Verdadero y B = Falso.')

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    extra = 0

    def has_add_permission(self, request, obj=None):
        return role_allows(request, 'users.manage')

    has_change_permission = has_add_permission
    has_delete_permission = has_add_permission


admin.site.unregister(User)


@admin.register(User)
class UserAdmin(RoleAwareAdmin, DjangoUserAdmin):
    inlines = [UserProfileInline]
    list_display = DjangoUserAdmin.list_display + ('is_active',)

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.is_superuser or obj.quiz_attempts.exists()):
            return False
        return super().has_delete_permission(request, obj)

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model is UserProfile:
            user = form.instance
            permissions = set(user.profile.role.permissions) if hasattr(user, 'profile') else set()
            user.is_staff = bool(permissions.intersection({
                'users.manage', 'roles.manage', 'questions.manage', 'quizzes.manage', 'results.view_all',
                'settings.manage',
            }))
            user.save(update_fields=['is_staff'])


@admin.register(Role)
class RoleAdmin(RoleAwareAdmin):
    class Form(ModelForm):
        permissions = MultipleChoiceField(
            choices=ROLE_PERMISSIONS,
            widget=CheckboxSelectMultiple,
            required=False,
            label='Permisos',
        )

        class Meta:
            model = Role
            fields = '__all__'

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.instance and self.instance.pk:
                self.initial['permissions'] = self.instance.permissions

        def clean_permissions(self):
            return list(dict.fromkeys(self.cleaned_data['permissions']))

    form = Form
    list_display = ['name', 'slug', 'is_system', 'is_active']
    list_filter = ['is_system', 'is_active']
    search_fields = ['name', 'slug']
    fields = ['name', 'slug', 'description', 'permissions', 'is_active', 'is_system']
    readonly_fields = ['is_system']

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.is_system)

    def delete_queryset(self, request, queryset):
        queryset.exclude(is_system=True).delete()

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        admin_permissions = {'users.manage', 'roles.manage', 'questions.manage', 'quizzes.manage', 'results.view_all', 'settings.manage'}
        is_staff = bool(admin_permissions.intersection(obj.permissions))
        for profile in obj.users.select_related('user'):
            if profile.user.is_staff != is_staff:
                profile.user.is_staff = is_staff
                profile.user.save(update_fields=['is_staff'])


@admin.register(Category)
class CategoryAdmin(RoleAwareAdmin):
    list_display = ['name', 'competency', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'competency']


class AnswerOptionInline(RoleAwareInline):
    model = AnswerOption
    extra = 2
    formset = AnswerOptionFormSet

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and not (
            obj and (obj.quiz_questions.filter(quiz__attempts__isnull=False).exists() or obj.attempt_answers.exists())
        )

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (
            obj and (obj.quiz_questions.filter(quiz__attempts__isnull=False).exists() or obj.attempt_answers.exists())
        )

    def get_readonly_fields(self, request, obj=None):
        if obj and (obj.quiz_questions.filter(quiz__attempts__isnull=False).exists() or obj.attempt_answers.exists()):
            return [field.name for field in self.model._meta.fields]
        return []


@admin.register(Question)
class QuestionAdmin(RoleAwareAdmin):
    list_display = ['stem', 'category', 'competency', 'type', 'default_score', 'is_active']
    list_filter = ['category', 'type', 'is_active']
    search_fields = ['stem', 'competency']
    inlines = [AnswerOptionInline]
    actions = ['activate_questions', 'deactivate_questions']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.quiz_questions.filter(quiz__attempts__status='IN_PROGRESS').exists():
            return [field.name for field in obj._meta.fields]
        if obj and (
            obj.quiz_questions.filter(quiz__attempts__isnull=False).exists() or obj.attempt_answers.exists()
        ):
            return [field.name for field in obj._meta.fields if field.name != 'is_active']
        return []

    def has_delete_permission(self, request, obj=None):
        if obj and (obj.quiz_questions.exists() or obj.attempt_answers.exists()):
            return False
        return super().has_delete_permission(request, obj)

    @admin.action(description='Activar preguntas seleccionadas')
    def activate_questions(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description='Desactivar preguntas seleccionadas')
    def deactivate_questions(self, request, queryset):
        queryset.exclude(quiz_questions__quiz__attempts__status='IN_PROGRESS').distinct().update(is_active=False)


class QuizQuestionInline(RoleAwareInline):
    model = QuizQuestion
    extra = 1

    def has_add_permission(self, request, obj=None):
        return super().has_add_permission(request, obj) and not (obj and obj.attempts.exists())

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.attempts.exists())

    def get_readonly_fields(self, request, obj=None):
        return ['question'] if obj and obj.attempts.exists() else []


class QuizQuestionFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(form.errors for form in self.forms):
            return
        questions = [
            form.cleaned_data.get('question') for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get('DELETE')
        ]
        if self.instance.is_active and not any(question and question.is_active for question in questions):
            raise ValidationError('Un cuestionario habilitado debe contener al menos una pregunta activa.')

QuizQuestionInline.formset = QuizQuestionFormSet

class QuizAdminForm(ModelForm):
    class Meta:
        model = Quiz
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        opens_at = cleaned_data.get('opens_at')
        closes_at = cleaned_data.get('closes_at')
        if opens_at and closes_at and closes_at <= opens_at:
            self.add_error('closes_at', 'La fecha de cierre debe ser posterior a la apertura.')
        return cleaned_data


@admin.register(Quiz)
class QuizAdmin(RoleAwareAdmin):
    form = QuizAdminForm
    list_display = ['title', 'opens_at', 'closes_at', 'duration_minutes', 'attempts_allowed', 'is_active']
    list_filter = ['is_active']
    search_fields = ['title']
    inlines = [QuizQuestionInline]
    actions = ['activate_quizzes', 'deactivate_quizzes']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.attempts.exists():
            return ['title', 'description', 'opens_at', 'closes_at', 'duration_minutes', 'attempts_allowed', 'max_grade']
        return []

    def has_delete_permission(self, request, obj=None):
        if obj and obj.attempts.exists():
            return False
        return super().has_delete_permission(request, obj)

    @admin.action(description='Habilitar cuestionarios seleccionados')
    def activate_quizzes(self, request, queryset):
        queryset.filter(quiz_questions__question__is_active=True).distinct().update(is_active=True)

    @admin.action(description='Deshabilitar cuestionarios seleccionados')
    def deactivate_quizzes(self, request, queryset):
        queryset.update(is_active=False)


class AttemptAnswerInline(RoleAwareInline):
    model = AttemptAnswer
    extra = 0
    readonly_fields = ['question', 'selected_option']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Attempt)
class AttemptAdmin(RoleAwareAdmin):
    list_display = ['user', 'quiz', 'status', 'started_at', 'submitted_at', 'grade']
    list_filter = ['status', 'quiz']
    search_fields = ['user__username', 'quiz__title']
    readonly_fields = ['user', 'quiz', 'status', 'started_at', 'submitted_at', 'grade']
    inlines = [AttemptAnswerInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportRecord)
class ImportRecordAdmin(RoleAwareAdmin):
    list_display = ['file_name', 'created_by', 'created_at', 'total_rows', 'imported_rows', 'duplicate_rows', 'error_rows']
    search_fields = ['file_name', 'created_by__username']
    readonly_fields = [field.name for field in ImportRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SystemSettings)
class SystemSettingsAdmin(RoleAwareAdmin):
    list_display = ['system_name', 'institution_name', 'support_email', 'updated_at']
    readonly_fields = ['updated_at']
