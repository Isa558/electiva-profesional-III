from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from rest_framework.test import APIClient

from .models import AnswerOption, Attempt, Category, Question, Quiz, Role, UserProfile
from .views import validate_import_rows

User = get_user_model()


class EvaluationApiTests(TestCase):
    def setUp(self):
        self.admin_role = Role.objects.get(slug='administrador')
        self.student_role = Role.objects.get(slug='estudiante')
        self.admin = User.objects.create_user('admin-demo', password='Admin-demo-123!')
        UserProfile.objects.create(user=self.admin, role=self.admin_role)
        self.student = User.objects.create_user('student-demo', password='Student-demo-123!')
        UserProfile.objects.create(user=self.student, role=self.student_role)
        self.other_student = User.objects.create_user('other-demo', password='Other-demo-123!')
        UserProfile.objects.create(user=self.other_student, role=self.student_role)
        self.category = Category.objects.create(name='Matemáticas', competency='Razonamiento cuantitativo')
        self.question = Question.objects.create(
            category=self.category,
            competency='Razonamiento cuantitativo',
            stem='¿Cuánto es 2 + 2?',
            default_score=Decimal('2.00'),
        )
        self.correct_option = AnswerOption.objects.create(question=self.question, letter='A', text='4', is_correct=True)
        AnswerOption.objects.create(question=self.question, letter='B', text='5')
        self.quiz = Quiz.objects.create(
            title='Prueba de matemáticas',
            description='Evaluación de prueba',
            opens_at=timezone.now() - timedelta(minutes=5),
            closes_at=timezone.now() + timedelta(hours=1),
            duration_minutes=30,
            attempts_allowed=2,
            max_grade=Decimal('5.00'),
            is_active=True,
        )
        self.quiz.questions.add(self.question)
        self.client = APIClient()

    def test_swagger_schema_and_docs_are_public(self):
        self.assertEqual(self.client.get('/api/docs/').status_code, 200)
        response = self.client.get('/api/schema/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/vnd.oai.openapi; charset=utf-8')

    def test_report_route_rejects_anonymous_user(self):
        response = self.client.get('/api/reportes/')
        self.assertEqual(response.status_code, 401)

    def test_full_demo_creates_subject_quizzes_idempotently(self):
        with override_settings(DEBUG=True, DEMO_ACCOUNTS_ENABLED=True):
            call_command('setup_demo_accounts', stdout=StringIO())
            call_command('setup_full_demo', stdout=StringIO())
            call_command('setup_full_demo', stdout=StringIO())

        titles = set(Quiz.objects.values_list('title', flat=True))
        self.assertIn('Simulacro Saber TyT - Matemáticas', titles)
        self.assertIn('Simulacro Saber TyT - Español', titles)
        self.assertIn('Simulacro Saber TyT - Inglés', titles)
        self.assertIn('Simulacro Saber TyT - Naturales', titles)
        self.assertIn('Simulacro Saber TyT - Ciencias', titles)
        self.assertGreaterEqual(
            Question.objects.filter(category__name__in=[
                'Matemáticas', 'Español', 'Inglés', 'Naturales', 'Ciencias',
            ]).count(),
            20,
        )

    def test_report_filters_accept_year_course_and_axis(self):
        login = self.client.post('/api/auth/token/', {
            'username': 'admin-demo',
            'password': 'Admin-demo-123!',
        }, format='json')
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        response = self.client.get('/api/reportes/', {
            'year': str(timezone.now().year),
            'course': 'Matemáticas',
            'axis': 'Razonamiento',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('filters', response.data)
        self.assertIn('results', response.data)

    def test_jwt_login_refresh_and_logout(self):
        response = self.client.post('/api/auth/token/', {'username': 'student-demo', 'password': 'Student-demo-123!'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get('/api/auth/me/').data['role_slug'], 'estudiante')

        refresh = response.data['refresh']
        refresh_response = self.client.post('/api/auth/token/refresh/', {'refresh': refresh}, format='json')
        self.assertEqual(refresh_response.status_code, 200)
        logout = self.client.post('/api/auth/logout/', {'refresh': refresh_response.data['refresh']}, format='json')
        self.assertEqual(logout.status_code, 205)
        invalid_refresh = self.client.post('/api/auth/token/refresh/', {'refresh': refresh_response.data['refresh']}, format='json')
        self.assertEqual(invalid_refresh.status_code, 401)

    def test_disabled_account_cannot_login(self):
        self.student.is_active = False
        self.student.save(update_fields=['is_active'])
        response = self.client.post('/api/auth/token/', {'username': 'student-demo', 'password': 'Student-demo-123!'}, format='json')
        self.assertEqual(response.status_code, 401)

    def test_login_error_is_localized(self):
        response = self.client.post('/api/auth/token/', {
            'username': 'not-found@sabertyt.edu.co',
            'password': 'incorrecta',
        }, format='json')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data['detail'], 'No se encontró una cuenta activa con esas credenciales.')

    def test_login_accepts_email_and_username(self):
        self.student.email = 'student@putumayo.edu.co'
        self.student.save(update_fields=['email'])
        response = self.client.post('/api/auth/token/', {
            'username': 'STUDENT@PUTUMAYO.EDU.CO',
            'password': 'Student-demo-123!',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertIn('access', response.data)

    @override_settings(DEBUG=True, DEMO_ACCOUNTS_ENABLED=True)
    def test_demo_setup_creates_accounts_idempotently_and_authenticates(self):
        output = StringIO()
        call_command('setup_demo_accounts', stdout=output)
        call_command('setup_demo_accounts', stdout=StringIO())

        for email, role_slug in [
            ('admin@sabertyt.edu.co', 'administrador'),
            ('docente@sabertyt.edu.co', 'docente'),
            ('estudiante@sabertyt.edu.co', 'estudiante'),
        ]:
            user = User.objects.get(email=email)
            self.assertTrue(user.check_password('demostracion'))
            self.assertEqual(user.profile.role.slug, role_slug)
            self.assertTrue(user.is_active)

        for email, role_slug in [
            ('admin@sabertyt.edu.co', 'administrador'),
            ('docente@sabertyt.edu.co', 'docente'),
            ('estudiante@sabertyt.edu.co', 'estudiante'),
        ]:
            login = self.client.post('/api/auth/token/', {
                'username': email,
                'password': 'demostracion',
            }, format='json')
            self.assertEqual(login.status_code, 200)
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
            self.assertEqual(self.client.get('/api/auth/me/').data['role_slug'], role_slug)
        self.assertTrue(self.client.get('/api/auth/demo-accounts/').data['enabled'])
        self.student_role.is_active = False
        self.student_role.save(update_fields=['is_active'])
        self.assertFalse(self.client.get('/api/auth/demo-accounts/').data['enabled'])

    @override_settings(DEBUG=True, DEMO_ACCOUNTS_ENABLED=True)
    def test_demo_setup_does_not_overwrite_an_existing_account(self):
        existing = User.objects.create_user(
            'admin@sabertyt.edu.co',
            email='admin@sabertyt.edu.co',
            password='User-selected-password-123!',
        )
        with self.assertRaises(CommandError):
            call_command('setup_demo_accounts', stdout=StringIO())
        existing.refresh_from_db()
        self.assertTrue(existing.check_password('User-selected-password-123!'))
        self.assertFalse(User.objects.filter(email='docente@sabertyt.edu.co').exists())

    @override_settings(DEBUG=True, DEMO_ACCOUNTS_ENABLED=True)
    def test_demo_evaluation_setup_is_idempotent_and_creates_available_quiz(self):
        call_command('setup_demo_accounts', stdout=StringIO())
        science_category = Category.objects.create(name='Ciencias')
        legacy_question = Question.objects.create(
            category=science_category,
            stem='La Tierra gira alrededor del Sol.',
            competency='',
        )
        call_command('setup_demo_evaluation', stdout=StringIO())
        call_command('setup_demo_evaluation', stdout=StringIO())

        quiz = Quiz.objects.get(title='Simulacro de demostración Saber TyT - Matemáticas y Español')
        questions = list(quiz.questions.select_related('category'))
        legacy_question.refresh_from_db()
        self.assertTrue(quiz.is_available())
        self.assertEqual(len(questions), 6)
        self.assertEqual({question.category.name for question in questions}, {'Matemáticas', 'Español'})
        self.assertTrue(all(question.competency for question in questions))
        self.assertTrue(all(question.options.filter(is_correct=True).count() == 1 for question in questions))
        self.assertEqual(legacy_question.competency, 'Explicación de fenómenos')
        self.assertEqual(Quiz.objects.filter(title=quiz.title).count(), 1)

    @override_settings(DEBUG=False, DEMO_ACCOUNTS_ENABLED=True)
    def test_demo_accounts_are_not_published_or_created_outside_debug(self):
        response = self.client.get('/api/auth/demo-accounts/')
        self.assertEqual(response.data, {'enabled': False})
        with self.assertRaises(CommandError):
            call_command('setup_demo_accounts', stdout=StringIO())

    def test_login_role_options_only_expose_active_role_names_and_slugs(self):
        Role.objects.create(name='Docente personalizado', slug='docente-personalizado', permissions=['questions.manage'])
        Role.objects.create(name='Desactivado', slug='desactivado', is_active=False)
        response = self.client.get('/api/auth/roles/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data,
            [
                {'name': 'Administrador', 'slug': 'administrador'},
                {'name': 'Docente', 'slug': 'docente'},
                {'name': 'Docente personalizado', 'slug': 'docente-personalizado'},
                {'name': 'Estudiante', 'slug': 'estudiante'},
            ],
        )
        self.assertNotIn('permissions', str(response.data))

    def test_home_page_is_served_by_django(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Simulador Saber TyT')
        self.assertContains(response, 'evaluaciones/app.css')
        self.assertContains(response, 'evaluaciones/app.js')

    def test_database_health_reports_live_database(self):
        response = self.client.get('/api/health/')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['connected'])
        self.assertIn(response.data['engine'], ['mysql', 'sqlite'])

    def test_role_permissions_are_checked_by_server(self):
        self.client.force_authenticate(self.student)
        denied = self.client.get('/api/questions/')
        self.assertEqual(denied.status_code, 403)
        self.client.force_authenticate(self.admin)
        allowed = self.client.get('/api/questions/')
        self.assertEqual(allowed.status_code, 200)

    def test_custom_role_allows_only_assigned_permissions(self):
        teacher_role = Role.objects.create(
            name='Docente Evaluador',
            slug='docente-evaluador',
            permissions=['questions.manage'],
        )
        teacher = User.objects.create_user('teacher-demo', password='Teacher-demo-123!')
        UserProfile.objects.create(user=teacher, role=teacher_role)
        self.client.force_authenticate(teacher)
        self.assertEqual(self.client.get('/api/questions/').status_code, 200)
        self.assertEqual(self.client.get('/api/users/').status_code, 403)
        self.assertEqual(self.client.get('/api/quizzes/').status_code, 403)
        teacher_role.is_active = False
        teacher_role.save(update_fields=['is_active'])
        self.assertEqual(self.client.get('/api/questions/').status_code, 403)

    def test_django_admin_respects_custom_role_permissions(self):
        teacher_role = Role.objects.create(
            name='Docente de preguntas',
            slug='docente-preguntas',
            permissions=['questions.manage'],
        )
        self.client.force_authenticate(self.admin)
        created = self.client.post('/api/users/', {
            'username': 'admin-teacher',
            'password': 'Admin-teacher-345!',
            'role_id': teacher_role.pk,
            'is_active': True,
        }, format='json')
        self.assertEqual(created.status_code, 201)
        self.client.force_authenticate(user=None)
        self.assertTrue(self.client.login(username='admin-teacher', password='Admin-teacher-345!'))
        self.assertEqual(self.client.get('/admin/evaluaciones/question/').status_code, 200)
        self.assertEqual(self.client.get('/admin/auth/user/').status_code, 403)
        teacher_role.is_active = False
        teacher_role.save(update_fields=['is_active'])
        self.assertEqual(self.client.get('/admin/').status_code, 403)

    def test_admin_role_form_displays_configurable_permissions(self):
        superuser = User.objects.create_superuser('root-demo', password='Root-demo-123!')
        self.assertTrue(self.client.login(username=superuser.username, password='Root-demo-123!'))
        response = self.client.get(f'/admin/evaluaciones/role/{self.student_role.pk}/change/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'questions.manage')
        self.assertContains(response, 'results.view_own')

    def test_student_can_start_answer_and_get_grade_without_correct_answer_leak(self):
        self.client.force_authenticate(self.student)
        available = self.client.get('/api/quizzes/available/')
        self.assertEqual(available.status_code, 200)
        self.assertEqual(len(available.data), 1)

        start = self.client.post(f'/api/quizzes/{self.quiz.pk}/attempts/', {}, format='json')
        self.assertEqual(start.status_code, 201)
        self.assertEqual(start.data['duration_minutes'], self.quiz.duration_minutes)
        self.assertEqual(start.data['attempt_number'], 1)
        self.assertEqual(start.data['student_name'], self.student.username)
        payload = str(start.data)
        self.assertNotIn('is_correct', payload)
        self.assertNotIn('isCorrect', payload)
        question = start.data['questions'][0]
        answer = self.client.post(
            f"/api/attempts/{start.data['id']}/answers/",
            {'question_id': question['id'], 'option_id': self.correct_option.id},
            format='json',
        )
        self.assertEqual(answer.status_code, 200)
        resumed = self.client.get(f"/api/attempts/{start.data['id']}/")
        self.assertEqual(resumed.data['saved_answers'], {str(question['id']): self.correct_option.id})
        self.assertNotIn('is_correct', str(resumed.data))
        submitted = self.client.post(f"/api/attempts/{start.data['id']}/submit/", {}, format='json')
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(Decimal(submitted.data['grade']), Decimal('5.00'))
        self.assertEqual(submitted.data['status'], Attempt.Status.COMPLETED)
        self.assertEqual(submitted.data['questions'], [])

    def test_student_cannot_read_another_users_attempt(self):
        attempt = Attempt.objects.create(user=self.student, quiz=self.quiz)
        self.client.force_authenticate(self.other_student)
        response = self.client.get(f'/api/attempts/{attempt.pk}/')
        self.assertEqual(response.status_code, 403)

    def test_student_cannot_start_outside_availability_or_over_attempt_limit(self):
        self.client.force_authenticate(self.student)
        self.quiz.opens_at = timezone.now() + timedelta(days=1)
        self.quiz.save(update_fields=['opens_at'])
        response = self.client.post(f'/api/quizzes/{self.quiz.pk}/attempts/', {}, format='json')
        self.assertEqual(response.status_code, 400)
        self.quiz.opens_at = timezone.now() - timedelta(hours=1)
        self.quiz.attempts_allowed = 1
        self.quiz.save(update_fields=['opens_at', 'attempts_allowed'])
        Attempt.objects.create(user=self.student, quiz=self.quiz)
        response = self.client.post(f'/api/quizzes/{self.quiz.pk}/attempts/', {}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_question_cannot_be_deactivated_during_an_active_attempt(self):
        Attempt.objects.create(user=self.student, quiz=self.quiz)
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f'/api/questions/{self.question.pk}/',
            {'is_active': False},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_admin_can_create_user_with_role(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/users/', {
            'username': 'new-student',
            'password': 'New-student-345!',
            'role_id': self.student_role.pk,
            'is_active': True,
        }, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['role'], 'Estudiante')

    def test_user_can_update_profile_and_change_password(self):
        self.client.force_authenticate(self.student)
        profile = self.client.patch('/api/auth/me/', {
            'first_name': 'Ana',
            'email': 'ana@putumayo.edu.co',
            'institutional_code': 'EST-2026-01',
        }, format='json')
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.data['first_name'], 'Ana')
        self.assertEqual(profile.data['institutional_code'], 'EST-2026-01')

        changed = self.client.post('/api/auth/password/', {
            'current_password': 'Student-demo-123!',
            'new_password': 'V@lid-NewPass-8201!',
        }, format='json')
        self.assertEqual(changed.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password('V@lid-NewPass-8201!'))

    def test_admin_can_read_and_update_system_settings(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch('/api/settings/', {
            'institution_name': 'Institución de prueba',
            'support_email': 'soporte@putumayo.edu.co',
        }, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['institution_name'], 'Institución de prueba')
        self.assertEqual(self.client.get('/api/settings/').data['support_email'], 'soporte@putumayo.edu.co')

        self.client.force_authenticate(self.student)
        denied = self.client.get('/api/settings/')
        self.assertEqual(denied.status_code, 403)

    def test_assigned_results_role_only_sees_attempts_for_its_quizzes(self):
        assigned_role = Role.objects.create(
            name='Docente Evaluador',
            slug='docente-evaluador-resultados',
            permissions=['quizzes.manage', 'results.view_assigned'],
        )
        teacher = User.objects.create_user('teacher-assigned', password='Teacher-demo-123!')
        UserProfile.objects.create(user=teacher, role=assigned_role)
        other_teacher = User.objects.create_user('teacher-other', password='Teacher-demo-123!')
        other_quiz = Quiz.objects.create(
            title='Cuestionario de otro docente',
            opens_at=timezone.now() - timedelta(minutes=5),
            closes_at=timezone.now() + timedelta(hours=1),
            duration_minutes=30,
            created_by=other_teacher,
        )
        self.quiz.created_by = teacher
        self.quiz.save(update_fields=['created_by'])
        own_attempt = Attempt.objects.create(user=self.student, quiz=self.quiz)
        Attempt.objects.create(user=self.other_student, quiz=other_quiz)

        self.client.force_authenticate(teacher)
        results = self.client.get('/api/attempts/')
        self.assertEqual(results.status_code, 200)
        self.assertEqual([row['id'] for row in results.data], [own_attempt.pk])
        self.assertEqual(self.client.get(f'/api/attempts/{own_attempt.pk}/').status_code, 200)
        other_attempt = Attempt.objects.get(quiz=other_quiz)
        self.assertEqual(self.client.get(f'/api/attempts/{other_attempt.pk}/').status_code, 403)

    def test_quiz_created_by_custom_role_is_scoped_to_its_owner(self):
        teacher_role = Role.objects.create(
            name='Docente de cuestionarios',
            slug='docente-cuestionarios',
            permissions=['quizzes.manage'],
        )
        teacher = User.objects.create_user('teacher-quizzes', password='Teacher-demo-123!')
        UserProfile.objects.create(user=teacher, role=teacher_role)
        self.client.force_authenticate(teacher)
        created = self.client.post('/api/quizzes/', {
            'title': 'Evaluación del docente',
            'description': 'Evaluación de práctica',
            'question_ids': [self.question.pk],
            'opens_at': (timezone.now() - timedelta(minutes=5)).isoformat(),
            'closes_at': (timezone.now() + timedelta(hours=1)).isoformat(),
            'duration_minutes': 25,
            'attempts_allowed': 2,
            'max_grade': '5.00',
            'passing_grade': '3.50',
            'is_active': True,
        }, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(Quiz.objects.get(pk=created.data['id']).created_by, teacher)
        listed = self.client.get('/api/quizzes/')
        self.assertEqual([quiz['id'] for quiz in listed.data], [created.data['id']])

    def test_question_api_rejects_duplicate_in_same_category(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/questions/', {
            'category': self.category.pk,
            'competency': 'Razonamiento cuantitativo',
            'type': 'MULTIPLE',
            'stem': f'  {self.question.stem.upper()}  ',
            'default_score': '1.00',
            'options': [
                {'letter': 'A', 'text': 'Opción A', 'is_correct': True},
                {'letter': 'B', 'text': 'Opción B', 'is_correct': False},
            ],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('stem', response.data)

    def test_question_api_requires_competency_and_supports_edit_and_deactivation(self):
        self.client.force_authenticate(self.admin)
        payload = {
            'category': self.category.pk,
            'competency': 'Interpretación y representación',
            'type': 'MULTIPLE',
            'stem': '¿Cuál opción representa el resultado?',
            'default_score': '2.50',
            'options': [
                {'letter': 'A', 'text': 'Primera opción', 'is_correct': False},
                {'letter': 'B', 'text': 'Segunda opción', 'is_correct': True},
            ],
        }
        created = self.client.post('/api/questions/', payload, format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data['competency'], 'Interpretación y representación')

        missing_competency = {**payload, 'stem': 'Pregunta sin competencia', 'competency': ''}
        invalid = self.client.post('/api/questions/', missing_competency, format='json')
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('competency', invalid.data)

        multiple_correct = {**payload, 'stem': 'Pregunta con dos respuestas correctas'}
        multiple_correct['options'] = [
            {'letter': 'A', 'text': 'Primera opción', 'is_correct': True},
            {'letter': 'B', 'text': 'Segunda opción', 'is_correct': True},
        ]
        invalid_options = self.client.post('/api/questions/', multiple_correct, format='json')
        self.assertEqual(invalid_options.status_code, 400)
        self.assertIn('exactamente una respuesta correcta', str(invalid_options.data))

        question_id = created.data['id']
        edited = self.client.patch(f'/api/questions/{question_id}/', {
            'stem': '¿Cuál opción muestra el resultado?',
        }, format='json')
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.data['stem'], '¿Cuál opción muestra el resultado?')

        deactivated = self.client.patch(f'/api/questions/{question_id}/', {'is_active': False}, format='json')
        self.assertEqual(deactivated.status_code, 200)
        self.assertFalse(deactivated.data['is_active'])

    def test_import_validator_rejects_duplicates_and_invalid_options(self):
        rows = [
            {'rowNumber': 2, 'values': {'categoria': 'Ciencias', 'competencia': 'Ciencias naturales', 'tipo': 'MULTIPLE', 'enunciado': 'Pregunta', 'puntaje_defecto': 1, 'opcion_a': 'A', 'opcion_b': 'B', 'correcta': 'A'}},
            {'rowNumber': 3, 'values': {'categoria': 'Ciencias', 'competencia': 'Ciencias naturales', 'tipo': 'MULTIPLE', 'enunciado': 'Pregunta', 'puntaje_defecto': 1, 'opcion_a': 'A', 'opcion_b': 'B', 'correcta': 'A'}},
            {'rowNumber': 4, 'values': {'categoria': 'Ciencias', 'competencia': 'Ciencias naturales', 'tipo': 'MULTIPLE', 'enunciado': 'Sin opción', 'puntaje_defecto': 1, 'opcion_a': 'A', 'opcion_b': '', 'correcta': 'B'}},
        ]
        valid, errors = validate_import_rows(rows)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(errors), 2)
        self.assertIn('Ya existe una pregunta con la misma categoría y enunciado.', errors[0]['errors'])

    def test_import_validator_requires_competency_and_score(self):
        rows = [{
            'rowNumber': 2,
            'values': {
                'categoria': 'Matemáticas',
                'competencia': '',
                'tipo': 'MULTIPLE',
                'enunciado': 'Pregunta de prueba',
                'puntaje_defecto': '',
                'opcion_a': 'Opción A',
                'opcion_b': 'Opción B',
                'correcta': 'A',
            },
        }]
        valid, errors = validate_import_rows(rows)
        self.assertEqual(valid, [])
        self.assertIn('La competencia es obligatoria.', errors[0]['errors'])
        self.assertIn('El puntaje es obligatorio.', errors[0]['errors'])

    def test_import_validator_rejects_invalid_score_and_correct_option(self):
        rows = [
            {
                'rowNumber': 2,
                'values': {
                    'categoria': 'Matemáticas',
                    'competencia': 'Razonamiento cuantitativo',
                    'tipo': 'MULTIPLE',
                    'enunciado': 'Puntaje no numérico',
                    'puntaje_defecto': 'mucho',
                    'opcion_a': 'A',
                    'opcion_b': 'B',
                    'correcta': 'A',
                },
            },
            {
                'rowNumber': 3,
                'values': {
                    'categoria': 'Español',
                    'competencia': 'Lectura crítica',
                    'tipo': 'MULTIPLE',
                    'enunciado': 'Respuesta sin opción',
                    'puntaje_defecto': '1',
                    'opcion_a': 'A',
                    'opcion_b': 'B',
                    'correcta': 'C',
                },
            },
        ]
        valid, errors = validate_import_rows(rows)
        self.assertEqual(valid, [])
        self.assertIn('El puntaje debe ser un número válido.', errors[0]['errors'])
        self.assertIn('La opción marcada como correcta no tiene texto.', errors[1]['errors'])

    def test_template_download_and_preview_validate_excel(self):
        self.client.force_authenticate(self.admin)
        template = self.client.get('/api/imports/template/')
        self.assertEqual(template.status_code, 200)
        self.assertIn('spreadsheetml', template['Content-Type'])
        downloaded_workbook = load_workbook(BytesIO(template.content), read_only=True)
        instructions = '\n'.join(
            str(cell)
            for row in downloaded_workbook['Instrucciones'].iter_rows(values_only=True)
            for cell in row
            if cell is not None
        )
        self.assertIn('materia o asignatura', instructions)
        self.assertIn('Matemáticas, Español', instructions)

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(['categoria', 'competencia', 'tipo', 'texto_base', 'enunciado', 'retroalimentacion', 'puntaje_defecto', 'opcion_a', 'opcion_b', 'opcion_c', 'opcion_d', 'correcta'])
        sheet.append(['Matemáticas', 'Razonamiento cuantitativo', 'MULTIPLE', '', 'Una pregunta de matemáticas', '', 1, 'Sí', 'No', '', '', 'A'])
        sheet.append(['Español', 'Lectura crítica', 'MULTIPLE', '', 'Una pregunta de español', '', 1, 'Opción A', 'Opción B', '', '', 'B'])
        buffer = BytesIO()
        workbook.save(buffer)
        upload = SimpleUploadedFile('preguntas.xlsx', buffer.getvalue())
        preview = self.client.post('/api/imports/preview/', {'file': upload}, format='multipart')
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data['valid'], 2)
        self.assertEqual(len(preview.data['rows']), 2)
        commit = self.client.post('/api/imports/commit/', {
            'file_name': 'preguntas.xlsx',
            'rows': preview.data['rows'],
        }, format='json')
        self.assertEqual(commit.status_code, 201)
        self.assertEqual(commit.data['successful'], 2)
        math_category = Category.objects.get(name='Matemáticas')
        spanish_category = Category.objects.get(name='Español')
        self.assertEqual(
            set(Question.objects.filter(stem__in=['Una pregunta de matemáticas', 'Una pregunta de español']).values_list('category__name', flat=True)),
            {'Matemáticas', 'Español'},
        )
        self.assertTrue(Question.objects.filter(stem='Una pregunta de matemáticas', category=math_category, competency='Razonamiento cuantitativo').exists())
        self.assertTrue(Question.objects.filter(stem='Una pregunta de español', category=spanish_category, competency='Lectura crítica').exists())
        history = self.client.get('/api/imports/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data[0]['file_name'], 'preguntas.xlsx')
        self.assertEqual(history.data[0]['imported_rows'], 2)

    def test_import_commit_does_not_save_invalid_rows(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/imports/commit/', {
            'file_name': 'invalid.xlsx',
            'rows': [{'rowNumber': 2, 'values': {'categoria': 'Ciencias', 'competencia': 'Ciencias naturales', 'tipo': 'MULTIPLE', 'enunciado': 'Inválida', 'puntaje_defecto': 1, 'opcion_a': 'A', 'correcta': 'A'}}],
        }, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Question.objects.filter(stem='Inválida').exists())
        history = self.client.get('/api/imports/')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.data[0]['file_name'], 'invalid.xlsx')
        self.assertEqual(history.data[0]['error_rows'], 1)
