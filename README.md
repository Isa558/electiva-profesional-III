# Simulador de Pruebas Saber TyT

Aplicación Django para administrar usuarios y roles, preguntas, cuestionarios y calificaciones. El acceso a la API usa JWT; las restricciones de rol se validan en el servidor.

## Requisitos y ejecución local

Requiere Python 3.10 o posterior, MariaDB en ejecución y las credenciales de la base de datos en `.env`. La configuración local actual usa la conexión existente de MariaDB.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

Abre `http://127.0.0.1:8000/` para iniciar sesión y `http://127.0.0.1:8000/admin/` para abrir Django Admin. El indicador de acceso confirma si MariaDB está disponible. Las migraciones crean los roles **Administrador**, **Estudiante** y **Docente** (este último como ejemplo configurable), agregan las tablas Django y copian el banco de preguntas y categorías existentes sin borrar las tablas originales. Después, crea tu cuenta administradora con `python manage.py createsuperuser`; desde la aplicación puedes crear cuentas, asignar roles y recorrer las pantallas de administración.

Para preparar las cuentas de demostración locales que aparecen en la pantalla de acceso, ejecuta `python manage.py setup_demo_accounts` mientras `DJANGO_DEBUG=true`. Este comando crea las cuentas `admin@sabertyt.edu.co`, `docente@sabertyt.edu.co` y `estudiante@sabertyt.edu.co`, todas con la contraseña `demostracion`. La pantalla solo muestra las credenciales cuando las tres cuentas activas existen con su rol y contraseña esperados. El comando se bloquea con `DJANGO_DEBUG=false`, y la API que publica estas credenciales de demostración también está deshabilitada fuera de modo debug. Puedes ocultarlas en desarrollo con `ENABLE_DEMO_ACCOUNTS=false`. No uses estas cuentas en producción.

Para preparar contenido local de sustentación después de crear las cuentas, ejecuta `python manage.py setup_demo_evaluation`. El comando agrega preguntas originales de Matemáticas y Español con competencias y opciones, completa la competencia de dos preguntas heredadas de Ciencias solo si está vacía, y crea un cuestionario activo disponible durante un año, con 30 minutos y tres intentos. Es repetible y no reemplaza preguntas o cuestionarios ya existentes; si encuentra un registro con el mismo identificador y contenido diferente, se detiene sin modificarlo. Inicia sesión con `estudiante@sabertyt.edu.co` para presentar la evaluación y generar una calificación mediante el flujo normal del sistema.

Para ampliar la demostración con cuestionarios independientes de Matemáticas, Español, Inglés, Naturales y Ciencias, ejecuta `python manage.py setup_full_demo` en modo local. El comando crea 20 preguntas adicionales y cinco simulacros nuevos sin reemplazar ni duplicar registros existentes.

La aplicación incluye paneles de administración por permiso para usuarios, roles, categorías, preguntas, importaciones, cuestionarios y resultados, además de las pantallas de evaluaciones, calificaciones y perfil para estudiantes. Los formularios de administración guardan los cambios en Django/MariaDB; la evaluación y el cálculo de calificación también se realizan en el servidor.

La base predeterminada es MariaDB (`DB_ENGINE=mysql`) y se configura en `.env`; no compartas ese archivo ni sus credenciales. Si deseas usar SQLite para una demostración aislada, establece `DB_ENGINE=sqlite` antes de migrar. Django crea sus tablas mediante `python manage.py migrate`; no es necesario crear un esquema SQL a mano. Configura `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` y `DJANGO_DEBUG=false` antes de publicar el servicio.

## Funcionalidades

- Autenticación JWT con tokens de acceso/renovación, cierre de sesión y bloqueo de cuentas inactivas.
- Roles configurables y permisos por operación. Los permisos se verifican en cada endpoint y en el panel de administración.
- Interfaz adaptable a móvil basada en el prototipo, con módulos que se muestran según el rol autenticado.
- Administración de usuarios, categorías, competencias, preguntas y cuestionarios. El contenido con intentos asociados se protege para conservar el historial de calificaciones.
- Plantilla Excel con hojas formateadas de carga e instrucciones, encabezados legibles, validaciones de tipo/respuesta y una fila de ejemplo que se debe eliminar antes de importar. Incluye la columna `categoria` para la materia (por ejemplo, Matemáticas o Español), competencia y puntaje obligatorios, vista previa de cada pregunta, validación previa en el servidor, creación o reutilización de categorías al importar, opción de vincular preguntas a un cuestionario autorizado antes de sus intentos e historial de importaciones.
- Disponibilidad de evaluaciones, tiempo límite validado por el servidor, intentos permitidos y calificaciones restringidas a la escala de 0,00 a 5,00.
- Metadatos de período académico y curso/grupo en cada cuestionario para filtrar resultados jerárquicamente.
- Consultas de resultados con filtros por año, período, curso/grupo, eje y estudiante; indicadores agregados, desempeño por eje, análisis de dificultad y paginación.
- Exportación protegida de informes `.xlsx` de consolidado (incluye resúmenes y preguntas difíciles), desempeño por eje e historial cronológico.
- Calificación automática en Django; la API del estudiante no incluye marcas de respuesta correcta y limita los intentos a su propietario.
- Edición de perfil y contraseña con validación de la contraseña actual; ajustes institucionales persistidos en la base de datos.

