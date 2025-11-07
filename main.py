# main.py
import asyncio
from fastapi import (
    FastAPI,
    Request,
    UploadFile,
    File,
    Form,
    Depends,
    HTTPException,
    status,
)
from starlette.middleware.gzip import GZipMiddleware
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
)
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from typing import List, Dict, Any, Optional

from database import get_db  # NUEVO
from sqlalchemy.ext.asyncio import AsyncSession  # NUEVO

# Importamos los módulos que ya creamos
from database import engine, AsyncSessionLocal, Base
import db_models
from security import get_password_hash

import config
import security
import schedule_service
import file_processing
from contextlib import asynccontextmanager
import response_generators
import auth  # NUEVO
import zoom_oauth  # NUEVO
from auth import User  # NUEVO
from database import engine, Base

from session_middleware import RedisSessionMiddleware


# --- NUEVO: Lifespan para la Base de Datos ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona la conexión de la base de datos durante el ciclo de vida de la app.
    """
    print("Iniciando pool de conexión...")
    async with engine.begin() as conn:
        # En un entorno de desarrollo, puedes crear las tablas aquí.
        # En producción, deberías usar Alembic (ver Paso 10).
        # await conn.run_sync(Base.metadata.drop_all) # Borra todo (cuidado)
        await conn.run_sync(Base.metadata.create_all)
        print("Tablas creadas (si no existían).")

    yield  # Aquí es donde la aplicación se ejecuta

    print("Cerrando pool de conexión...")
    await engine.dispose()  # Cierra las conexiones al apagar


# app = FastAPI()
app = FastAPI(lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Configuración de Rate Limiter
app.state.limiter = security.limiter
app.add_exception_handler(RateLimitExceeded, security.rate_limit_handler)

# Montar archivos estáticos y plantillas
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(RedisSessionMiddleware, templates=templates)

# --- Endpoints de Autenticación (NUEVOS) ---


@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    token = security.get_or_create_csrf_token(request.state.session)
    # Asumimos que tienes una plantilla "login.html"
    return templates.TemplateResponse(
        "login.html", {"request": request, "csrf_token": token}
    )


@app.post("/login", response_class=RedirectResponse)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    # En la vida real, usa OAuth2PasswordRequestForm
    # No validamos CSRF aquí porque el login debe ser simple
    # pero en producción deberías añadirlo.
):
    user = await auth.authenticate_user(db, username, password)

    if not user:
        # Manejo de error (ej. redirigir de vuelta con error)
        return RedirectResponse(url="/login?error=1", status_code=303)

    # ¡Login exitoso! Guardamos el ID en la sesión
    request.state.session["user_id"] = user.id  # user.id ahora viene de la BD
    request.state.session["is_authenticated"] = True

    # Convertimos el modelo de BD a Pydantic para el estado
    request.state.user = auth.User.model_validate(user)
    request.state.is_authenticated = True

    return RedirectResponse(url="/profile", status_code=303)


@app.get("/logout", response_class=RedirectResponse)
async def logout(request: Request):
    # Marcamos al usuario como no autenticado
    request.state.session["user_id"] = None
    request.state.session["is_authenticated"] = False
    request.state.user = None
    request.state.is_authenticated = False

    # Opcional: Borrar toda la sesión de invitado también
    request.state.session_cleared = True

    return RedirectResponse(url="/", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
async def user_profile(
    request: Request, current_user: User = Depends(auth.get_current_active_user)
):
    """
    Página de perfil del usuario.
    Solo accesible para usuarios logueados (no invitados).
    """
    token = security.get_or_create_csrf_token(request.state.session)

    # Comprobamos si el usuario (de nuestra BD simulada) ya tiene tokens
    is_zoom_linked = bool(current_user.zoom_user_id)

    # Asumimos que tienes "profile.html"
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "csrf_token": token,
            "user": current_user,
            "is_zoom_linked": is_zoom_linked,
        },
    )


# --- Endpoints de Vinculación de Zoom (NUEVOS) ---


@app.get("/auth/zoom")
async def zoom_auth_start(
    request: Request, current_user: User = Depends(auth.get_current_active_user)
):
    """
    Paso 1: Iniciar la vinculación.
    """
    if not config.ZOOM_CLIENT_ID:
        raise HTTPException(500, "Zoom no está configurado en el servidor.")

    # 1. Obtener AMBOS valores de la función
    auth_url, code_verifier = zoom_oauth.get_zoom_auth_url()

    # 2. Guardar el verifier en la sesión ANTES de redirigir
    request.state.session["zoom_code_verifier"] = code_verifier

    return RedirectResponse(url=auth_url)


@app.get("/auth/zoom/callback")
async def zoom_auth_callback(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
    # Zoom nos devuelve esto en la URL
    # No podemos usar 'get_current_active_user' porque la sesión
    # puede ser distinta (viene de un redirect).
    # Confiamos en la sesión del middleware.
):
    """
    Paso 2: Callback de Zoom.
    El usuario es redirigido aquí después de autorizar en Zoom.
    """

    # Verificamos que el usuario esté logueado en nuestra app
    if not request.state.is_authenticated or not request.state.user:
        # Es un invitado o sesión expirada
        return RedirectResponse(url="/login?error=zoom_auth_failed", status_code=303)

    current_user = request.state.user

    # 1. Recuperar el verifier que guardamos en la sesión
    code_verifier = request.state.session.pop("zoom_code_verifier", None)

    if not code_verifier:
        # Esto pasa si la sesión expiró o hay un intento malicioso
        return RedirectResponse(
            url="/profile?error=zoom_session_expired", status_code=303
        )

    try:
        # Paso 3: Intercambiar el código por tokens
        token_data = await zoom_oauth.exchange_code_for_tokens(code, code_verifier)

        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]

        # Paso 4: Obtener el ID de usuario de Zoom
        zoom_user_info = await zoom_oauth.get_zoom_user_info(access_token)
        zoom_user_id = zoom_user_info["id"]

        # ¡MODIFICADO: Guardar en la BD!
        await auth.save_zoom_tokens_for_user(
            db=db,  # ¡Pasar la sesión de la BD!
            user_id=current_user.id,
            zoom_user_id=zoom_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    except Exception as e:
        print(f"Error en el callback de Zoom: {e}")
        return RedirectResponse(url="/profile?error=zoom_link_failed", status_code=303)

    return RedirectResponse(url="/profile?success=zoom_linked", status_code=303)


# --- Endpoints de la Aplicación (Sin cambios, ahora conscientes del auth) ---


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    token = security.get_or_create_csrf_token(request.state.session)
    # Ya no pasamos 'is_authenticated' o 'user', el
    # context processor global se encarga de eso.
    return templates.TemplateResponse(
        "index.html", {"request": request, "csrf_token": token}
    )


@app.get("/generate-schedule", response_class=HTMLResponse)
async def read_schedule(request: Request):
    """
    Este endpoint sigue funcionando para INVITADOS y USUARIOS LOGUEADOS.
    La lógica de 'schedule_data' está en la sesión de Redis,
    que es independiente de si el usuario está logueado o no.
    """
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    data_to_render = schedule_service.filter_active_rows(all_rows)
    num_deleted_rows = schedule_service.get_deleted_rows_count(all_rows)

    token = security.get_or_create_csrf_token(request.state.session)
    upload_errors = request.state.session.pop("upload_errors", [])

    return templates.TemplateResponse(
        "generate-schedule.html",
        {
            "request": request,
            "title": "Generate Schedule",
            "description": "Extract the schedule information",
            "data": data_to_render,
            "num_deleted": num_deleted_rows,
            "csrf_token": token,
            "upload_errors": upload_errors,
        },
    )


# ... (El resto de tus endpoints: /generate-schedule POST, /upload-new, etc.
#      NO necesitan cambios, ya que todos operan sobre
#      request.state.session["schedule_data"], lo cual funciona
#      perfectamente tanto para invitados como para usuarios logueados.)

# ... (Pegar aquí el resto de endpoints de main.py sin modificar)


@app.post("/generate-schedule", response_class=RedirectResponse)
@security.limiter.limit("10/minute")
async def generate_schedule(
    request: Request,
    files: List[UploadFile] = File(...),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])
    processed_files_set = set(schedule_data.get("processed_files", []))

    newly_processed_files = []
    upload_errors = []

    for file in files:
        if file.filename in processed_files_set:
            continue

        content = await file.read()

        # 1. Validar archivo (Lógica en file_processing)
        error = file_processing.validate_file(file, content)
        if error:
            upload_errors.append(error)
            continue

        # 2. Parsear archivo (Lógica en file_processing)
        try:
            new_schedules = await file_processing.process_single_file(file, content)

            # 3. Fusionar datos (Lógica en schedule_service)
            all_rows = schedule_service.merge_new_schedules(all_rows, new_schedules)

            newly_processed_files.append(file.filename)

        except Exception as e:
            print(f"Error processing file {file.filename}: {e}")
            upload_errors.append(f"Error al procesar: {file.filename}")

    # 4. Actualizar estado de la sesión
    processed_files_set.update(newly_processed_files)
    schedule_data["processed_files"] = list(processed_files_set)
    schedule_data["all_rows"] = all_rows

    request.state.session["schedule_data"] = schedule_data
    request.state.session["upload_errors"] = upload_errors

    return RedirectResponse(url="/generate-schedule", status_code=303)


@app.get("/upload-new", response_class=HTMLResponse)
async def show_upload_form(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    schedule_data["processed_files"] = []
    request.state.session["schedule_data"] = schedule_data

    token = security.get_or_create_csrf_token(request.state.session)

    return templates.TemplateResponse(
        "generate-schedule.html",
        {
            "request": request,
            "title": "Upload New Files",
            "description": "Add new files to the existing schedule",
            "data": None,
            "show_cancel": True,
            "csrf_token": token,
        },
    )


@app.post("/delete-rows", response_class=JSONResponse)
@security.limiter.limit("30/minute")
async def delete_selected_rows(
    request: Request,
    selected_ids: str = Form(...),
    is_csrf_valid: bool = Depends(security.validate_csrf),
):
    if len(selected_ids) > config.MAX_SELECTED_IDS_LENGTH:
        return JSONResponse(
            {"success": False, "message": "Payload too large."}, status_code=413
        )
    try:
        ids_to_delete = {str(i) for i in selected_ids.split(",")}
    except ValueError:
        return JSONResponse(
            {"success": False, "message": "Invalid ID format."}, status_code=400
        )

    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    # Usar el servicio para la lógica de borrado
    all_rows, deleted_count = schedule_service.delete_rows_by_id(
        all_rows, ids_to_delete
    )

    # Lógica de sesión restante
    if not schedule_service.filter_active_rows(all_rows):
        schedule_data["processed_files"] = []

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    return JSONResponse({"success": True, "message": f"Deleted {deleted_count} rows."})


@app.post("/restore-rows", response_class=JSONResponse)
@security.limiter.limit("30/minute")
async def restore_deleted_rows(
    request: Request, is_csrf_valid: bool = Depends(security.validate_csrf)
):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    if not all_rows:
        return JSONResponse({"success": True, "message": "No data to restore."})

    # Usar el servicio para la lógica de restauración
    all_rows, restored_count = schedule_service.restore_deleted_rows(all_rows)

    schedule_data["all_rows"] = all_rows
    request.state.session["schedule_data"] = schedule_data

    return JSONResponse(
        {"success": True, "message": f"Restored {restored_count} rows."}
    )


@app.post("/delete-data", response_class=JSONResponse)
@security.limiter.limit("10/minute")
async def delete_data(
    request: Request, is_csrf_valid: bool = Depends(security.validate_csrf)
):
    # Usar el servicio para obtener un estado vacío
    request.state.session["schedule_data"] = schedule_service.get_empty_schedule_data()
    # request.state.session_cleared = True
    return JSONResponse({"success": True, "message": "All data cleared."})


@app.get("/schedule")
@security.limiter.limit("60/minute")
async def get_schedule_tsv(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    active_rows = schedule_service.filter_active_rows(all_rows)
    active_rows_data = [row["data"] for row in active_rows]

    # Usar el generador de respuestas
    return response_generators.generate_tsv_response(active_rows_data)


@app.get("/download-excel")
@security.limiter.limit("30/minute")
async def download_excel(request: Request):
    schedule_data = request.state.session.get(
        "schedule_data", schedule_service.get_empty_schedule_data()
    )
    all_rows = schedule_data.get("all_rows", [])

    active_rows = schedule_service.filter_active_rows(all_rows)
    active_rows_data = [row["data"] for row in active_rows]

    # Usar el generador de respuestas
    return response_generators.generate_excel_response(active_rows_data)
