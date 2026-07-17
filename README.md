# Warhammer Fantasy Tools

Aplicación web para gestionar profesiones, habilidades, talentos y personajes del juego de rol **Warhammer Fantasy Roleplay (2ª edición)**. Permite importar profesiones desde PDFs del libro de reglas (incluyendo páginas escaneadas en inglés o español), buscar rutas de progresión entre profesiones y crear personajes.

---

## Tabla de contenidos

- [Características](#características)
- [Tecnologías](#tecnologías)
- [Instalación rápida con Docker](#instalación-rápida-con-docker)
- [Despliegue en NAS Synology (DSM)](#despliegue-en-nas-synology-dsm)
- [Instalación local para desarrollo](#instalación-local-para-desarrollo)
- [Configuración](#configuración)
- [Comandos de administración y mantenimiento](#comandos-de-administración-y-mantenimiento)
- [Tests automatizados](#tests-automatizados)
- [Guía de operación — Administrador](#guía-de-operación--administrador)
- [Guía de operación — Usuario](#guía-de-operación--usuario)
- [Modelo de datos](#modelo-de-datos)
- [Estructura del proyecto](#estructura-del-proyecto)

---

## Características

| Módulo | Descripción |
|---|---|
| **Profesiones** | Catálogo con todos los campos WFRP2: perfil primario y secundario, habilidades con especializaciones y grupos de elección, talentos, enseres, accesos y salidas |
| **Importación PDF** | Sube un PDF del libro (escaneado o digital), con OCR automático y traducción inglés → español |
| **Buscador de caminos** | Encuentra hasta 5 rutas entre dos profesiones mostrando características acumuladas, habilidades y enseres necesarios en cada paso; todos los pasos de una ruta pueden verse simultáneamente. Admite **puntos intermedios** obligatorios (p. ej. Sicario → Asesino → Tirador): cada tramo se busca reutilizando las salidas de **cualquier** profesión ya visitada en la ruta, no solo la parada inmediatamente anterior, y la interfaz marca cuándo un tramo continúa desde una parada anterior en vez de la última. Cada profesión del camino enlaza directamente a su ficha |
| **Habilidades y Talentos** | Catálogo completo con buscador avanzado (nombre / todos los campos); importación y exportación en texto, CSV y Excel; filtros por tipo (Básica / Avanzada) y por característica asociada; cada entrada muestra qué profesiones la otorgan. **Buscador con autocompletado** (menú Profesiones → Buscar por habilidad/talento) para saltar directo a esa ficha |
| **Personajes** | Creación rápida (manual) o mediante el **Generador de Personaje**: asistente con tiradas guiadas (raza, profesión, características, trasfondo completo) siguiendo las reglas caseras de creación de personajes jugadores. Carrera profesional con múltiples profesiones en orden |
| **Contactos** | Agenda de NPCs (crear/editar es admin-only) con datos globales (nombre, raza —desplegable guiado—, profesiones del catálogo, Untersuchung + grado con tiers Agente/Adjunto, estado, foto, visibilidad total/oculto) y datos por personaje (nivel de relación con etiqueta, tipo de relación, salario, notas privadas) sobre el **personaje activo** de cada usuario; importación/exportación Excel. Módulo integrado a partir del proyecto independiente [ContactosWH](https://github.com/jmsanesteban/ContactosWH) (ahora archivado, ver nota histórica en su README) |
| **Sistema de permisos** | Control granular por función: plantillas de permisos reutilizables + asignaciones directas por usuario; los administradores tienen acceso total |
| **Backup y recuperación** | Exportar/importar en JSON Profesiones, Usuarios, Equipamiento, Recetas propuestas, Recargo de precios, Personajes (incluido su inventario —equipo y comida/bebida—, historial de compras y dinero concedido) y Contactos+Vínculos (incluidas sus notas privadas), Plantillas de permisos y Sinónimos (además del "Backup completo" que hace las nueve a la vez); pensado para poder levantar una instancia nueva desde cero sin perder ningún dato real (salvo las contraseñas, que se regeneran forzando el cambio en el primer login) |
| **Comida y bebida** | Catálogo de bebidas por nación y de recetas (vigor/moral/coste/duración/complejidad), con **compra directa** vinculada a un personaje desde el propio menú (descuenta el dinero del banco y lo manda a su inventario, igual que el equipo); tablas de referencia de ingredientes y métodos de cocina; página de normas de intoxicación y de vigor/moral diario; cualquier usuario puede proponer una receta nueva (cálculo automático de sus valores), que queda pendiente hasta que un administrador la revisa y aprueba; un administrador puede activar un **recargo global (%)** sobre estas compras |
| **Equipamiento** | Catálogo de armas, armaduras, ropa, libros, otros objetos y objetos especiales, con menú propio por categoría además del catálogo completo; ficha de cada objeto con estadísticas (`stats`, las del libro) y campos adicionales (`custom_fields`, añadidos a mano) editables uno a uno o **en bloque** sobre un conjunto filtrado (añadir/renombrar/eliminar un campo a la vez en varios objetos); cada personaje tiene su propia **tienda** (carrito + checkout que descuenta dinero), **inventario** repartido en 5 ubicaciones de almacenaje, e **historial de compras** inmutable; un administrador puede además conceder objetos especiales directamente (sin pasar por caja) o añadir dinero a mano a la cuenta de un personaje (mientras no haya sueldos/recompensas automáticos) |
| **Modo oscuro / modo claro** | Selector de tema desde el menú de usuario (arriba a la derecha) — modo oscuro (el de siempre) o modo claro (fondo blanco/pergamino, texto oscuro), pensado para gente con problemas de visión o que prefiere trabajar sobre fondo claro. Preferencia guardada por navegador, sin recarga de página; toda la app cambia de color, incluida la barra de navegación — solo la banda de "entorno de preproducción" se queda fija para seguir destacando igual en ambos modos |

---

## Tecnologías

- **Backend:** Python 3.11 · Flask 3 · SQLAlchemy · Flask-Login
- **Base de datos:** MySQL 8
- **OCR:** Tesseract 5 (vía pytesseract) + pdf2image · PyMuPDF (PDFs digitales)
- **Traducción:** deep-translator (Google Translate) · langdetect
- **Pathfinding:** networkx (algoritmo de Yen vía `shortest_simple_paths`, con búsqueda multi-fuente para puntos intermedios)
- **Frontend:** Bootstrap 5 · Cinzel / Crimson Text (Google Fonts)
- **Importación/Exportación:** openpyxl (Excel), pandas (importación Excel de Contactos), csv estándar, formato texto propio
- **Infraestructura:** Docker · Docker Compose · Gunicorn

---

## Instalación rápida con Docker

### Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (incluye Docker Compose)
- Git

### Pasos

```bash
# 1. Clona el repositorio
git clone https://github.com/jmsanesteban/WarhammerFantasyTools.git
cd WarhammerFantasyTools

# 2. Copia y edita el fichero de entorno
cp .env.example .env
# Edita .env: cambia las contraseñas y la SECRET_KEY antes de usar en producción

# 3. Levanta la aplicación
docker-compose up --build
```

La primera vez tarda unos minutos mientras se construye la imagen y se descargan las dependencias del sistema (Tesseract, Poppler, etc.).

Una vez arrancado, abre **http://localhost:5000** en el navegador.

El usuario administrador se crea automáticamente con las credenciales definidas en `.env` (`ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`).

### Apagar y reiniciar

```bash
# Parar los contenedores (conserva los datos)
docker-compose down

# Volver a arrancar (sin reconstruir)
docker-compose up

# Parar y eliminar también los datos (base de datos)
docker-compose down -v
```

### Ver logs en tiempo real

```bash
docker-compose logs -f app
docker-compose logs -f db
```

---

## Despliegue en NAS Synology (DSM)

Requiere **DSM 7.2 o superior** con el paquete **Container Manager** (sustituyó al antiguo paquete "Docker" y añadió soporte nativo de proyectos `docker-compose`). Instálalo desde el **Centro de paquetes** si no lo tienes ya.

### 1. Subir el proyecto

1. Abre **File Station** y crea una carpeta para el proyecto, p.ej. `docker/wft` (dentro de un volumen compartido, no en la papelera de reciclaje ni en carpetas del sistema).
2. Sube el contenido del repositorio a esa carpeta (arrastra el ZIP descargado de GitHub y descomprímelo ahí, o usa SFTP/`git clone` si el NAS tiene acceso SSH con `git` instalado — ver más abajo). La carpeta debe contener `docker-compose.yml` en su raíz.
3. Copia `.env.example` a `.env` dentro de esa misma carpeta (con el editor de texto de File Station, o por SFTP) y cambia `SECRET_KEY` y las contraseñas antes de arrancar — igual que en la instalación estándar (ver [Configuración](#configuración)).

### 2. Crear el proyecto en Container Manager

1. Abre **Container Manager → Proyecto → Crear**.
2. Nombre del proyecto (p.ej. `wft`) y selecciona como **ruta** la carpeta creada en el paso anterior — Container Manager detecta automáticamente el `docker-compose.yml`.
3. Pulsa **Compilar** (equivale a `docker-compose up --build -d`). La primera vez tarda varios minutos mientras se construye la imagen.
4. Una vez arrancado, la app queda accesible en `http://<ip-del-nas>:5000`.

> **Colisión de puertos:** algunos paquetes de DSM u otros proyectos ya usan el puerto 5000. Si Container Manager avisa de un conflicto, edita el mapeo de puertos en `docker-compose.yml` (p.ej. `"5050:5000"`) antes de compilar, y accede por el puerto que hayas elegido.

### 3. Logs y gestión

Desde **Container Manager → Proyecto → (tu proyecto) → Contenedor**, cada contenedor (`wft_app`, `wft_db`) tiene su propia pestaña **Registro** con los logs en tiempo real — equivalente a `docker-compose logs -f` sin necesitar SSH.

### 4. Actualizar la aplicación

- **Si el NAS tiene acceso SSH con `git` instalado** (algunos modelos Synology lo traen, otros no): conecta por SSH, `cd` a la carpeta del proyecto, `git pull`, y luego pulsa **Compilar** de nuevo desde Container Manager (o `docker-compose up -d --build` por línea de comandos si prefieres seguir por SSH — ver [Actualizar la aplicación](#actualizar-la-aplicación-nueva-versión-del-código)).
- **Si no hay `git` en el NAS**: descarga el ZIP actualizado del repositorio, descomprímelo sustituyendo los ficheros en la carpeta del proyecto en File Station (sin tocar tu `.env` ni la carpeta `uploads/`), y pulsa **Detener** → **Compilar** desde Container Manager para reconstruir con el código nuevo.

### 5. Exponer la app a internet (opcional)

Para acceso remoto sin abrir puertos en el router, el mismo patrón que ya usa esta app en su propio despliegue (Cloudflare Tunnel vía `docker-compose.override.yml`, ver el modelo de datos/infra del proyecto) funciona igual en un NAS Synology — Cloudflare ofrece un paquete/contenedor `cloudflared` que se añade al mismo proyecto. Si no te hace falta acceso externo, con el puerto 5000 (o el que hayas mapeado) accesible en tu red local es suficiente.

---

## Instalación local para desarrollo

Para desarrollar sin Docker necesitas MySQL, Python 3.11+ y Tesseract instalados en tu máquina.

### 1. MySQL

Crea la base de datos y el usuario:

```sql
CREATE DATABASE wft CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'wftuser'@'localhost' IDENTIFIED BY 'wftpassword';
GRANT ALL PRIVILEGES ON wft.* TO 'wftuser'@'localhost';
FLUSH PRIVILEGES;
```

### 2. Tesseract OCR

**Windows:** Descarga el instalador desde [github.com/UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) e instala los paquetes de idioma `spa` y `eng`.

**Linux/macOS:**
```bash
sudo apt install tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng poppler-utils  # Debian/Ubuntu
brew install tesseract tesseract-lang poppler  # macOS
```

### 3. Entorno Python

```bash
# Crea y activa el entorno virtual
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

# Instala dependencias
pip install -r requirements.txt
```

### 4. Configuración

```bash
cp .env.example .env
```

Edita `.env` y cambia `DATABASE_URL` para apuntar a localhost:

```
DATABASE_URL=mysql+pymysql://wftuser:wftpassword@localhost:3306/wft
FLASK_ENV=development
```

### 5. Migraciones y arranque

```bash
# Inicializa las tablas y siembra datos iniciales (permisos, plantillas, sinónimos)
flask init-db

# Crea el usuario administrador
flask create-admin

# Arranca el servidor de desarrollo
flask run
```

La app estará en **http://localhost:5000**.

---

## Configuración

Todas las variables se definen en el fichero `.env` (copia de `.env.example`):

| Variable | Descripción | Por defecto |
|---|---|---|
| `SECRET_KEY` | Clave secreta de Flask (CSRF, sesiones). **Cambia en producción.** | `change-this-...` |
| `FLASK_ENV` | `development` activa el modo debug. En producción usa `production`. | `development` |
| `MYSQL_DATABASE` | Nombre de la base de datos | `wft` |
| `MYSQL_USER` | Usuario de MySQL | `wftuser` |
| `MYSQL_PASSWORD` | Contraseña del usuario MySQL | `wftpassword` |
| `MYSQL_ROOT_PASSWORD` | Contraseña root de MySQL (solo Docker) | `rootpassword` |
| `DATABASE_URL` | URL de conexión completa usada por Flask | `mysql+pymysql://...` |
| `ADMIN_USERNAME` | Nombre del usuario administrador inicial | `admin` |
| `ADMIN_EMAIL` | Email del administrador inicial | `admin@example.com` |
| `ADMIN_PASSWORD` | Contraseña del administrador inicial | `changeme123` |
| `UPLOAD_FOLDER` | Ruta donde se guardan PDFs e imágenes subidas | `/app/uploads` |
| `MAX_CONTENT_LENGTH` | Tamaño máximo de fichero en bytes | `104857600` (100 MB) |
| `URL_PREFIX` | Sirve la app bajo un prefijo (p.ej. `/wft`) en vez de en la raíz — para compartir un dominio con otras apps detrás de un mismo proxy/túnel. Vacío = raíz (por defecto en local y staging). | *(vacío)* |
| `APP_ENVIRONMENT` | Puramente visual: con el valor `prepro`, el navbar cambia de color y muestra una insignia "Entorno de preproducción" — para no confundir preproducción con producción a simple vista. Déjalo vacío en producción y en local. | *(vacío)* |

> **Importante:** En producción genera una `SECRET_KEY` larga y aleatoria:
> ```python
> python -c "import secrets; print(secrets.token_hex(32))"
> ```

---

## Comandos de administración y mantenimiento

Los comandos de Docker funcionan igual en Windows y Linux. En Windows se ejecutan en **PowerShell** (o CMD); en Linux/macOS en cualquier terminal. Las únicas diferencias son las rutas de fichero y algunos comandos de utilidad del sistema operativo.

> Los nombres de los contenedores son `wft_app` (aplicación) y `wft_db` (MySQL). Si los cambiaste en `docker-compose.yml`, ajusta los comandos en consecuencia.

---

### Ciclo de vida de los contenedores

| Acción | Comando |
|---|---|
| Arrancar (sin reconstruir) | `docker-compose up -d` |
| Arrancar con reconstrucción de imagen | `docker-compose up --build -d` |
| Parar (sin borrar datos) | `docker-compose down` |
| Parar y borrar volúmenes (⚠️ borra la BD) | `docker-compose down -v` |
| Reiniciar solo la app | `docker-compose restart app` |
| Reconstruir y reiniciar solo la app | `docker-compose up --build -d app` |
| Ver estado de los contenedores | `docker-compose ps` |

> ⚠️ **Tras un `git pull` con cambios de código, `restart` no basta.** La imagen se construye en el build (`build: .`, sin bind-mount del código fuente), así que un `restart` simplemente reinicia el contenedor con la imagen **vieja**. Hace falta `docker compose up -d --build app` para que el código nuevo llegue al contenedor.

---

### Logs

#### Windows — PowerShell

```powershell
# Logs en tiempo real de toda la pila
docker-compose logs -f

# Solo la aplicación
docker-compose logs -f app

# Solo la base de datos
docker-compose logs -f db

# Últimas 100 líneas de la aplicación
docker-compose logs --tail=100 app

# Buscar errores en los logs de la app (requiere Select-String)
docker-compose logs app 2>&1 | Select-String "ERROR", "Exception", "Traceback"
```

#### Linux / macOS

```bash
# Logs en tiempo real de toda la pila
docker-compose logs -f

# Solo la aplicación
docker-compose logs -f app

# Solo la base de datos
docker-compose logs -f db

# Últimas 100 líneas de la aplicación
docker-compose logs --tail=100 app

# Buscar errores en los logs de la app
docker-compose logs app 2>&1 | grep -E "ERROR|Exception|Traceback"
```

---

### Comandos Flask (init, admin, shell)

Todos se ejecutan dentro del contenedor de la app con `docker exec`.

#### Windows — PowerShell

```powershell
# Crear / migrar tablas de base de datos (ejecutar tras cada actualización del código)
# También siembra permisos, plantillas y sinónimos por defecto (idempotente)
docker exec wft_app flask init-db

# Crear el usuario administrador (usa las variables ADMIN_* del .env)
docker exec wft_app flask create-admin

# Abrir una shell interactiva de Python con el contexto de la app
docker exec -it wft_app flask shell

# Abrir una shell Bash dentro del contenedor
docker exec -it wft_app bash
```

#### Linux / macOS

```bash
# Crear / migrar tablas de base de datos
docker exec wft_app flask init-db

# Crear el usuario administrador
docker exec wft_app flask create-admin

# Shell interactiva de Python con contexto de la app
docker exec -it wft_app flask shell

# Shell Bash dentro del contenedor
docker exec -it wft_app bash
```

---

### Acceso a la base de datos MySQL

#### Windows — PowerShell

```powershell
# Abrir el cliente MySQL interactivo en el contenedor de BD
# (te pedirá la contraseña definida en .env → MYSQL_PASSWORD)
docker exec -it wft_db mysql -u wftuser -p wft

# Con contraseña directa (sin prompt; sustituye 'wftpassword' por la real)
docker exec -it wft_db mysql -u wftuser -pwftpassword wft

# Ejecutar una consulta SQL de una sola línea
docker exec wft_db mysql -u wftuser -pwftpassword wft -e "SELECT COUNT(*) FROM professions;"
```

#### Linux / macOS

```bash
# Abrir el cliente MySQL interactivo
docker exec -it wft_db mysql -u wftuser -p wft

# Ejecutar una consulta SQL de una sola línea
docker exec wft_db mysql -u wftuser -pwftpassword wft -e "SELECT COUNT(*) FROM professions;"
```

---

### Copias de seguridad de la base de datos

#### Windows — PowerShell

```powershell
# Exportar la BD completa a un fichero SQL con fecha en el nombre
$fecha = Get-Date -Format "yyyyMMdd_HHmm"
docker exec wft_db mysqldump -u wftuser -pwftpassword wft | Out-File -Encoding utf8 "backup_$fecha.sql"

# Restaurar desde un fichero SQL
Get-Content "backup_20240101_1200.sql" | docker exec -i wft_db mysql -u wftuser -pwftpassword wft
```

#### Linux / macOS

```bash
# Exportar la BD completa a un fichero SQL con fecha en el nombre
docker exec wft_db mysqldump -u wftuser -pwftpassword wft > "backup_$(date +%Y%m%d_%H%M).sql"

# Restaurar desde un fichero SQL
docker exec -i wft_db mysql -u wftuser -pwftpassword wft < backup_20240101_1200.sql
```

> **Alternativa por secciones (JSON):** `mysqldump` es la copia de seguridad completa de la base de datos, pero
> requiere acceso al servidor MySQL. Para un backup más ligero, portable entre bases de datos, y accesible desde
> la propia web (sin tocar el servidor), usa **Exportar/Importar** en Profesiones, Usuarios, Personajes,
> Plantillas de permisos, Sinónimos y Vínculos — ver [Backup y recuperación](#backup-y-recuperación) más abajo.
> Especialmente recomendable para **Profesiones**: reconstruir el catálogo a mano desde el PDF es un trabajo
> manual de horas, mientras que el JSON exportado se reimporta en segundos.

---

### Gestión de ficheros subidos (PDFs e imágenes)

Los uploads se almacenan en el volumen Docker `uploads`. Para acceder a ellos:

> **Nota:** la caché de revisión de PDFs (resultados de OCR pendientes de guardar, 48h de vida) vive en un volumen Docker **separado** (`pdf_cache`, montado en `/app/pdf_cache`) — deliberadamente fuera de `uploads`, que se sirve públicamente sin autenticación vía `/uploads/<fichero>`.

#### Windows — PowerShell

```powershell
# Copiar todos los uploads a una carpeta local
docker cp wft_app:/app/uploads ./uploads_backup

# Copiar una carpeta local de vuelta al contenedor
docker cp ./uploads_backup/. wft_app:/app/uploads/

# Ver qué hay en la carpeta de uploads
docker exec wft_app ls -lh /app/uploads/
```

#### Linux / macOS

```bash
# Copiar todos los uploads a una carpeta local
docker cp wft_app:/app/uploads ./uploads_backup

# Copiar una carpeta local de vuelta al contenedor
docker cp ./uploads_backup/. wft_app:/app/uploads/

# Ver qué hay en la carpeta de uploads
docker exec wft_app ls -lh /app/uploads/
```

---

### Actualizar la aplicación (nueva versión del código)

#### Windows — PowerShell

```powershell
# 1. Obtener los cambios del repositorio
git pull

# 2. Reconstruir la imagen e iniciar
docker-compose up --build -d

# 3. Aplicar migraciones de base de datos si las hay
docker exec wft_app flask init-db
```

#### Linux / macOS

```bash
# 1. Obtener los cambios del repositorio
git pull

# 2. Reconstruir la imagen e iniciar
docker-compose up --build -d

# 3. Aplicar migraciones de base de datos si las hay
docker exec wft_app flask init-db
```

---

### Diagnóstico rápido

#### Windows — PowerShell

```powershell
# Estado general de los contenedores
docker-compose ps

# Uso de recursos (CPU, memoria, red) en tiempo real
docker stats wft_app wft_db

# Inspeccionar variables de entorno cargadas en el contenedor
docker exec wft_app env | Select-String "FLASK|MYSQL|ADMIN"

# Ver el espacio ocupado por los volúmenes Docker
docker system df

# Limpiar imágenes y capas no utilizadas (libera espacio en disco)
docker image prune -f
```

#### Linux / macOS

```bash
# Estado general de los contenedores
docker-compose ps

# Uso de recursos en tiempo real
docker stats wft_app wft_db

# Inspeccionar variables de entorno cargadas en el contenedor
docker exec wft_app env | grep -E "FLASK|MYSQL|ADMIN"

# Ver el espacio ocupado por los volúmenes Docker
docker system df

# Limpiar imágenes y capas no utilizadas
docker image prune -f
```

---

### Referencia rápida de comandos Flask CLI

| Comando | Descripción |
|---|---|
| `flask init-db` | Crea todas las tablas, aplica migraciones incrementales de columnas y siembra permisos, plantillas y sinónimos por defecto. Seguro de ejecutar múltiples veces. |
| `flask create-admin` | Crea el usuario administrador definido en las variables `ADMIN_*` del `.env`. Si ya existe, no hace nada. |
| `flask shell` | Abre una shell Python con la app cargada. Útil para consultas y depuración ad-hoc. |
| `flask db migrate` | (Modo desarrollo) Genera una migración Alembic a partir de los cambios en los modelos. |
| `flask db upgrade` | (Modo desarrollo) Aplica las migraciones Alembic pendientes. |

---

## Tests automatizados

Suite de tests unitarios y de integración con **pytest**, ejecutada contra una base de datos **SQLite en memoria** (no hace falta un servidor MySQL para correrla) y el test client de Flask. Cubre permisos, autenticación, profesiones, habilidades/talentos, personajes WFRP, contactos (incluida la parte de administración), comida y bebida, el backup/restauración por secciones, el buscador de caminos, y — con especial atención, por ser el área con más incidencias reales en producción — todo el pipeline de importación de PDF.

### Ejecutar los tests

```bash
# Instalar dependencias de test (además de las de requirements.txt)
pip install -r requirements-dev.txt

# Ejecutar toda la suite
pytest

# Con detalle por test
pytest -v

# Solo un fichero
pytest tests/test_pdf_import.py -v

# Con cobertura
pytest --cov=app --cov-report=term-missing
```

### Estructura

| Fichero | Cubre |
|---|---|
| `tests/conftest.py` | Fixtures compartidas: app Flask en modo `testing`, sesión de BD, cliente de test, factories de modelos (`make_user`, `make_profession`, `make_skill`, `make_talent`, `make_character`, `make_contact*`) y helper de login |
| `tests/test_permissions.py` | `User.has_perm()` / `effective_perm_codes()` (bypass de admin, permisos directos, plantillas) y los decoradores `require_permission` / `admin_required` |
| `tests/test_auth.py` | Login, registro, logout, redirección a `next`, usuarios inactivos, cambio de contraseña propio, y el bloqueo de `must_change_password` (redirige a cualquier página salvo logout hasta completarlo) |
| `tests/test_admin_users.py` | Gestión admin de contraseñas: restablecer a una aleatoria, forzar cambio sin tocar la contraseña, y establecer una contraseña concreta (con validación de longitud/confirmación) |
| `tests/test_professions.py` | CRUD de profesiones, permisos, características primarias/secundarias, habilidades/talentos/enseres/salidas asociados, y el export/import JSON (permiso `professions.edit`, formato con habilidades/talentos anidados) |
| `tests/test_backup_service.py` | `app/services/backup_service.py`: round-trip export→borrar→reimportar de cada sección (Plantillas de permisos, Sinónimos, Usuarios, Profesiones con habilidades/talentos/enseres/salidas, Equipamiento incluido el emparejamiento por nombre+categoría+subcategoría+calidad y el objeto base de un especial, Recetas con método/ingredientes/condimentos por nombre, Recargo de precios (fila única), Personajes con las 7 tablas hijas más grado(s)/mochila-saco de la Untersuchung, inventario y historial de compras (incluida comida/bebida, emparejada por nombre de bebida+origen o nombre de receta) y dinero concedido, Contactos+Vínculos con salarios/visibilidad/estado-paradero/quién lo creó/notas privadas) y del Backup completo; modo `update` no duplica; una referencia inexistente (usuario/profesión/habilidad/talento/objeto base/objeto de inventario/ingrediente/bebida/receta) se omite con aviso en vez de fallar; el export de Usuarios nunca incluye la contraseña y el import nunca la toca al actualizar; un backup antiguo que aún tenga el booleano `vivo` (antes de que se separara en estado/paradero) se sigue importando correctamente; las cinco secciones con foto propia (Profesiones, Equipamiento, Recetas, Contactos, Personajes) exportan también los bytes de la imagen en base64 y los reescriben en `uploads/` al importar, y un backup sin ese campo (o una fila sin foto) no intenta escribir nada |
| `tests/test_admin_backup.py` | Rutas de backup en `/admin/*`: todas exigen admin (salvo Profesiones, que exige `professions.edit` y se cubre en `test_professions.py`), descarga JSON válido, importación end-to-end repuebla los datos tras borrarlos; Backup completo **selectivo**: exportar solo unas secciones marcadas deja el resto fuera del JSON y `secciones` refleja exactamente lo incluido; dos exportaciones en el mismo segundo nunca se pisan el nombre de fichero; cada exportación queda guardada en `BACKUP_FOLDER` y aparece listada en la página (con su recuento de registros por sección embebido para el panel de detalle); descargar un backup guardado funciona y rechaza un `filename` con `../` (path traversal); comprimir/descomprimir dejan el backup igual de legible/descargable/re-importable (se (des)comprime al vuelo), comprimir dos veces no hace nada, descomprimir uno no comprimido tampoco; comprimir/descomprimir varios de golpe transforma cada uno en su propio fichero y omite los que no correspondan (ya comprimidos / ya sin comprimir); eliminar borra el fichero y también rechaza path traversal; la **nota** de un backup se guarda dentro del propio fichero (no en un índice aparte), se puede borrar dejándola en blanco, y sobrevive intacta a comprimir/descomprimir; **restaurar** un backup guardado en el servidor (sin descargarlo/resubirlo) funciona en modo Omitir y Actualizar, funciona sobre un fichero comprimido (descomprime al vuelo) y rechaza path traversal; la tarjeta de Comida y bebida del panel enlaza directo a Exportar/Importar |
| `tests/test_skills_talents.py` | CRUD de habilidades y talentos, búsqueda/filtros, buscador con autocompletado (páginas `/habilidades/buscar` y `/talentos/buscar`), importación/exportación en texto plano, y el guardián anti-duplicados (bloquea duplicados exactos, avisa de casi-duplicados) al crear/editar/importar |
| `tests/test_theme_toggle.py` | Selector de tema oscuro/claro: el script anti-parpadeo del `<head>` está presente en cualquier página (incluso sin login), los dos botones "Modo oscuro"/"Modo claro" aparecen en el menú de usuario solo si hay sesión iniciada |
| `tests/test_characters.py` | CRUD de personajes WFRP, aislamiento por propietario (admin ve todos, jugador solo los suyos), historial de profesiones ordenado, `es_untersuchung`, salario por profesión, subida de foto en creación/edición (se guarda en `uploads/personajes/`, editar sin subir nueva imagen conserva la existente), la ficha muestra la foto o un icono de marcador de posición, y el listado solo muestra la miniatura (con el mismo zoom al pasar el ratón y clic para ampliar en grande que ya tienen las fotos de recetas/equipamiento) en las tarjetas de personajes que sí tienen foto |
| `tests/test_contacts.py` | Vista de usuario de Contactos: permiso de visibilidad por personaje (sin concesión no se ve, total/parcial oculta profesiones), concesión automática al crear, alta de contacto + vínculo propio, aislamiento de notas/nivel entre personajes (incluso del mismo usuario), visibilidad de Untersuchung según membresía, salario, insignias de Estado (Muerto/Corrompido) y Paradero (solo si Vivo) en listado y ficha |
| `tests/test_admin_contacts.py` | Administración de Contactos: listado/alta/baja, edición de datos globales (incluidos estado/paradero — el servidor limpia el paradero si el estado deja de ser Vivo, aunque se publique en la petición), que el creador de un contacto (no solo un admin) puede editar sus datos globales pero no el interruptor Visible, concesión/revocación de visibilidad por personaje, edición del vínculo de cualquier personaje, importación/exportación Excel con columnas fijas, y el directorio de Vínculos (usuario propietario visible, búsqueda) |
| `tests/test_pdf_import.py` | Pipeline de importación de PDF: emparejamiento de habilidades/talentos, canonicalización de chips al nombre exacto del catálogo, auto-vinculación de accesos/salidas, detección de duplicados/casi-duplicados, persistencia del caché de trabajos en disco (con expiración a las 48h), recuperación de enseres mal clasificados como talentos, corrección de nombres de carrera vía sinónimos, y el endpoint de guardado (modos crear/actualizar/omitir + el guardián anti-duplicados). Incluye tests de regresión explícitos para los bugs reales corregidos: pérdida de chips confirmados al guardar, caché no persistente entre reinicios, accesos/salidas no auto-vinculados, enseres perdidos dentro de talentos, nombres de carrera no corregidos por el diccionario de sinónimos, y habilidades/talentos casi-duplicados (p.ej. "preparar veneno" vs "Preparar venenos") |
| `tests/test_pathfinder.py` | Construcción del grafo de carreras, búsqueda de rutas (más cortas primero, límite de resultados, ausencia de ruta), búsqueda con puntos intermedios obligatorios (incluyendo la reutilización de una salida de una parada anterior cuando la última parada es un callejón sin salida), y acumulación de estadísticas (máximo por característica, deduplicación de habilidades/talentos/enseres a lo largo de la ruta) |
| `tests/test_talent_specializations.py` | Talentos con especializaciones predefinidas (p.ej. "Especialista en armas"): carga de `talent_specializations.json`, guardado en formato de entradas (JSON) con grupos de elección, y que los talentos sin especializaciones predefinidas siguen funcionando con el campo de texto libre de siempre |
| `tests/test_character_creation_service.py` | Servicio de tiradas del generador de personajes: parseo de fórmulas de dados, barrido completo 1-100 de cada tabla porcentual para las 5 razas (detecta huecos en los datos), agrupación de razas (Elfo Silvano/Alto Elfo comparten tablas de características/altura/peso/edad), y cada función `roll_*` individual |
| `tests/test_character_generator_routes.py` | Rutas del asistente de creación guiada: página del generador, endpoint de tirada por AJAX (`/generador/tirar`) para cada paso, y el guardado final (ficha completa con características, trasfondo, rasgos, contactos, posesiones y objetos mágicos) |
| `tests/test_wsgi_prefix.py` | `PrefixMiddleware` (servir la app bajo `URL_PREFIX`, p.ej. `/wft`): recorte de prefijo + `SCRIPT_NAME`, tolerancia con peticiones sin prefijo, y generación de URLs correctas de extremo a extremo con `url_for()` |
| `tests/test_food.py` | Comida y bebida: siembra idempotente del catálogo (`seed_food_catalog`, incluido el backfill de `complejidad` en filas ya sembradas antes de que existiera esa columna), conversión/formateo de moneda (`currency_service`), listado/filtro (incluidos sabor/calidad/disponibilidad) y ordenación por columna (incluidos los costes) de bebidas/recetas, la división de `sabor` en categoría base + variante, ficha de bebida (calculadora de precio, notas) y de receta (ingredientes/condimentos, recetas "solo compra"), páginas de referencia de ingredientes/métodos de cocina, el servicio de cálculo automático de una receta (`recipe_calc_service`, con "Olla podrida" como caso de regresión exacto contra el libro incluida la `calidad` derivada, los umbrales de `calidad_from_complejidad`, y el rechazo de combinaciones incompatibles o con demasiados ingredientes/condimentos), el flujo de propuesta de receta nueva (queda pendiente, oculta del catálogo público y de otros usuarios, visible en "Mis recetas"), y que todas las rutas exigen login |
| `tests/test_admin_recipes.py` | Revisión admin de recetas propuestas: acceso restringido a administradores, aprobar exige subir una imagen si no la tenía, aprobar publica la receta en el catálogo con la etiqueta "Comunidad" y registra quién/cuándo, rechazar guarda el motivo y el proponente lo ve en "Mis recetas", eliminar borra la receta y su imagen (incluida una ya rechazada, que no aparece en "Recetas pendientes"), y el botón de eliminar solo es visible para administradores en la ficha de la receta |
| `tests/test_equipment.py` | Catálogo de Equipamiento: listado/filtros (categoría, subcategoría, calidad, búsqueda) y sus menús por categoría (cabecera con el mismo icono y el mismo nombre en plural que su entrada del desplegable Equipamiento del navbar — antes se veía siempre el mismo icono de escudo y el nombre en singular, sin importar la categoría), ficha, permisos de creación/edición/eliminación (`equipment.edit`), subida de imagen restringida a arma/armadura, `stats`/`custom_fields` uno a uno, edición de campos en bloque (añadir/renombrar/eliminar sobre un conjunto filtrado, respeta filtros y permiso), export/import JSON (`equipment.import`) con el enlace al objeto base de un especial |
| `tests/test_equipment_book_order.py` | Comando `flask set-equipment-book-order`: dry-run no escribe nada, `--apply` rellena `orden` emparejando Arma/Armadura por (nombre, subcategoría) exactos contra `app/data/equipment_orden.py` (desambigua nombres repetidos como "Daga" cuerpo a cuerpo vs. distancia), Ropa lo calcula de (rango de subcategoría, rango de calidad) sin necesitar nombre, deja `orden=None` en lo que no empareja, es idempotente, y el listado (`/equipamiento/armas`) ordena por `orden` antes que por nombre, con fallback alfabético si no está asignado |
| `tests/test_character_purchases.py` | Tienda/carrito/inventario/historial de un personaje: añadir al carrito con calidad/cantidad/ubicación, filtros de la tienda (categoría/subcategoría/calidad, acotados a Arma/Armadura/Ropa), cálculo de precio por calidad (multiplicador ×0,5/×1/×3/×10) y por nivel social (Ropa Noble), checkout todo-o-nada (aborta sin cobrar si una línea no tiene precio calculable o falta dinero), reparto del inventario en las 5 ubicaciones, historial inmutable, la concesión de objetos especiales por un administrador (precio libre, incluido 0), y conceder dinero a mano (solo admin, suma al saldo y queda registrado en el historial) |
| `tests/test_character_inventory.py` | Mover equipo entre ubicaciones del inventario (stack completo, cantidad parcial, mover varios a la vez, fusión con una pila ya existente en el destino) y las reglas de carga de "El Imperio y sus viajes" (`encumbrance_service`: umbrales Fuerza/Fuerza+Resistencia/2×(Fuerza+Resistencia), el bonus +20 del talento Robusto, que solo Equipamiento+Mochila/saco cuentan como peso llevado, el peso unidad/total por línea, el código de color por nivel de carga, y el límite físico independiente de Mochila (50U) / Saco (80U)) |
| `tests/test_untersuchung_grados.py` | `app/models/untersuchung.py` (compartido entre Contactos y Personajes): tope de 3 grados (`clamp_grados`, preservando duplicados a propósito), qué grados cuentan como "con marca" (`has_marca` — Bazas/Contactos nunca cuentan), la imagen de marca de cada uno, `grados_display` (colapsa duplicados en "Gato x2"); que elegir un grado "con marca" marca automáticamente `es_untersuchung=True` en Contacto y en Personaje, que uno "sin marca" no lo hace, que se puede asignar el mismo grado a dos de las 3 marcas (doble marca), y que el tope de 3 slots se respeta en el servidor |
| `tests/test_admin_synonyms.py` | Diccionario de sinónimos: crear/editar/eliminar, y la regresión de un bug real donde el botón "Editar" dejaba de funcionar en cuanto un término contenía una comilla (los valores viajan por atributos `data-*`, no incrustados con `\|tojson` dentro de un `onclick="..."`) |
| `tests/test_food_purchases.py` | Compra directa de bebida/receta vinculada a un personaje: descuenta el dinero y crea el inventario (`drink_id`/`recipe_id`, sin `equipment_item_id`) y el historial de compras (`category_snapshot` bebida/comida); rechaza sin cobrar nada si falta dinero o si la receta no tiene precio de compra; solo el dueño del personaje (o un admin, para cualquiera) puede comprar; el recargo global de `ShopMarkup` se aplica al precio cobrado (nunca al enviado por el cliente); la página admin de Recargo de precios exige admin y persiste el %; inventario/historial enlazan de vuelta a la bebida/receta comprada; el peso de comida (0,5U por ración) y de bebida (según su recipiente — Botella/Pinta/Chupito) se calcula en `encumbrance_service.unit_weight`/`item_weight` y una compra real lo refleja en el inventario del personaje |
| `tests/test_admin_food.py` | Sección admin "Comida y bebida": Exportar/Importar Recetas exige admin; `food_pdf_service.parse_recetas_pdf` (construyendo un PDF sintético con PyMuPDF en el propio test, no depende del PDF real) extrae correctamente un bloque de receta normal (con su foto incrustada) y uno especial (método/calidad `*`, solo compra), resolviendo método/ingrediente/condimento por nombre tolerando acentos (el PDF real tiene alguna errata, p.ej. "Almibar" sin tilde); detecta recetas ya existentes en el catálogo y no las ofrece para importar; el POST de confirmación crea la receta + guarda la foto y vuelve a comprobar duplicados por si la pantalla de revisión quedó desactualizada; `sync_recipe_images_from_folder` solo enlaza recetas sin foto, nunca sobrescribe una ya asignada, y reporta los ficheros sin receta correspondiente |

### Notas de diseño

- Cada test corre con una base de datos SQLite en memoria completamente aislada (`db.create_all()` / `drop_all()` por test), así que no hay estado compartido entre tests.
- CSRF está desactivado en `TestingConfig` para simplificar los POSTs de test; los tests que necesitan verificar el comportamiento de CSRF lo reactivan explícitamente.
- `PDF_CACHE_DIR` se redirige a un directorio temporal del sistema durante los tests (ver `tests/conftest.py`), para no escribir en la ruta de producción (`/app/pdf_cache`).

---

## Guía de operación — Administrador

### Acceso al panel de administración

Inicia sesión con las credenciales de administrador y accede desde el menú **Admin → Panel**. El menú desplegable "Admin" del navbar tiene los accesos directos más habituales; el **Panel** en sí es el punto central que reúne *todo* lo administrable de la aplicación (estadísticas + una tarjeta por área: habilidades, talentos, importar PDF, profesiones, usuarios, contactos, vínculos, personajes, plantillas de permisos, diccionario de sinónimos, comida y bebida), para no depender de recordar en qué desplegable vive cada cosa. **Cada tarjeta incluye Exportar e Importar cuando esa sección los tiene** (aunque también vivan en el menú propio de esa sección) — nada obliga a salir del Panel para hacer un backup puntual de algo.

#### Vínculos (`/contactos/vinculos`)

Ya no es admin-only (ver [Gestionar Contactos](#gestionar-contactos)) — para un administrador muestra siempre **todas** las relaciones contacto↔personaje: contacto, personaje, tipo de relación, nivel de relación y número de notas (recuento, no contenido). Busca por nombre de contacto o de personaje. Desde cada fila: **Ver ficha** abre la ficha del contacto ya filtrada como ese personaje concreto (ahí están el vínculo completo y las notas).

#### Comida y bebida (`/admin/comida`)

- **Ingredientes** (`/admin/comida/ingredientes`) — CRUD completo del catálogo de ingredientes: nombre, vigor,
  moral, coste por docena de raciones, descripción, y la compatibilidad (Sí/No/Condimento) con cada uno de los
  métodos de cocina, editable desde un formulario con una fila por método. Eliminar un ingrediente que esté en
  uso en alguna receta (como ingrediente o condimento) está bloqueado — hay que quitarlo de la receta primero.
  A diferencia de bebidas y métodos de cocina (que siguen siendo un catálogo cerrado, sembrado solo desde
  `app/data/food/*.json` al arrancar), los ingredientes ya se gestionan en caliente desde aquí; el fichero de
  semilla solo se usa para el arranque inicial de una base de datos vacía, y nunca sobrescribe ediciones
  posteriores.
- **Exportar/Importar Recetas** — igual que el resto de catálogos (también viaja dentro del Backup completo).
- **Importar PDF de recetas hechas** — sube un PDF con el mismo formato que "Recetas hechas" del libro (una
  receta por bloque: Vigor/Moral/Método/Duración/Calidad/Ingredientes/Condimentos/Costes, con una foto
  incrustada por receta). Se parsea al momento con **PyMuPDF** (sin OCR — el texto ya es digital) y muestra una
  **pantalla de revisión** con la miniatura de cada foto antes de guardar nada — las recetas que ya existen en
  el catálogo se detectan por nombre y se omiten automáticamente, mostrando solo las nuevas con una casilla de
  selección. La foto de cada receta se empareja con su bloque de texto por orden dentro de la página del PDF —
  de ahí la revisión visual, para detectar a simple vista si algún emparejamiento fuese incorrecto antes de
  confirmar.
- **Sincronizar fotos** — para fotos sueltas: sube el fichero a mano a `uploads/imagenes_comidas/` con el
  nombre exacto de la receta (p.ej. `Olla podrida.jpg`) y pulsa "Sincronizar fotos" para vincularlas. Solo
  rellena recetas que **todavía no tienen foto** — nunca sobrescribe una ya asignada; para reemplazar una foto
  existente hay que quitarla primero (editando la receta) o hacerlo a mano.

---

### Importar profesiones desde un PDF

Esta es la forma principal de cargar datos masivos desde el libro de reglas.

> **Importante:** Antes de importar un PDF, asegúrate de tener el catálogo de habilidades y talentos cargado. El sistema valida automáticamente las habilidades y talentos extraídos contra la base de datos.

> **Límite de tamaño:** 100 MB por archivo (`MAX_CONTENT_LENGTH`). Si subes un PDF más grande, la pantalla muestra un error indicando el tamaño real del archivo y el límite — no hace falta comprimir "por si acaso", el mensaje es explícito.

1. Ve a **Admin → Subir PDF**.
2. Selecciona el archivo PDF y pulsa **Procesar PDF**.
3. El sistema ejecuta la siguiente pipeline automáticamente:
   - Extrae el texto de cada página con **PyMuPDF** (PDFs digitales).
   - Si una página tiene poco texto (página escaneada), la convierte a imagen y ejecuta **OCR** con Tesseract.
   - Detecta el idioma; si es **inglés**, traduce al español automáticamente (nombre original preservado en el campo EN).
   - Corrige nombres con letras separadas por el OCR (p.ej. `A Nimal T Rainer` → `Animal Trainer`).
   - Analiza el texto buscando bloques de profesión (nombre en mayúsculas, tablas de perfil, secciones de habilidades, etc.).
4. Se muestra la pantalla de **revisión**, con un **resumen de triaje** arriba del todo, dividido en dos tablas colapsables: **"Ya registradas"** (coinciden exactamente con una profesión ya guardada — colapsada por defecto, no suele hacer falta revisarlas) y **"No registradas"** (nuevas o con posible colisión de nombre — típico de erratas de OCR/traducción, desplegada por defecto ya que son las que necesitan atención). El nombre de cada fila es un **enlace directo** a su tarjeta de edición más abajo en la página. Debajo, una tarjeta por cada profesión con los campos pre-rellenados y chips de colores para habilidades y talentos: **verde** = encontrado en la BD, **naranja** = sin coincidencia, **azul** = aceptado manualmente (la leyenda de colores está justo encima del resumen).
5. Se muestran advertencias si la profesión no tiene salidas, o tiene habilidades/talentos sin correspondencia en la BD. La advertencia de "sin accesos" solo aparece en profesiones **avanzadas** (las básicas normalmente no tienen acceso, al ser carreras iniciales).
6. **Revisa y corrige** los datos de cada profesión. Presta especial atención a las características numéricas y los chips naranja.
7. Pulsa **Guardar esta profesión** en cada tarjeta que quieras importar.

> **Salidas y accesos:** el sistema intenta enlazarlos automáticamente comparando el texto extraído contra los nombres de profesiones ya existentes (coincidencia difusa, tolera pequeñas erratas), aplicando primero el diccionario de sinónimos por si el nombre de carrera traducido no coincide con el nombre oficial WFRP2 (ver más abajo). Un acceso vincula la profesión importada como salida de la profesión de origen (los accesos no se guardan como campo propio — se derivan de las salidas de otras profesiones). Solo lo que no encuentra ninguna coincidencia queda como texto "pendiente de vincular" en la descripción, para asignarlo a mano.

> **Duplicados:** si al guardar resulta que ya existe una profesión con ese nombre exacto (por ejemplo, al retomar una revisión ya guardada antes), el sistema no crea un duplicado — te redirige a la profesión existente con un aviso.

> **Caché de la revisión:** el resultado del procesamiento (OCR incluido) se guarda 48 horas en un volumen persistente, así que puedes cerrar la pestaña o perder la sesión sin perder el trabajo — usa **"Retomar"** desde la pantalla de subida de PDF. Esta caché sobrevive incluso a un reinicio/actualización del servidor.

> **Enseres mal clasificados como talentos:** cuando el OCR/traducción no reconoce la cabecera "Enseres:" (encabezado muy deformado), su contenido solía quedarse enganchado al final de los talentos, sin forma de recuperarlo. El sistema ahora detecta objetos con pinta de enser (p.ej. "4 Cuchillos arrojadizos", "10 metros de cuerda") dentro del texto de talentos y los mueve automáticamente a Enseres. No es infalible con texto muy corrupto — revisa siempre los chips de talentos tras importar.

> **Diccionario de sinónimos y nombres de carrera:** el diccionario (**Admin → Sinónimos**) corrige términos donde la traducción literal de GTranslate no coincide con el nombre oficial WFRP2 en español (p.ej. "conocimiento académico" → "sabiduría académica"). Ahora también se aplica a los nombres de otras profesiones listados en accesos/salidas (p.ej. la carrera inglesa "Champion" se traduce oficialmente como "Héroe", no "Campeón"). Se han añadido varias entradas de partida marcadas como "verificar" en sus notas — revísalas en **Admin → Sinónimos** y corrígelas si no coinciden con tu edición del libro.

> **Las habilidades y talentos de una profesión solo pueden ser los ya existentes en el catálogo** (una elección "Habilidad A o Habilidad B" también se construye con dos entradas ya existentes, nunca texto libre). La pantalla de revisión ahora reescribe cada chip a su nombre exacto del catálogo cuando hay una coincidencia razonable (p.ej. "preparar veneno" → "Preparar venenos"), en vez de dejar un texto parecido-pero-distinto que podría acabar creando sin querer una habilidad o talento duplicado. Además, crear o renombrar una habilidad/talento a mano (o importarlos por lote) ahora avisa si el nombre es muy parecido a uno ya existente, y bloquea la creación si es un duplicado exacto.

---

### Gestionar profesiones manualmente

Ve a **Admin → Nueva Profesión** o al icono de edición de cualquier profesión existente.

#### Campos del formulario

**Información básica**
- **Nombre (ES):** Nombre en español de la profesión. Campo obligatorio.
- **Nombre (EN):** Nombre en inglés (opcional, útil como referencia).
- **Tipo:** Básica o Avanzada.
- **Descripción:** Texto libre con la descripción de la profesión.
- **Imagen:** Foto o ilustración de la profesión (JPG, PNG, etc.).

**Perfil Principal** (características primarias, mejoras en porcentaje, múltiplos de 5)

| Sigla ES | Sigla EN | Nombre completo |
|---|---|---|
| HA | WS | Habilidad de Armas |
| HP | BS | Habilidad de Proyectiles |
| F | S | Fuerza |
| R | T | Resistencia |
| Ag | Ag | Agilidad |
| I | Int | Inteligencia |
| V | WP | Voluntad |
| Em | Fel | Empatía |

**Perfil Secundario** (características secundarias, mejoras en unidades)

| Sigla ES | Sigla EN | Nombre completo |
|---|---|---|
| A | A | Ataques |
| H | W | Heridas |
| BF | SB | Bonus de Fuerza |
| BR | TB | Bonus de Resistencia |
| M | M | Movimiento |
| Mag | Mag | Magia |
| PL | IP | Puntos de Locura |
| PD | FP | Puntos de Destino |

**Habilidades**

La sección de habilidades distingue dos tipos de entrada:

- **Habilidades simples:** Marca la casilla y opcionalmente rellena el campo **"Gr."** (grupo de elección) y **"Esp."** (especialización separada por comas).
- **Habilidades con especializaciones predefinidas** (Hablar Idioma, Oficio, Sabiduría Académica, etc.): muestran un panel expandible con tags clicables. Cada clic en un tag **añade una entrada** nueva con esa especialización; cada entrada tiene su propio campo **"Gr."**. Esto permite representar exactamente la estructura del libro:
  - *Hablar Idioma (Reikspiel o Tileano)* → dos entradas con el mismo grupo = el jugador elige una.
  - *Hablar Idioma (Bretón)* → una entrada con grupo distinto = obligatoria.
  - Los botones **Cualquiera / Dos cualquiera / Tres cualquiera** añaden entradas especiales para elecciones abiertas.

El campo **"Gr."** (grupo de elección) funciona igual para habilidades simples y con especializaciones: habilidades/entradas con el mismo número son alternativas (el jugador elige una). Déjalo vacío para elementos obligatorios.

**Talentos**
- Funciona igual que las habilidades simples. Usa el número de grupo para indicar elecciones tipo "Talento A o Talento B".
- El campo "Esp." permite especializaciones del mismo modo.
- **Talentos con especializaciones predefinidas** (por ahora, "Especialista en armas"): usan el mismo panel expandible con tags clicables que las habilidades tipo Sabiduría Académica (ver arriba) — cada clic añade una entrada (p.ej. *Especialista en armas (Parada)*), con su propio grupo de elección. Para añadir más talentos a esta lista, edita `app/data/talent_specializations.json` (misma estructura que `skill_specializations.json`, indexado por el nombre en español del talento).

**Enseres**
- Lista separada por comas de los objetos necesarios para la profesión.
- Ejemplo: `Espada, Escudo, Armadura de malla, 10 coronas de oro`

**Salidas (Career Exits)**
- Marca las profesiones a las que se puede acceder al completar ésta.
- Los accesos (Career Entries) se derivan automáticamente de las salidas ya configuradas en otras profesiones.

---

### Gestionar habilidades y talentos

Ve a **Habilidades** o **Talentos** desde el menú principal.

#### Campos de Habilidades

| Campo | Descripción |
|---|---|
| **Nombre (ES)** | Nombre en español. Obligatorio. |
| **Nombre (EN)** | Nombre en inglés. Lo usa el sistema para enlazar habilidades al importar PDFs en inglés. |
| **Tipo** | Básica o Avanzada. |
| **Características** | Características de las que depende la habilidad (p.ej. `Empatía, Inteligencia`). Separadas por comas si hay varias. |
| **Talentos asociados** | Talentos que potencian o modifican esta habilidad. |
| **Descripción** | Texto completo de la habilidad según las reglas. |

#### Campos de Talentos

| Campo | Descripción |
|---|---|
| **Nombre (ES)** | Nombre en español. Obligatorio. |
| **Nombre (EN)** | Nombre en inglés. Lo usa el sistema para enlazar talentos al importar PDFs en inglés. |
| **Descripción** | Texto completo del talento según las reglas. |

#### Búsqueda y filtros

- **Buscador** en la parte superior: busca por nombre de forma predeterminada. Activa **"Todos los campos"** para buscar también en descripción, características y talentos asociados.
- **Filtro por tipo** (solo habilidades): filtra entre Básica, Avanzada o todas.
- **Filtro por característica** (solo habilidades): muestra solo las habilidades que dependan de una característica concreta (desplegable con todos los valores existentes en la BD).

#### Importar y exportar

Desde la página de listado de habilidades o talentos, usa los botones **Importar** y **Exportar**.

**Formatos soportados:** texto plano (`.txt`), CSV (`.csv`) y Excel (`.xlsx`).

##### Formato de texto — Talentos

```
Nombre: Talento de ejemplo
Descripción: Descripción completa del talento.

Nombre: Otro talento
Descripción: Su descripción.
```

Cada bloque va separado por una línea en blanco. Los nombres de campo son `Nombre:` y `Descripción:`.

##### Formato de texto — Habilidades

```
Nombre: Habilidad de ejemplo
Tipo: Básica
Características: Empatía
Descripción: Descripción completa.
Talentos asociados: Talento A, Talento B

Nombre: Otra habilidad
Tipo: Avanzada
Características: Inteligencia, Voluntad
Descripción: Su descripción.
Talentos asociados:
```

Cada bloque separado por línea en blanco. `Tipo` acepta `Básica` o `Avanzada` (insensible a mayúsculas). Si `Talentos asociados:` está vacío o ausente, se guarda `NULL`.

> **Recomendación:** Carga primero el catálogo completo de habilidades y talentos antes de importar PDFs, para que el sistema pueda enlazarlos automáticamente.

---

### Gestionar usuarios y permisos

Ve a **Admin → Usuarios**.

#### Lista de usuarios

Desde esta pantalla puedes:

- **Cambiar el rol** entre `usuario` y `admin` con el selector de la fila. Los administradores tienen acceso total y no están limitados por las plantillas ni los permisos individuales.
- **Ver la plantilla asignada** a cada usuario normal en la columna "Plantilla".
- **Activar/Desactivar** usuarios con el botón de pausa/play. Un usuario desactivado no puede iniciar sesión.
- **Editar los permisos** de un usuario con el icono de llave 🔑, que abre la pantalla de edición de permisos.
- **Restablecer a una contraseña aleatoria** (icono ↻): genera una contraseña segura al azar, se muestra una única vez en el flash de confirmación, y marca al usuario para que la cambie en su próximo inicio de sesión.
- **Establecer una contraseña concreta** (icono 🔑 junto al de restablecer): abre un formulario para escribir tú mismo la nueva contraseña (con confirmación), con la opción de forzar además que el usuario la cambie la próxima vez que entre.
- **Forzar cambio de contraseña** (icono ⚠️) sin tocar la contraseña actual: la próxima vez que el usuario inicie sesión, se le redirige obligatoriamente a la pantalla de cambio de contraseña antes de poder ver nada más de la aplicación.
- **Eliminar** la cuenta de usuario permanentemente.

#### Edición de permisos de un usuario (`/admin/usuarios/<id>/permisos`)

Desde aquí puedes:

1. **Asignar una plantilla** al usuario (ver sección siguiente). La plantilla define el conjunto base de permisos.
2. **Activar permisos directos** adicionales, que se suman a los de la plantilla. Útil para dar acceso puntual a una función sin crear una nueva plantilla.
3. Ver los **permisos efectivos actuales** (unión de plantilla + directos) como referencia.

#### Plantillas de permisos (`/admin/plantillas`)

Las plantillas son conjuntos predefinidos de permisos que se pueden asignar rápidamente a varios usuarios. Ve a **Admin → Plantillas de permisos** (o desde el botón de la pantalla de usuarios).

Plantillas incluidas por defecto:

| Plantilla | Permisos incluidos |
|---|---|
| **Lector** | Ver profesiones · Ver habilidades · Buscador de caminos · Ver personajes · Ver contactos |
| **Editor** | Todo lo anterior + Editar profesiones · Importar PDF · Editar habilidades · Editar personajes · Editar/importar contactos |
| **Gestor** | Todo lo anterior + Gestionar usuarios (asignar plantillas y permisos a otros) |

Puedes crear, editar y eliminar plantillas desde esa pantalla. Al eliminar una plantilla, los usuarios que la tenían asignada pierden los permisos que venían de ella (los permisos directos se mantienen).

#### Códigos de permisos disponibles

| Código | Descripción |
|---|---|
| `professions.view` | Consultar listado y detalle de profesiones |
| `professions.edit` | Crear, editar y eliminar profesiones |
| `professions.import` | Importar profesiones desde un PDF |
| `skills.view` | Consultar habilidades y talentos |
| `skills.edit` | Crear, editar y eliminar habilidades y talentos |
| `pathfinder.use` | Buscar rutas entre profesiones |
| `characters.view` | Consultar personajes propios |
| `characters.edit` | Crear y editar personajes propios |
| `contacts.view` | Consultar listado y ficha de contactos |
| `contacts.edit` | Crear contactos y editar el propio vínculo (nivel, notas...) de un personaje |
| `contacts.import` | Importar/exportar contactos desde Excel |
| `equipment.view` | Consultar catálogo de armas, armaduras, ropas y objetos especiales |
| `equipment.edit` | Crear, editar y eliminar objetos del catálogo de equipamiento (incluida la edición en bloque) |
| `equipment.import` | Importar/exportar el catálogo de equipamiento en JSON |
| `users.manage` | Asignar plantillas y permisos a otros usuarios (no puede convertir en admin) |

> **Nota:** Los administradores (`role = admin`) tienen acceso completo a todas las funciones independientemente de los permisos asignados. El permiso `users.manage` permite a un usuario normal gestionar permisos de otros, pero no puede cambiar roles ni crear administradores. Al igual que `characters.*`, los códigos `contacts.*` están catalogados y disponibles para plantillas, pero las rutas de Contactos autorizan con `login_required` + comprobaciones de propiedad/rol (no con `require_permission`) — mismo patrón ya existente en el resto de la app. El catálogo de Equipamiento (listado y ficha de cada objeto) es público, sin necesitar `equipment.view`; ese código existe para catalogarlo en plantillas de permisos, pero solo `equipment.edit`/`equipment.import` están realmente aplicados con `@require_permission` en las rutas de creación/edición/borrado/importación/exportación.

---

### Revisar recetas propuestas

Ve a **Admin → Recetas pendientes** (o al indicador "Recetas pendientes" del panel de administración). Cada receta propuesta por un usuario muestra quién la pidió y cuándo, y todos sus valores ya calculados (vigor, moral, coste, precio, duración, complejidad, ingredientes/condimentos) — son de solo lectura, no se editan aquí. Una tabla de **"Desglose por elemento"** muestra, fila por fila, cuánto aporta el método de cocina y cada ingrediente/condimento a Vigor, Moral y Coste (más la duración, que sale solo del método) — para no tener que abrir Métodos/Ingredientes en otra pestaña al revisar si los números cuadran.

- **Aprobar**: sube una imagen (obligatoria si la receta todavía no tiene una) y pulsa Aprobar. La receta pasa a `aprobada`, se registra qué administrador la aprobó y cuándo, y desde ese momento aparece en el catálogo público de Recetas con la etiqueta "Comunidad".
- **Rechazar**: puedes indicar un motivo (opcional pero recomendado); el proponente lo verá en su página "Mis recetas".
- Si algo de la composición está mal (un ingrediente que no pega, un nombre confuso...), la opción más simple es rechazarla con un motivo explicando qué corregir — quien la propuso puede volver a enviarla.
- **Eliminar**: en la ficha de la propia receta (`Comida y bebida → Recetas → Ver`, no en la cola de pendientes) los administradores tienen un botón "Eliminar" que borra la receta y su imagen de forma permanente. Está en la ficha normal en vez de en la cola de revisión porque una receta rechazada o ya aprobada desaparece de "Recetas pendientes" y necesita poder borrarse igualmente (p.ej. una prueba mal hecha que nunca debió proponerse).

---

### Backup y recuperación

Además de la copia de seguridad completa por `mysqldump` (ver [Copias de seguridad de la base de datos](#copias-de-seguridad-de-la-base-de-datos)), cada una de estas secciones tiene su propio **Exportar/Importar** en formato **JSON**, pensado para no perder trabajo manual ante un problema con la base de datos — sobre todo **Profesiones**, ya que reconstruir el catálogo desde el PDF exige revisión manual de más de 220 entradas.

| Sección | Dónde | Incluye |
|---|---|---|
| **Profesiones** | Profesiones → Exportar/Importar (requiere permiso `professions.edit`) | Todos los campos propios + habilidades/talentos/enseres/salidas de carrera + **su foto** (bytes en base64, no solo la ruta) |
| **Usuarios** | Admin → Usuarios → Exportar/Importar | Todos los campos **salvo la contraseña** (ver más abajo) |
| **Equipamiento** | Equipamiento → Exportar/Importar (requiere permiso `equipment.import`), o Admin → Panel | Todos los objetos del catálogo (armas, armaduras, ropa, libros, otros, especiales), con sus estadísticas, campos adicionales, el enlace al objeto base para objetos especiales y **su foto** (bytes en base64). Empareja por (nombre, categoría, subcategoría, calidad) — no por id — porque el catálogo tiene bastantes objetos que comparten nombre dentro de una categoría (p.ej. cada tier de calidad de ropa) |
| **Recetas** | Admin → Comida y bebida → Exportar/Importar | Recetas propuestas por jugadores (pendiente/aprobada/rechazada) y las del libro, con método/ingredientes/condimentos por nombre y **su foto** (bytes en base64). Bebidas y métodos de cocina se siembran solo al arrancar el contenedor, no hace falta respaldarlos. Los **ingredientes** sí se editan en caliente (Admin → Comida y bebida → Ingredientes) pero de momento **no** viajan en este export ni en el Backup completo — cualquier edición hecha ahí solo vive en la base de datos de esa instancia |
| **Recargo de precios** | Solo dentro del Backup completo (sin página propia) | El % global de recargo activo sobre las compras de comida/bebida y quién lo estableció por última vez |
| **Personajes** | Personajes → Exportar/Importar (solo visible para admin) | Ficha completa: características, trasfondo, carrera, habilidades, talentos, rasgos, contactos generados en creación, posesiones, objetos mágicos, grado(s) y mochila/saco de la Untersuchung, **su foto** (bytes en base64), **inventario** (qué tiene y en qué ubicación, incluida comida/bebida comprada), **historial de compras** y **dinero concedido a mano** |
| **Plantillas de permisos** | Admin → Usuarios → Plantillas de permisos → Exportar/Importar | Nombre, descripción y permisos incluidos |
| **Diccionario de sinónimos** | Admin → Diccionario de sinónimos → Exportar/Importar | Todas las entradas (término original/correcto, prefijo, notas) |
| **Contactos + Vínculos** | Admin → Vínculos → Exportar/Importar | Cada contacto con su carrera profesional (sueldo objetivo incluido), **todos** sus vínculos por personaje (nivel, tipo de relación), quién lo registró, sus **notas privadas** por personaje y **su foto** (bytes en base64) — más completo que la exportación Excel de Contactos (que solo cubre nombre/Untersuchung/profesiones y se mantiene aparte, sin cambios) |
| **Backup completo** | Admin → Backup completo (o el indicador del panel) | Exporta/importa las nueve secciones anteriores de golpe, en el orden correcto de dependencias — **selectivo**: se puede desmarcar cualquier sección antes de exportar (todas marcadas por defecto = backup total); el propio fichero guarda qué secciones incluye (`secciones`). Cada exportación queda guardada en el servidor: una lista de solo nombres a la izquierda (el propio nombre ya lleva la fecha) y, al elegir uno, un panel de detalle a la derecha con sus secciones y nº de registros por sección, tamaño, etc. — los botones (Descargar/Comprimir·Descomprimir/Eliminar) van encima de ambos y actúan sobre el fichero seleccionado. **Comprimir** (gzip, reduce el tamaño en disco) tiene su reverso **Descomprimir**; un backup comprimido sigue siendo descargable/importable/**restaurable** con normalidad (se descomprime al vuelo). También se puede marcar cualquier combinación de ficheros y pulsar **Comprimir seleccionados** o **Descomprimir seleccionados** — cada acción solo afecta a los seleccionados que le correspondan (comprimir ignora los ya comprimidos y viceversa, cada uno en su propio fichero). El panel de detalle también tiene un campo de **nota** libre por backup (p.ej. "antes de actualizar profesiones") — se guarda dentro del propio fichero (no en un índice aparte), así que sobrevive a comprimir/descomprimir/descargar sin esfuerzo extra, y un icono en la lista avisa de qué backups tienen nota (con el texto en el tooltip). Pensado para poder levantar una instancia nueva desde cero (p. ej. tras un fallo de disco) sin perder ningún dato real — el único hueco intencionado es `CharacterCartItem` (un carrito de compra a medio hacer, sin valor de recuperación) |

Cómo funciona el import (mismo criterio en todas las secciones):

- **Restaurar sin descargar/resubir**: cada backup guardado en el servidor (panel de detalle → "Restaurar este
  backup") tiene su propio botón de restauración con el mismo selector Omitir/Actualizar que el import por
  fichero — importa el JSON directamente desde `BACKUP_FOLDER` (descomprimiendo al vuelo si estaba
  comprimido), sin tener que descargarlo primero al dispositivo y volver a subirlo. El import por fichero
  (subir un `.json` desde el equipo) sigue existiendo tal cual, para restaurar un backup que no está guardado
  en este servidor.
- **Nunca se identifica por id** — cada fila se empareja por su clave natural (nombre de usuario, nombre de profesión, nombre+usuario de personaje...), así el JSON exportado de una base de datos se puede importar en otra distinta.
- **Modo "Omitir"** (por defecto): si el registro ya existe, no se toca. **Modo "Actualizar"**: lo sobrescribe (y sus datos anidados) con lo importado.
- Una referencia que no se encuentra (una habilidad, un usuario, una profesión...) **no aborta la importación** — esa fila concreta se omite y aparece como aviso en el resumen final, igual que ya hace la importación de PDF con talentos/enseres no reconocidos.
- **Imágenes**: Profesiones, Equipamiento, Recetas, Contactos y Personajes son las cinco secciones con foto propia. Su export ya no guarda solo la ruta (`image_path`) sino también los bytes de la imagen en base64 (`image_data_b64`) — así el JSON queda autocontenido: `uploads/` no viaja con `git pull` ni se copia solo, así que sin esto una instancia nueva (o restaurada en otra máquina) se quedaba con la ruta apuntando a un fichero que no existía. Al importar, si la fila trae `image_data_b64` se reescribe el fichero en `uploads/<image_path>`; si no lo trae (backup antiguo, o fila sin foto) no se toca nada. Las 8 marcas de la Untersuchung (`uploads/imagenes_untersuchung/`) quedan fuera de este mecanismo a propósito — son un recurso fijo del libro, no datos ligados a una fila de ningún modelo.
- La importación de **Usuarios** nunca incluye ni toca contraseñas: un usuario nuevo recibe una contraseña temporal aleatoria (mostrada una vez, tras la importación) con cambio obligatorio en el próximo inicio de sesión; actualizar un usuario ya existente no modifica su contraseña actual.

**Restaurar una base de datos completamente vacía**, en orden:

1. `flask init-db` (crea el esquema, siembra permisos/plantillas por defecto y el catálogo de Comida y bebida).
2. Importa **Habilidades** y **Talentos** con su propio import (Profesiones y Personajes los referencian por nombre y no forman parte de este backup).
3. Importa el **Backup completo** (o, si prefieres ir sección a sección: Plantillas de permisos → Sinónimos → Usuarios → Profesiones → Equipamiento → Recetas → Recargo de precios → Personajes → Contactos+Vínculos, en ese orden).

---

### Gestionar el catálogo de Equipamiento

Ve a **Equipamiento** en el menú principal (requiere permiso `equipment.edit` para crear/editar/eliminar; el listado y la ficha de cada objeto son públicos para cualquier usuario autenticado o no).

- El menú **Equipamiento** se despliega en un enlace por categoría (**Armas**, **Armaduras**, **Munición**, **Ropa**, **Libros**, **Otros objetos**, **Objetos especiales**) más un **Catálogo completo**. Cada enlace de categoría muestra solo esos objetos (el desplegable de categoría desaparece del formulario de filtros, ya que está implícita) y la cabecera indica en cuál estás (p.ej. "Equipamiento — Armas"); el Catálogo completo sigue permitiendo elegir cualquier categoría desde el desplegable, como antes. Munición (flechas/virotes, balas, pólvora...) es su propia categoría independiente — antes vivía como una subcategoría dentro de Armas.
- **Calidad dinámica en Armas y Armaduras**: como la calidad de estas dos categorías es un modificador de compra (no un atributo del objeto), el filtro de calidad no oculta objetos — en su lugar, al elegir una calidad concreta, cada ficha muestra sus estadísticas y precio ya ajustados a esa calidad. En Armas: aguante/ataque-parada/daño según la tabla de fabricación del libro, acumulada sobre el modificador propio del arma. En Armaduras: la fila "Agilidad/Calidad" (que con "Toda calidad" muestra las 4 cifras Mala/Normal/Buena/Excelente a la vez) pasa a mostrar solo el valor de la calidad elegida, ya que esa es también la que determina el peso de la pieza (ver más abajo). La munición nunca varía por calidad ("se fabrica siempre normal") y no participa de nada de esto, aunque esté dentro de la categoría Arma.
- **Nuevo / Editar**: cada objeto tiene `categoría` (arma/armadura/ropa/libro/otros/especial), `subcategoría` (tipo dentro de la categoría, p.ej. cuerpo a cuerpo/distancia/munición para armas), `calidad` (solo relevante como atributo fijo de catálogo en Ropa, donde cada tier de calidad es una fila distinta — en Armas/Armaduras la calidad es un modificador de compra, no un atributo del objeto), precio (`price_text` libre + el peniques normalizado que se calcula solo si el texto es una cantidad simple — la munición admite además un lote entre paréntesis, p.ej. "1C (5)"), peso (en las unidades de carga del libro; no aplica a armadura/escudos, que derivan su peso de la penalización de agilidad), imagen (solo Arma/Armadura), **Estadísticas** (`stats`, lo que trae el libro — clave/valor libre) y **Campos adicionales** (`custom_fields`, lo que añade un administrador a mano; nunca se pisa al reimportar desde el libro).
- **Editar campos en bloque** (enlace junto a Exportar/Importar/Nuevo): añade, renombra o elimina un campo de `custom_fields` sobre **todos** los objetos que coincidan con los filtros de categoría/subcategoría/calidad/búsqueda —para no tener que entrar objeto a objeto cuando hace falta un campo nuevo (p.ej. "poder mágico") en todo un conjunto. Añadir no sobreescribe por defecto (casilla opcional "sobreescribir si ya existe"); renombrar solo afecta a quien tenga la clave antigua y avisa si el objeto ya tenía también la nueva (no la pisa); eliminar solo afecta a quien tenga esa clave. Cada operación muestra un resumen de cuántos objetos se han creado/actualizado/omitido.
- **Exportar/Importar** (requiere además `equipment.import`): JSON de todo el catálogo, empareja por (nombre, categoría, subcategoría, calidad) — ver [Backup y recuperación](#backup-y-recuperación).
- **Alta sin coste al inventario**: un administrador puede activar, por usuario, la capacidad de que ese jugador añada equipo directamente al inventario de sus personajes **sin cobrarlo** (pensado para dar de alta el equipo que un personaje ya existente tenía antes de migrar a este sistema, no para comprar gratis de forma habitual) — toggle en **Admin → Usuarios**, junto al de Activo/Inactivo. Queda registrado en el historial de compras del personaje con precio 0 y una nota indicándolo, para distinguirlo de una compra real.

---

## Guía de operación — Usuario

### Registro e inicio de sesión

1. Pulsa **Registrarse** en la barra de navegación.
2. Introduce usuario, email y contraseña (mínimo 6 caracteres).
3. Inicia sesión desde **Entrar**.

> Los usuarios recién registrados no tienen ningún permiso por defecto. Un administrador debe asignarles una plantilla o permisos directos desde **Admin → Usuarios**.

### Cambiar tu contraseña

Desde el menú desplegable con tu nombre de usuario (arriba a la derecha), entra en **Cambiar contraseña**. Pide tu contraseña actual, la nueva (mínimo 8 caracteres) y su confirmación.

Si un administrador ha marcado tu cuenta para forzar el cambio (por ejemplo, tras crear tu usuario o restablecerte la contraseña), la aplicación te lleva automáticamente a esta pantalla en tu próximo inicio de sesión y no te deja ver nada más hasta que la cambies.

### Elegir el tema (modo oscuro / modo claro)

Desde el mismo menú desplegable con tu nombre de usuario, en la sección **Tema**, puedes elegir entre **Modo oscuro** (el de siempre) y **Modo claro** (fondo claro, texto oscuro, pensado para quien tiene problemas de visión o simplemente prefiere trabajar sobre fondo blanco). Un icono de check marca cuál está activo. El cambio es instantáneo, sin recargar la página.

La preferencia se guarda en el propio navegador (no en tu cuenta), así que hay que volver a elegirla si cambias de dispositivo o navegador. Por defecto, todo el mundo empieza en modo oscuro. La barra de navegación y el pie de página cambian de color igual que el resto de la app; la única excepción es la banda de "entorno de preproducción" (teal), que se queda fija en ambos modos a propósito — su función es destacar y avisar, así que no debe camuflarse por elegir un tema u otro.

---

### Explorar profesiones

Ve a **Profesiones** en el menú principal.

- Filtra por tipo (**Básica / Avanzada**) o busca por nombre.
- Al entrar en una profesión verás todos sus detalles: perfil primario y secundario, habilidades con grupos de elección indicados como "Habilidad A **o** Habilidad B", talentos, enseres, y las profesiones de acceso y salida.
- Desde la ficha puedes lanzar el **Buscador de caminos** con esa profesión como punto de partida.

---

### Usar el Buscador de caminos

Ve a **Profesiones → Buscador de caminos** en el menú principal (vive bajo Profesiones porque depende directamente de su catálogo).

1. Selecciona la **profesión de inicio** (la que tiene el personaje ahora o la inicial).
2. Selecciona la **profesión de destino** (la que se quiere alcanzar).
3. Pulsa el botón de búsqueda.

El sistema muestra hasta **5 rutas posibles**, ordenadas de menor a mayor número de pasos.

Para cada ruta se muestra:

- **Ruta:** secuencia de profesiones (Ej.: Soldado → Mercenario → Veterano).
- **Totales acumulados:** el valor más alto que ofrece cualquier profesión del camino, para cada característica.
  - Las características **primarias** (HA, HP, F, R, Ag, I, V, Em) mejoran en pasos de 5 %.
  - Las características **secundarias** (A, H, BF, BR, M, Mag, PL, PD) mejoran en pasos de 1 unidad.
- **Detalle por paso:** despliega cada profesión del camino con sus características, habilidades, talentos y enseres. Todos los pasos pueden estar abiertos simultáneamente.
- **Resumen de habilidades/talentos:** listado completo de todo lo que se puede obtener durante el camino (incluyendo grupos de elección).

---

### Explorar habilidades y talentos

- Ve a **Habilidades** o **Talentos** en el menú.
- Busca por nombre (opción por defecto) o activa **"Todos los campos"** para buscar también en la descripción.
- En habilidades, filtra adicionalmente por tipo (Básica/Avanzada) o por característica asociada.
- Al entrar en una habilidad o talento, verás su descripción completa, características y talentos asociados, y la lista de **todas las profesiones que lo otorgan**.

---

### Crear y gestionar personajes

Un jugador normal solo ve sus propios personajes en el listado; un administrador ve los de todos los jugadores (agrupados por usuario), aunque cualquiera puede editar/ver la ficha de cualquier personaje ya conociendo su URL.

Hay dos formas de crear un personaje desde **Personajes**:

#### Creación rápida (manual)

1. Introduce el nombre, raza y género del personaje, sube opcionalmente una **foto/retrato**, y marca si es **miembro de la Untersuchung** (afecta a qué contactos ven ese dato en la ficha de Contactos). La foto se puede añadir o cambiar más tarde desde **Editar** en cualquier momento; si no tiene, la ficha muestra un icono de marcador de posición y el listado simplemente no muestra miniatura para ese personaje.
2. En la sección **Carrera Profesional**, añade las profesiones que ha tenido el personaje en orden cronológico usando el botón **Añadir profesión**; para cada una puedes elegir además un tipo de sueldo y estado de habilidad (misma tabla de referencia que en Contactos).
3. La última profesión añadida se marca como "Actual".
4. Guarda el personaje.

> **Buscador de profesiones con salidas resaltadas:** cada casilla de profesión es un buscador (escribe para filtrar en vivo sobre las ~220 profesiones del catálogo, ordenadas alfabéticamente). Las profesiones que son **salida** de alguna de las ya elegidas en el personaje se marcan con una insignia "★ Salida" y aparecen agrupadas primero — de referencia, no restrictivo: siempre puedes elegir cualquier otra profesión del catálogo (p. ej. por acuerdo excepcional con el director de juego).

#### Generador de Personaje (creación guiada por tiradas)

Ve a **Personajes → Generador de personaje**. Implementa las reglas caseras de creación de personajes jugadores (raza, profesión, características, trasfondo). Cada sección tiene un botón **Tirar** (🎲, lo hace la web) y un botón **Ver tabla** (para partidas con dados físicos: muestra todas las opciones posibles con su rango, y al hacer clic en la tuya se resalta en dorado y rellena los campos exactamente igual que si se hubiera tirado en la web). Todos los campos son editables a mano en cualquier momento.

> **Registro de tiradas:** en la parte superior de la página hay un panel que anota **todas** las tiradas (o elecciones manuales de tabla) hechas durante la creación, con el resultado exacto de cada dado — aunque el proceso sea automático, nada queda oculto. Se puede limpiar con el botón "Limpiar registro" si quieres empezar de cero.

Pasos del asistente, en orden:

1. **Raza** — tira dos veces y elige uno de los dos resultados (te da +1 Punto de Historial), o elige la raza directamente sin tirar.
2. **Profesión** — tira tres veces (según la raza elegida) y elige un resultado (+1 PH), o selecciona la profesión directamente del catálogo. Si la profesión tirada no existe todavía en el catálogo, créala primero desde **Profesiones** y luego selecciónala aquí.
3. **Características** — tira el perfil primario y secundario completo según la raza (incluye Bono de Fuerza/Resistencia calculados y las horas de sueño estimadas). Heridas, Puntos de Destino y Puntos de Historial también se pueden volver a tirar de forma independiente (un botón 🎲 propio junto a cada uno) sin rehacer el resto del perfil.
4. **Signo astral** — tira el signo (da un rasgo de personalidad y modificadores, mostrados también en la tabla manual junto a cada signo), o pulsa "Omitir" para no tirarlo y ganar +1 PH en su lugar.
5. **Altura, peso y edad** — tres tiradas encadenadas (el peso depende de la altura ya tirada).

> **Características finales:** el Perfil Principal (HA/HP/F/R/Ag/I/V/Em) se tira o se edita a mano como valor **base**, pero el signo astral y el tramo de altura/peso/edad pueden añadir modificadores porcentuales por encima. Bajo cada característica se muestra en vivo el valor **final** (base + todos los modificadores activos) según se va completando el asistente; volver a tirar o cambiar cualquiera de esos pasos sustituye su aportación anterior en vez de acumularla. Al guardar el personaje, el campo de cada característica se rellena con el valor **final**, no con el base — es el que se usa en partida.
6. **Apariencia** — color de pelo, ojos y mano dominante.
7. **Procedencia** — provincia y población de origen (o patria de origen para no humanos).
8. **Situación familiar** — huérfano, hijo único o número de hermanos (con sexo y edad relativa).
9. **Sucesos de juventud** — tira tantas veces como el grado de edad + 1 indique; los resultados de tipo contacto/amigo/enemigo se añaden automáticamente a la lista de contactos. Los sucesos narrativos que no tiene sentido repetir (p. ej. "Madre muerta", "Padres divorciados") no pueden salir dos veces en el mismo personaje — si se repite la tirada, se vuelve a tirar automáticamente.
10. **Puntos de Historial** — el contador de PH disponibles/gastados se actualiza automáticamente según lo tirado y elegido en los pasos anteriores (re-tirar un paso ya bonificado no vuelve a sumar el mismo bono). Cada opción de gasto (objeto mágico —dos tiradas encadenadas: tipo y luego propiedad—, talento aleatorio extra, posesiones, etc.) tiene su propio botón; algunas conllevan tirar también en la tabla de estética, personalidad o desventajas (el "peaje"). Las opciones "Misericordia de Shallya" y "+2%/+1 PV" abren un selector para elegir sobre qué característica (o Heridas) actuar.
11. **Habilidades y talentos raciales** — se muestran automáticamente según la raza (y la provincia, si es humano imperial), incluyendo el bono especial de provincia. El botón de talento aleatorio tira los talentos aleatorios base de la raza; el mismo talento no puede salir dos veces para un mismo personaje.
12. **Carrera profesional** — igual que en la creación rápida.

Al guardar, el personaje queda con toda la ficha completa: características, trasfondo, rasgos, contactos, posesiones y objetos mágicos, visibles en su página de detalle.

> **Nota:** el generador enlaza habilidades/talentos raciales al catálogo solo cuando el nombre coincide exactamente (p.ej. "Hablar idioma" con especialización "Reikspiel") — si el catálogo no tiene esa habilidad o talento todavía, no se crea nada automáticamente, igual que en la importación de PDF.

Desde la ficha del personaje puedes ver las estadísticas de cada profesión en su carrera, además de todo lo generado por el asistente.

---

### Gestionar Contactos

Ve a **Contactos** en el menú principal. Un contacto (NPC) tiene datos **globales** (nombre, raza, foto, carrera profesional con sueldo objetivo, si pertenece a la Untersuchung y su(s) grado(s), estado, lugares de descanso/trabajo/ocio, notas del director — solo admin) y datos **por personaje** (nivel de relación, tipo de relación, notas privadas) sobre el vínculo con el **personaje activo** del usuario — cada personaje ve y edita solo su propio vínculo, nunca el de otro, aunque sean del mismo usuario.

- **Crear y editar contactos es exclusivo de administrador**, desde **+ Nuevo contacto** o desde **Editar** en la propia ficha. El resto de usuarios solo consulta y gestiona su propio vínculo.
- **Personaje activo**: cada usuario tiene un personaje "activo" persistido (sustituye al antiguo selector "Ver como" por página). Se fija al hacer login si hace falta (con un único personaje se marca solo; con varios y ninguno marcado, se te lleva una vez al listado de Personajes a elegir), desde **Mi perfil** (menú de usuario, arriba a la derecha), o con el botón "Marcar activo" en cada tarjeta del listado de Personajes. Un administrador conserva además, solo en la ficha del contacto, un selector para editar el vínculo de cualquier otro personaje puntualmente.
- **Raza**: desplegable guiado (Humano, Enano, Alto elfo, Elfo Silvano, Halfling, Ogro, Hombre bestia, Piel verde, No muerto, Slam, Criatura, Monstruo, Demonio) con una opción **"Nueva raza…"** que revela un campo de texto libre para cualquier otra.
- **Estado**: Vivo / Muerto / Desconocido, como insignia en el listado y la ficha.
- **Visibilidad**: un único interruptor admin, **Visible** (en Editar contacto) — si está desmarcado, el contacto queda oculto para todos los no-admin. Sin concesiones por personaje.
- **Carrera profesional y sueldo** (2026-07-17): en Editar contacto, las profesiones se añaden con el mismo buscador + filas repetibles que la carrera de un Personaje (columnas Profesión / Tipo de trabajador / Calidad del trabajador / Sueldo del trabajador). El sueldo es un **hecho objetivo** que pone el director (no una creencia por personaje): se calcula en vivo a partir de la tabla de referencia de sueldos (tipo × calidad, sin ajuste por % de habilidad — a diferencia de un Personaje, un NPC no tiene ese dato) y se muestra también en la ficha, junto a cada profesión.
- **Nivel y tipo de relación**: el nivel es un desplegable de 5 a -5 con etiqueta descriptiva (Amigo incondicional…Enemigo mortal). El tipo de relación es una selección múltiple (Baza, Contacto, Súbdito, Señor, Otra) — con dos parejas mutuamente excluyentes (Baza/Contacto, Súbdito/Señor: marcar una desmarca la otra, tanto en el formulario como al guardar); "Otra" no tiene pareja.
- **Untersuchung**: hecho del propio contacto (`Contact.es_untersuchung`), no del vínculo — se marca a mano con el checkbox **Untersuchung** en Editar contacto, o se activa solo al asignar cualquier **grado** (el checkbox se marca automáticamente al elegir una marca; desmarcarlo a mano no la quita si el contacto sigue teniendo alguna). Ese dato (y su(s) grado(s)) **solo se muestra si el personaje activo también es miembro** (o eres admin, que siempre lo ve). Los grados tienen dos tiers: **Agente** (Escudo/Estilete/Gato/Brújula/Pluma/Corona, hasta 3 marcas, repetible = veteranía) y **Adjunto** (Carro/Paloma, exactamente 1 marca — solo se ofrece en la primera de las 3, y elegirlo ahí deshabilita las otras dos). Los **Personajes** tienen el mismo selector en su ficha de edición (con las mismas cabeceras de columna en su carrera profesional) — un jugador puede ser él mismo agente de la Untersuchung.
- **Notas**: privadas de cada personaje — una nota de tu personaje A nunca aparece al ver el contacto como tu personaje B. Fuera de la propia ficha, solo se muestra su **número**, nunca el contenido.
- La ficha de un contacto muestra siempre **todos** los campos globales, tengan o no dato (con un guion si están vacíos) — solo las marcas de la Untersuchung son la excepción deliberada: se ven únicamente las que el contacto realmente tiene, cada una con su nombre como texto alternativo.
- El listado de Contactos es global (visible para cualquier usuario, ya no hay filtrado por personaje): miniatura con zoom al pasar el ratón/lightbox al hacer clic (mismo sistema que Personajes), Raza, Unter, Estado, y un botón con el nº de personajes vinculados que despliega su nivel y tipo en un panel con una paleta de color propia (teal), para diferenciarlo claramente del resto de la tabla — el botón queda resaltado mientras el panel está abierto. La ficha añade al final una tabla **"Personajes con relación"**, visible a cualquiera que pueda ver el contacto.
- **Vínculos** (`/contactos/vinculos`, menú **Contactos → Vínculos**) ya no es admin-only: cualquier usuario lo ve, por defecto filtrado a los vínculos de su propio personaje activo (columnas: Contacto, Tipo de relación, Nivel, nº de notas, Ver ficha); un botón **"Ver todos"** amplía a los vínculos de todos los personajes de todos los usuarios (añade la columna Personaje). Un administrador ve siempre todos.
- Los administradores gestionan además desde **Admin → Contactos**: listado completo de **todos** los contactos del sistema (mostrar/ocultar, eliminar, editar), e importación/exportación Excel con columnas fijas (`nombre`, `es_untersuchung`, `profesiones` separadas por comas — deben existir ya en el catálogo de Profesiones; el resto de campos, incluido el sueldo, solo viaja en el "Backup completo" JSON).

---

### Comprar y gestionar equipo

Cada personaje tiene su propia **Tienda**, accesible desde su ficha.

- **Tienda**: catálogo de Armas, Armaduras, Munición y Ropa (los objetos especiales no se compran — los concede un administrador, ver más abajo). Filtra por categoría, **tipo** (subcategoría) y **calidad**, igual que el catálogo completo de Equipamiento — el desplegable de tipo se acota a los que existen dentro de la categoría elegida, o busca por nombre. Armas, Armaduras y Ropa se listan en el **orden del libro** (no alfabético) cuando el objeto tiene un `orden` asignado — se rellena con `flask set-equipment-book-order [--apply]` (informe de filas emparejadas/sin emparejar por categoría antes de escribir nada) o a mano por fila en el formulario de edición; cualquier objeto sin `orden` cae al orden alfabético de siempre.
- **Añadir al carrito**: al elegir un objeto, se pide **calidad** (Mala/Normal/Buena/Excelente en Armas y Armaduras — el precio se recalcula al vuelo con el multiplicador de esa calidad, ×0,5/×1/×3/×10, y en Armas se muestra también un avance de cómo cambian sus estadísticas con cada calidad; en Ropa la calidad ya es el objeto elegido, cada tier es una ficha distinta), **cantidad** y en qué **ubicación** del inventario se guarda. La munición no tiene calidad (siempre se fabrica normal) y se vende por lotes (p.ej. "5 flechas por 1 chelín") — la cantidad solo acepta múltiplos exactos del tamaño de lote de ese objeto.
- **Carrito**: revisa lo añadido antes de pagar, quita líneas sueltas, y visualiza el total. Al **finalizar compra**, se descuenta el total del dinero del personaje de una vez (todo o nada: si una línea no tiene precio calculable, o no hay dinero suficiente, no se cobra nada y se explica qué corregir) y cada línea pasa al inventario y al historial de compras.
- **Inventario**: el equipo del personaje (y la comida/bebida comprada, ver más abajo) repartido en 5 ubicaciones de almacenaje (Equipamiento, Mochila/saco, Alforjas, Base, Altdorf). Cada objeto se puede **mover** a otra ubicación, uno a uno (con la cantidad exacta a mover si hay varias unidades) o **varios a la vez** (casilla de selección por fila + un destino común), fusionándose con una pila ya existente del mismo objeto/calidad en el destino en vez de duplicar filas. El peso de cada línea se muestra como **unidad / total** (en unidades de carga, "U" — una mezcla de peso y volumen, no solo peso real), y también el total por ubicación. La comida (cualquier receta) siempre pesa **0,5U por ración** (2 raciones = 1U — lo normal es comer 3 raciones al día); una bebida pesa según su recipiente de venta — **Botella 1U, Pinta 0,5U, Chupito 0,1U** (1 litro son 2 pintas o 10 chupitos, así que el litro entero siempre pesa 1U independientemente de en cuántas consumiciones se reparta).
- **Carga**: solo lo que está en Equipamiento y Mochila/saco cuenta como "llevado encima" (El Imperio y sus viajes, p.9). El máximo es Fuerza + Resistencia (características, no sus bonos); por encima hay 3 niveles con penalización creciente a Movimiento/Agilidad/Atletismo (detallada por separado para Turno y para Viaje), mostrados con un código de color progresivo (verde → amarillo → naranja → rojo) en la tarjeta de Carga del Inventario: **Carga ligera** (≥ Fuerza), **Carga media** (≥ Fuerza+Resistencia) y **Carga pesada** (≥ 2×(Fuerza+Resistencia)). El talento Robusto (Enano) suma +20 a los tres umbrales. Independientemente de eso, la ubicación **Mochila/saco** tiene su propio límite físico según lo que el jugador indique que lleva — **Mochila (50U)** o **Saco (80U)** — y muestra un aviso en rojo si se supera, aunque el personaje sea lo bastante fuerte para cargar ese peso sin problema.
- **Historial de compras**: registro inmutable de todo lo comprado o concedido, con fecha, calidad, precio pagado y quién lo concedió si fue un administrador.
- **Alta sin coste**: si un administrador te ha habilitado esta opción, la pantalla de añadir al carrito incluye una casilla **"Ya lo tenía (no cobrar)"** que manda el objeto directo al inventario sin pasar por caja — pensado para dar de alta el equipo que el personaje ya tenía antes de usar esta tienda, no para uso habitual.
- **Objetos especiales**: no se compran en la tienda — un administrador los concede desde la ficha del personaje (**Conceder objeto especial**), con calidad, cantidad, precio (puede ser 0) y notas libres.
- **Conceder dinero**: mientras no haya sueldos ni recompensas automáticos, un administrador puede añadir dinero directamente a la cuenta de un personaje desde su ficha (**Conceder dinero**, junto al importe de dinero actual), indicando cantidad (Coronas/Chelines/Peniques) y un motivo libre (p.ej. "Sueldo semanal", "Recompensa de misión"). Cada concesión queda registrada en el **Historial de compras** del personaje (fecha, importe, motivo y quién la concedió), sin tocar el catálogo de equipamiento.

---

### Explorar Comida y bebida

Ve a **Comida y bebida** en el menú principal.

- **Bebidas**: catálogo completo por nación de origen (Bretonia, Enana, Elfica, Tilea, Estalia, Imperio, Kislev/Norsca, Arabia), con disponibilidad, calidad, sabor y precio en taberna. Filtra por nombre, origen, sabor, calidad o disponibilidad; pulsa en cualquier cabecera de columna para ordenar por ese campo (vuelve a pulsar para invertir el sentido) y usa **"Orden por defecto"** para volver al orden inicial (origen, nombre). En el listado y en la ficha de cada bebida hay una **calculadora de precio**: indica cuántas unidades quieres comprar y el total se calcula al momento (en Coronas de oro / Chelines de plata / Peniques). El dato de "Por mayor" es informativo (% de descuento comprando el tonel completo a un comerciante o productor). El campo **Sabor** tiene una categoría base (Extraño, Fuerte, Suave, Raro, Mala, Bueno, Muy buena, Dulce, Normal...) y, cuando el libro lo especifica, una **variante** más concreta debajo (p.ej. sabor "Extraño", variante "Picante" o "Amargo"; sabor "Raro", variante "Metálico" o "Café"). No se crean bebidas nuevas — es un catálogo cerrado.
- **Recetas**: catálogo de recetas, con su método de cocina, calidad, vigor, moral, duración, si se puede recalentar, complejidad, coste de creación (12 raciones) y precio de compra (1 ración). Filtra por nombre, método o calidad, y ordena por cualquier columna (incluidos ambos costes) igual que en Bebidas. Tres recetas especiales (Empanadilla Halfling, Pan de piedra, Lágrimas de Isha) están marcadas como **"Solo compra"**: no se pueden elaborar, solo adquirir ya hechas. Las recetas propuestas por usuarios y ya aprobadas llevan una etiqueta **"Comunidad"**.
- **Comprar bebidas y recetas**: en la ficha de cada bebida o receta (solo si tiene precio de compra) hay un formulario de **compra directa** integrado en la propia calculadora de precio; en el listado, el botón **Comprar** de cada fila abre una ventana emergente con los mismos campos. En ambos casos se elige la **cantidad**, el **personaje** al que va destinada (los tuyos, o cualquiera si eres administrador) y en qué **ubicación** de su inventario se guarda (las mismas 5 que usa el equipo). Al comprar se descuenta el total del dinero del personaje (todo o nada: si no llega el dinero no se cobra nada) y la aplicación te lleva directamente al **inventario** de ese personaje, donde ya aparece el objeto recién comprado (con enlace de vuelta a la bebida/receta), y también queda en su historial de compras. Si un administrador ha activado un **recargo global (%)** (Panel de administración → Recargo de precios, "por disponibilidad u otras razones"), el precio mostrado y el cobrado ya lo incluyen.
- **Proponer una receta nueva**: cualquier usuario puede proponer una receta desde **Comida y bebida → Proponer receta**. Eliges el método de cocina y hasta 4 ingredientes y 2 condimentos (el formulario solo deja elegir combinaciones válidas para ese método, según la tabla de compatibilidad); Vigor, Moral, Coste, Precio de compra, Duración, Recalentar, Complejidad y **Calidad** se **calculan automáticamente** con las mismas fórmulas del libro — no hay que rellenar nada de eso a mano, y el formulario muestra el cálculo en vivo según vas eligiendo. La **Calidad** no se elige: sale directamente de la Complejidad (1-4 Mala, 5-8 Normal, 9-12 Buena, 13+ Excelente — cada ingrediente relleno suma +1 a la complejidad, cada condimento +2, más la complejidad base del método). La receta queda en estado **pendiente** y no aparece en el catálogo público hasta que un administrador la revisa, le añade una imagen y la aprueba (o la rechaza, con un motivo). Desde **Comida y bebida → Mis recetas** puedes ver el estado de todo lo que has propuesto (pendiente/aprobada/rechazada, con el motivo si aplica).
- **Ingredientes**: tabla de referencia con el vigor/moral/coste por docena de cada familia de ingrediente, y su compatibilidad con cada método de cocina (Sí / Condimento / No).
- **Métodos de cocina**: tabla de referencia (Crudo, Ahumado, Secado, Salado, Almíbar, Brasa, Cocido, Guisado, Asar, Hornear) con su vigor/moral/coste/duración base y cuántos ingredientes y condimentos admite cada uno.
- **Normas**: página de referencia con las reglas de intoxicación por bebidas espirituosas (Achispado/Ebrio/Borracho) y las reglas de vigor y moral diarios. Se muestran tal cual las describe el libro, a título informativo — el sistema de cartas de estado (Fatigado, Motivado, Exhausto, Distraído...) que estas reglas mencionan **todavía no está implementado**; por ahora esos efectos se llevan a mano en partida.

---

## Modelo de datos

```
users
  ├─ template_id → permission_templates   (plantilla de permisos asignada)
  ├─ user_permissions (M2M)               (permisos directos adicionales)
  ├─ must_change_password                 (heredado de ContactosWH, no aplicado aún en el login)
  ├─ created_by_id → users.id             (lineage: quién creó la cuenta, opcional)
  ├─ active_character_id → characters.id  (personaje activo del usuario, ON DELETE SET NULL;
  │                                         sustituye al selector "Ver como" por página en Contactos)
  └─ characters                   (perfil completo: características WFRP2, trasfondo del
       │                           generador — raza, signo astral, altura/peso/edad,
       │                           procedencia, situación familiar, nivel social,
       │                           Puntos de Historial, dinero, es_untersuchung)
       ├─ character_professions   (lista ordenada de profesiones + tipo_sueldo/estado_habilidad)
       ├─ character_skills        (skill_id + specialization, p.ej. "Hablar idioma (Reikspiel)")
       ├─ character_talents       (talent_id + specialization + times_taken)
       ├─ character_traits        (estética/personalidad/desventaja rolados con Puntos de Historial)
       ├─ character_acquaintances (contactos/amigos/enemigos/hermanos de los sucesos de juventud
       │                           del generador — texto libre, independiente de contact_*)
       ├─ character_possessions   (objetos de inventario iniciales)
       ├─ character_magic_items   (objetos mágicos rolados con Puntos de Historial)
       └─ contact_character_links (su propia visión de cada Contacto, ver más abajo)

permissions                               (12 códigos de permiso disponibles)
permission_templates                      (conjuntos reutilizables de permisos)
template_permissions (M2M)                (permisos que incluye cada plantilla)

contacts                           (hechos GLOBALES de un NPC — iguales para todo el mundo)
  ├─ nombre, raza                  (raza es texto libre; el desplegable RAZA_CHOICES solo guía el form)
  ├─ es_untersuchung               (solo se muestra a personajes que también sean miembros, o admin)
  ├─ grados_untersuchung           (JSON, lista de 0-3 de UNTERSUCHUNG_GRADOS, dos tiers excluyentes:
  │                                 Agente —Escudo/Estilete/Gato/Brújula/Pluma/Corona, repetible—
  │                                 y Adjunto —Carro/Paloma, máx. 1—; solo aplica si es_untersuchung)
  ├─ estado                        ('vivo' | 'muerto' | 'desconocido', default 'vivo')
  ├─ lugar_descanso, lugar_trabajo, lugar_ocio  (texto libre, hechos globales del contacto)
  ├─ notas_director                (texto libre, solo visible/editable por admin)
  ├─ image_path
  ├─ is_visible                    (único interruptor de visibilidad: oculto para todo no-admin
  │                                 si está apagado, visible para cualquiera si está encendido)
  ├─ created_by_id → users.id      (quién lo registró; ya no determina permisos de edición)
  ├─ contact_professions           (carrera del contacto - profession_id + tipo_sueldo/estado_habilidad,
  │                                 mismas columnas que CharacterProfession; sueldo objetivo puesto por el
  │                                 director, no calculado de ninguna habilidad real - ver salary_service)
  ├─ character_links → contact_character_links
  └─ notes → contact_notes

contact_character_links            (la visión de UN personaje sobre un Contacto —
  ├─ character_id, contact_id      nunca visible para otro personaje, ni del mismo usuario, salvo
  │                                 nivel/tipo en la tabla "Personajes con relación" de la ficha)
  ├─ nivel                         (-5 a 5, con etiqueta descriptiva por NIVEL_LABELS)
  └─ tipo_relacion                 (JSON, lista de 0+ de Baza/Unter-Untersuchung/Súbdito/Señor/Otra)

contact_notes
  ├─ contact_id, character_id      (nota propia de un personaje, nunca de otro)
  └─ content

`salaries.json` (app/data/): tabla de referencia de sueldos (Obreros/Sirvientes/Artesanos/
Profesionales/Especialistas/Artistas o ilegal 1-3, con sueldo semanal/anual y umbrales de
habilidad m/n/b/ex) y multiplicadores por estado (Mala x0.5, Normal x1, Buena x2, Excelente x3) —
elegido manualmente al asignar una profesión a un Contacto o a un Personaje, no se calcula
a partir de ninguna habilidad real.

professions
  ├─ profession_skills    (skill_id + specialization + choice_group)
  │    Ejemplo: Hablar Idioma con specialization="Tileano" y otra fila
  │    con specialization="Estaliano" permiten guardar sub-habilidades
  │    múltiples de la misma habilidad base. Cuando varias entradas de la
  │    misma habilidad comparten choice_group, el jugador elige una.
  ├─ profession_talents   (talent_id + specialization + choice_group)
  ├─ profession_trappings (enseres requeridos)
  └─ career_exits         (salidas: relación auto-referencial many-to-many)

skills
  ├─ name_es, name_en
  ├─ is_advanced
  ├─ caracteristicas       (características de las que depende, sep. por comas)
  ├─ talentos_asociados    (talentos que la modifican, sep. por comas)
  └─ description

talents
  ├─ name_es, name_en
  └─ description

synonyms                   (diccionario para importación de PDFs)
  ├─ source  (término incorrecto/alternativo, en minúsculas)
  ├─ target  (nombre oficial en WFRP2 ES)
  ├─ is_prefix  (True = aplica también a "source (especialización)")
  └─ notes

cooking_methods             (Crudo, Ahumado, Secado, Salado, Almíbar, Brasa, Cocido, Guisado, Asar, Hornear)
  ├─ vigor, moral, coste, duracion_dias, complejidad_base
  ├─ ingredientes_permitidos, condimentos_permitidos   (cuántos slots admite una receta con este método)
  └─ elementos_necesarios, habilidad, recalentar

ingredients                 (Nada, Raíces, Verduras... Aceites — 20 familias del libro)
  ├─ vigor, moral, coste_docena
  └─ ingredient_cooking_methods → compatibilidad con cada método ('si' | 'no' | 'condimento')

recipes                     (recetas del libro + propuestas de usuarios, ver app/services/recipe_calc_service.py)
  ├─ cooking_method_id → cooking_methods   (null si solo_compra)
  ├─ vigor, moral, duracion_dias, recalentar, complejidad
  ├─ calidad                  (NO se elige a mano: 1-4 Mala, 5-8 Normal, 9-12 Buena, 13+ Excelente,
  │                             en función de complejidad = complejidad_base del método +1/ingrediente +2/condimento)
  ├─ coste_creacion_peniques (12 raciones), precio_compra_peniques (1 ración)
  ├─ solo_compra              (True = las 3 recetas especiales que no se pueden elaborar)
  ├─ ingrediente_1..4_id, condimento_1/2_id → ingredients  (slots fijos, como en la tabla del libro)
  ├─ status                   ('pendiente' | 'aprobada' | 'rechazada' — el libro siembra 'aprobada')
  ├─ image_path               (igual que Profession.image_path; obligatoria para aprobar una propuesta)
  ├─ created_by_id, requested_at → users   (quién la propuso y cuándo; null en las del libro)
  ├─ approved_by_id, approved_at → users   (quién la aprobó/rechazó y cuándo)
  └─ rejection_reason         (motivo opcional cuando se rechaza)

drinks                      (catálogo cerrado — "no se van a crear bebidas nuevas")
  ├─ origen                  (nación: Bretonia, Enana, Elfica, Tilea, Estalia, Imperio, Kislev/Norsca, Arabia)
  ├─ disponibilidad, calidad, ui_texto, recipiente
  ├─ sabor                    (categoría base del libro: Extraño, Fuerte, Suave, Raro, Mala, Bueno...)
  ├─ sabor_variante           (descriptor concreto, solo si el libro lo daba entre paréntesis: p.ej.
  │                            sabor="Extraño" + variante="Picante", sabor="Raro" + variante="Café")
  ├─ precio_taberna_peniques, por_mayor_pct
  └─ notas                   (efectos especiales de bebidas concretas)

equipment_items              (catálogo: arma | armadura | municion | ropa | especial | libro | otros)
  ├─ category, subcategory   (subcategory: cuerpo_a_cuerpo/distancia para armas,
  │                           acolchada/cuero/malla/placas/escudos... para armaduras, etc. -
  │                           munición es su propia categoría, sin subcategoría propia)
  ├─ quality                 (solo un atributo de catálogo real en Ropa - cada tier Harapos/
  │                           Común/Burguesa/Noble es su propia fila; en Arma/Armadura queda
  │                           NULL, la calidad es un modificador elegido al comprar, no del objeto)
  ├─ orden                    (posición dentro de su categoría, igual que en el libro - NULL hasta que
  │                           `flask set-equipment-book-order --apply` la rellena; sin ella, cae al
  │                           orden alfabético de siempre. Editable a mano por fila en el formulario)
  ├─ is_special, base_item_id (objetos especiales construidos sobre un objeto mundano base,
  │                           p.ej. "Espada Flamígera" con base_item = "Espada")
  ├─ price_text, precio_peniques, precio_escala_clase_social
  │                          (precio_peniques es el precio ya normalizado a peniques si price_text
  │                           era una cantidad simple; precio_escala_clase_social marca precios tipo
  │                           Ropa Noble que escalan con el nivel social del comprador, no un número fijo)
  ├─ unidades_por_precio     (munición vendida por lotes, p.ej. "1C (5)" = 5 flechas por ese precio -
  │                           precio_peniques es el precio del lote completo, no de una unidad; 1 para
  │                           todo lo que no es munición)
  ├─ image_path               (solo arma/armadura tienen foto de producto)
  ├─ stats                    (JSON libre: lo que trae el libro - daño, aguante, armadura, etc.
  │                           - varía demasiado de forma entre categorías para columnas fijas)
  ├─ custom_fields            (JSON libre añadido a mano por un admin - nunca se pisa al reimportar
  │                           desde el libro; editable uno a uno o en bloque sobre un conjunto filtrado)
  └─ peso                     (carga en las unidades del libro "El Imperio y sus viajes"; NULL para
                              armadura/escudos, cuyo peso se deriva en tiempo real de su propia
                              penalización de agilidad - stats.agilidad_por_calidad/agilidad - en vez
                              de guardarse aparte, para no desincronizarse entre las 4 calidades)

character_inventory_items    (una entrada del inventario de un personaje)
  ├─ character_id, equipment_item_id (o drink_id/recipe_id si es comida/bebida comprada,
  │                           o custom_name si no viene de ningún catálogo - exactamente uno de los tres)
  ├─ quality, quantity
  ├─ location                 (una de las 5 ubicaciones: equipamiento/mochila_saco/alforjas/base/altdorf)
  └─ condition                (reservado para una futura fase de desgaste/reparación - sin usar hoy)

character_cart_items         (línea pendiente de pagar - nunca guarda el precio: se recalcula desde
  ├─ character_id, equipment_item_id  equipment_item.price_for_quality() en cada vista y en el checkout,
  ├─ quality, quantity                para que un cambio de nivel_social entre añadir y pagar no quede obsoleto.
  └─ location                         Solo Equipamiento - la compra de comida/bebida es directa, sin carrito)

character_purchases          (historial inmutable - nunca se edita ni se borra tras crearse)
  ├─ character_id, equipment_item_id (o drink_id/recipe_id si es comida/bebida)
  ├─ item_name_snapshot, category_snapshot, quality_snapshot
  │                          (congela lo comprado aunque el catálogo cambie/borre después)
  ├─ precio_peniques_pagado  (0 para objetos concedidos por un admin o dados de alta sin coste; para
  │                           comida/bebida ya incluye el recargo global activo en el momento de comprar)
  ├─ granted_by_gm, granted_by_user_id
  └─ notes

shop_markup                  (fila única - recargo global % sobre las compras de comida/bebida,
  ├─ pct                      activable/desactivable por un admin "por disponibilidad u otras razones")
  ├─ updated_by_id
  └─ updated_at

character_money_grants       (historial inmutable de dinero concedido a mano - stand-in temporal
  ├─ character_id             mientras no existan sueldos/recompensas automáticos)
  ├─ peniques                 (importe añadido, siempre positivo)
  ├─ motivo                   (texto libre, p.ej. "Sueldo semanal")
  ├─ granted_by_user_id
  └─ created_at
```

`app/data/food/*.json` (`cooking_methods.json`, `ingredients.json`, `ingredient_compatibility.json`,
`recipes.json`, `drinks.json`): transcripción de las tablas del libro "Comida y bebida", usada como semilla
idempotente por `app/services/food_seed_service.py` (misma estrategia que el seed de `synonyms`: comprueba lo
que ya existe por nombre e inserta solo lo que falte, así que ampliar el catálogo en el futuro no duplica filas).
Los precios se guardan en peniques (`app/services/currency_service.py`: 1 Corona de oro = 20 Chelines de plata =
240 Peniques; 1 Chelín = 12 Peniques) y se formatean para mostrarse con el filtro de plantilla `food_money`.
Equipamiento reutiliza este mismo servicio (filtro `money`, alias de `food_money`) en vez de tener su propio
sistema de moneda — el dinero de un personaje (`Character.dinero_coronas`/`dinero_peniques_extra`) también se
guarda internamente en peniques.

### Regla de acumulación de características en el Buscador

Todas las características (primarias y secundarias) se acumulan de la misma forma: se muestra el **valor más alto** que ofrece cualquier profesión individual del camino. No se suman.

- **Perfil principal** (HA, HP, F, R, Ag, I, V, Em): mejoras en pasos de 5 %. Una profesión con +20 % en HA y otra con +10 % resulta en **+20 %** total (no +30 %).
- **Perfil secundario** (A, H, BF, BR, M, Mag, PL, PD): mejoras en pasos de 1 unidad. Una profesión con +2 Ataques y otra con +1 resulta en **+2** total (no +3).

### Grupos de elección (choice_group)

Cuando una profesión ofrece elegir entre habilidades o talentos (p.ej. "Juego **o** Chismear"), ambas se almacenan con el mismo número en el campo `choice_group`. En la interfaz se muestran separadas por la palabra **"o"**.

Las habilidades/talentos con `choice_group = NULL` son **obligatorias** (no hay elección).

El mismo mecanismo se aplica a las especializaciones: si una profesión permite "Hablar Idioma (Reikspiel **o** Tileano)", se almacenan dos filas de `profession_skills` para la misma habilidad, con el mismo `choice_group` y diferente `specialization`.

### Permisos y plantillas

Los permisos se implementan en tres niveles:

1. **Administrador** (`role = 'admin'`): acceso total sin restricciones.
2. **Plantilla** (`template_id`): asigna un conjunto predefinido de permisos a un usuario.
3. **Permisos directos** (`user_permissions`): permisos adicionales sobre la plantilla, asignados individualmente.

Los permisos efectivos de un usuario son la unión de los que vienen de su plantilla y los directos. La comprobación se realiza con `user.has_perm(code)` en el backend y con el decorador `@require_permission(code)` en las rutas que lo necesitan.

---

## Estructura del proyecto

```
WarhammerFantasyTools/
├── .env.example            # Plantilla de variables de entorno
├── .gitignore
├── docker-compose.yml      # Orquestación: app + MySQL
├── Dockerfile              # Imagen de la aplicación
├── entrypoint.sh           # Script de arranque: espera DB, migraciones, crea admin
├── requirements.txt        # Dependencias Python
├── run.py                  # Punto de entrada de la aplicación
└── app/
    ├── __init__.py         # Factory de la app Flask + comandos CLI (init-db, create-admin)
    ├── wsgi_prefix.py       # PrefixMiddleware: sirve la app bajo URL_PREFIX (p.ej. /wft)
    ├── config.py           # Configuraciones por entorno
    ├── extensions.py       # Instancias de extensiones Flask
    ├── utils.py            # Decoradores: admin_required, require_permission; helpers
    ├── data/
    │   ├── skill_specializations.json   # Especializaciones predefinidas por habilidad
    │   ├── talent_specializations.json  # Especializaciones predefinidas por talento
    │   ├── character_creation/          # Tablas de tiradas del Generador de Personaje (raza,
    │   │   └── *.json                   # profesión, características, procedencia, PH, etc.)
    │   └── food/                        # Semilla del catálogo de Comida y bebida (bebidas,
    │       └── *.json                   # ingredientes, métodos de cocina, recetas)
    ├── models/
    │   ├── __init__.py     # Exporta todos los modelos para Flask-Migrate
    │   ├── permission.py   # Permission, PermissionTemplate + tablas M2M + seed data
    │   ├── user.py         # Usuario: rol, has_perm(), effective_perm_codes()
    │   ├── profession.py   # Profesión, ProfessionSkill, ProfessionTalent, Trapping
    │   ├── skill.py        # Habilidad
    │   ├── talent.py       # Talento
    │   ├── character.py    # Personaje WFRP: características, trasfondo, carrera profesional,
    │   │                   # rasgos, contactos generados en creación, posesiones y objetos mágicos
    │   ├── synonym.py      # Diccionario de sinónimos para importación PDF
    │   ├── contact.py                  # Contact, ContactProfession (hechos globales del NPC)
    │   ├── contact_character_link.py   # ContactCharacterLink
    │   ├── contact_note.py             # ContactNote (por personaje)
    │   ├── food.py                     # CookingMethod, Ingredient, IngredientCookingMethod, Recipe, Drink
    │   ├── equipment.py    # EquipmentItem, CharacterInventoryItem, CharacterCartItem, CharacterPurchase
    │   └── shop.py         # ShopMarkup: recargo global (%) sobre las compras de comida/bebida
    ├── routes/
    │   ├── auth.py         # Login, registro, logout
    │   ├── main.py         # Página de inicio, errores, servicio de uploads
    │   ├── professions.py  # CRUD de profesiones (edición requiere professions.edit)
    │   ├── skills_talents.py  # CRUD de habilidades y talentos (edición requiere skills.edit)
    │   ├── pathfinder.py   # Buscador de caminos
    │   ├── characters.py   # Gestión de personajes WFRP + tienda/carrito/inventario/historial de compras
    │   ├── contacts.py     # Vistas de usuario de Contactos (listado, ficha, carrera+sueldo, vínculo/notas por personaje)
    │   ├── admin.py        # Panel admin: usuarios, permisos, plantillas, PDF, Contactos (listado/import-export),
    │   │                   # recargo global de precios
    │   ├── food.py         # Comida y bebida: bebidas, recetas, ingredientes, métodos de cocina, normas,
    │   │                   # y su compra directa vinculada a un personaje
    │   └── equipment.py    # Catálogo (menús por categoría + completo), edición en bloque, export/import
    ├── services/
    │   ├── pdf_processor.py      # OCR, traducción y parsing de PDFs
    │   ├── translation_service.py # Detección de idioma y traducción
    │   ├── import_service.py     # Importación/exportación de habilidades y talentos
    │   ├── pathfinder_service.py  # Construcción del grafo y BFS
    │   ├── contact_import_service.py  # Importación/exportación Excel de Contactos (columnas fijas)
    │   ├── salary_service.py     # Tabla de referencia de sueldos (Contactos y Personajes)
    │   ├── character_creation_service.py  # Tiradas del Generador de Personaje (dados, tablas porcentuales)
    │   ├── currency_service.py   # Conversión/formateo Coronas de oro / Chelines de plata / Peniques
    │   ├── food_seed_service.py  # Siembra idempotente del catálogo de Comida y bebida desde app/data/food/
    │   ├── recipe_calc_service.py  # Cálculo de vigor/moral/coste/precio/duración/complejidad de una receta
    │   ├── food_pdf_service.py    # Admin: parsea PDFs de "recetas hechas" (con foto) y sincroniza fotos
    │   │                          # sueltas en uploads/imagenes_comidas/ con el catálogo
    │   └── backup_service.py     # Export/import JSON: Profesiones, Usuarios, Equipamiento, Personajes,
    │                             # Plantillas, Sinónimos, Contactos+Vínculos, y el orquestador de Backup completo
    ├── templates/
    │   ├── base.html             # Layout base con nav adaptativo
    │   ├── admin/
    │   │   ├── dashboard.html
    │   │   ├── users.html                # Lista de usuarios con plantilla y acciones
    │   │   ├── user_new.html             # Alta de usuario con contraseña temporal
    │   │   ├── user_edit.html            # Edición de permisos por usuario
    │   │   ├── permission_templates.html # Lista de plantillas de permisos
    │   │   ├── template_edit.html        # Crear/editar plantilla
    │   │   ├── synonyms.html
    │   │   ├── pdf_upload.html
    │   │   ├── pdf_review.html
    │   │   ├── contacts.html             # Listado/administración de contactos
    │   │   ├── contacts_import.html
    │   │   ├── contacts_export.html
    │   │   ├── recipes_pending.html        # Cola de recetas propuestas pendientes de revisión
    │   │   └── recipe_review.html          # Ficha de revisión: valores calculados + subir imagen + aprobar/rechazar/eliminar
    │   ├── food/
    │   │   ├── recipe_form.html    # Proponer receta: método/ingredientes/condimentos filtrados por compatibilidad
    │   │   ├── recipe_detail.html  # Ficha de receta: botón Eliminar visible solo para administradores
    │   │   └── my_recipes.html     # Estado (pendiente/aprobada/rechazada) de las propias propuestas
    │   ├── contacts/
    │   │   ├── index.html         # Listado global (miniatura, raza, Unter, estado, nº vínculos)
    │   │   ├── detail.html        # Ficha: datos globales, vínculo del personaje activo, "Personajes con relación"
    │   │   ├── new.html           # Alta de contacto (admin-only)
    │   │   ├── edit.html          # Edición de contacto (admin-only)
    │   │   └── vinculos.html      # Directorio de vínculos (propio por defecto, "Ver todos" amplía)
    │   ├── equipment/
    │   │   ├── list.html          # Catálogo (menú por categoría + completo), filtros, cabecera de contexto
    │   │   ├── detail.html        # Ficha de un objeto
    │   │   ├── form.html          # Crear/editar objeto (stats/custom_fields dinámicos, imagen)
    │   │   ├── bulk_fields.html   # Editor de campos en bloque sobre un conjunto filtrado
    │   │   ├── import.html
    │   │   └── _macros.html       # equipment_card (tarjeta reutilizada en catálogo y tienda), stats_table
    │   ├── characters/
    │   │   ├── tienda.html                    # Catálogo de compra de un personaje (arma/armadura/municion/ropa)
    │   │   ├── anadir_carrito_confirmar.html  # Elegir calidad/cantidad/ubicación antes de añadir al carrito
    │   │   ├── carrito.html                   # Revisar/quitar líneas y finalizar compra
    │   │   ├── inventario.html                # Equipo del personaje por ubicación de almacenaje
    │   │   ├── historial_compras.html         # Registro inmutable de compras/concesiones
    │   │   ├── conceder_especial.html         # Admin: conceder un objeto especial directamente
    │   │   └── conceder_dinero.html            # Admin: añadir dinero directamente a la cuenta
    │   └── ...                   # Resto de plantillas por módulo
    └── static/
        ├── css/custom.css               # Tema oscuro medieval WH
        ├── js/main.js                   # Scripts del cliente (incluye drag-reorder y toggles de Contactos)
        └── js/profession_picker.js      # Buscador de profesión con salidas de carrera resaltadas (creación de personajes)
```