## API principal

Las rutas requieren `Authorization: Bearer <access>` salvo la obtención y renovación de tokens.

| Método y ruta | Uso |
| --- | --- |
| `POST /api/auth/token/` | Iniciar sesión con nombre de usuario o correo y contraseña |
| `GET /api/auth/demo-accounts/` | Credenciales de demostración locales, solo en modo debug y si las cuentas están preparadas |
| `POST /api/auth/token/refresh/` | Renovar el token |
| `POST /api/auth/logout/` | Revocar un token de renovación |
| `GET /api/auth/me/` | Consultar identidad, rol y permisos |
| `PATCH /api/auth/me/` | Actualizar los datos personales propios |
| `POST /api/auth/password/` | Cambiar la contraseña verificando la actual |
| `GET /api/health/` | Comprobar la conexión a la base de datos |
| `/api/users/`, `/api/roles/` | Administración con permisos `users.manage` y `roles.manage` |
| `GET /api/role-permissions/` | Catálogo de permisos para configurar roles |
| `/api/categories/`, `/api/questions/` | Banco de preguntas con `questions.manage` |
| `/api/quizzes/` | Configuración con `quizzes.manage` |
| `/api/settings/` | Configuración institucional con `settings.manage` |
| `GET /api/quizzes/available/` | Cuestionarios disponibles para el estudiante |
| `/api/quizzes/<id>/attempts/` | Iniciar un intento |
| `/api/attempts/<id>/answers/`, `/submit/` | Guardar respuestas y finalizar |
| `GET /api/attempts/` | Consultar resultados propios o autorizados |
| `GET /api/reportes/` | Consultar resultados, filtros disponibles, indicadores, análisis por eje y preguntas difíciles; acepta `year`, `period`, `group`, `axis`, `student`, `page` y `page_size` |
| `GET /api/reportes/export/<consolidated\|axes\|history>/` | Descargar informes `.xlsx` con los mismos filtros y el mismo alcance de permisos |
| `/api/imports/`, `/api/imports/template/`, `/preview/`, `/commit/` | Historial, plantilla y flujo de importación Excel |

## Swagger y esquema OpenAPI

- Documentación interactiva: `/api/docs/`
- Esquema OpenAPI: `/api/schema/`
- En Swagger, selecciona **Authorize**, inicia sesión con `POST /api/auth/token/` y usa el token JWT como `Bearer <access>`.
- Operaciones principales: `/api/simulacros/`, `/api/preguntas/`, `/api/intentos/`, `/api/resultados/`, `/api/reportes/?year=2026&period=2026-2&course=Sexto%20A&axis=Razonamiento&student=usuario`, y `PATCH /api/preguntas/<id>/`.

## Despliegue

El proyecto puede desplegarse en Render usando `render.yaml`; también puede utilizarse Vercel si el proveedor mantiene el controlador MySQL y las conexiones persistentes. Antes de desplegar, configura `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_DEBUG=false`, las variables `DB_*` de MariaDB/MySQL y `DB_SSL_CA` cuando el proveedor lo requiera. Ejecuta migraciones y `collectstatic` durante el despliegue.

Para crear un rol personalizado, usa `POST /api/roles/` con `name`, `slug`, `description` y una lista de permisos. Los permisos disponibles son `users.manage`, `roles.manage`, `questions.manage`, `quizzes.manage`, `results.view_all`, `results.view_assigned`, `quizzes.take`, `results.view_own` y `settings.manage`. Un rol docente puede usar `results.view_assigned` para consultar los intentos de sus propios cuestionarios sin ver los resultados de los demás.

## Pruebas

```powershell
python manage.py test evaluaciones
python manage.py check
npm test
```

El servidor activo es Django. Los archivos de Express y las pruebas JavaScript de importación que quedan en el repositorio corresponden a la implementación anterior.
