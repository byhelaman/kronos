# create_test_user.py
import asyncio
import uuid
from sqlalchemy.future import select

# Importamos los módulos que ya creaste
from database import AsyncSessionLocal
from db_models import User
from security import get_password_hash

# --- Configura tus datos aquí ---
TEST_USERNAME = "admin"
TEST_PASSWORD = "admin"
TEST_FULLNAME = "Admin"
# --------------------------------

async def create_user():
    print("Iniciando creación de usuario...")

    # Usamos la sesión de BD de tu archivo database.py
    async with AsyncSessionLocal() as db:

        # 1. Comprobar si ya existe
        query = select(User).where(User.username == TEST_USERNAME)
        result = await db.execute(query)
        existing_user = result.scalar_one_or_none()

        if existing_user:
            print(f"El usuario '{TEST_USERNAME}' ya existe.")
            return

        # 2. Si no existe, hashear la contraseña
        # Usamos la función de tu archivo security.py
        hashed_pass = get_password_hash(TEST_PASSWORD)

        # 3. Crear el nuevo objeto User (basado en db_models.py)
        new_user = User(
            id=str(uuid.uuid4()), # El ID debe ser un string
            username=TEST_USERNAME,
            full_name=TEST_FULLNAME,
            hashed_password=hashed_pass
        )

        # 4. Guardar en la BD
        db.add(new_user)
        await db.commit()

        print(f"¡Usuario '{TEST_USERNAME}' creado exitosamente!")
        print("Puedes iniciar sesión con él ahora.")

if __name__ == "__main__":
    # Importante: Este script asume que las tablas ya fueron 
    # creadas por el 'lifespan' de main.py al menos una vez.
    print("Conectando a la base de datos...")
    asyncio.run(create_user())