from fastapi import FastAPI
from .database import seed_database
from .routes.auth import router as auth_router
from .routes.profiles import router as profiles_router
from .routes.suppliers import router as suppliers_router
from .routes.users import router as users_router

app = FastAPI(
    title="TrackFlow - Supplier Directory API",
    version="1.0.0",
    description="API RESTful para la gestión del directorio de proveedores",
)


@app.on_event("startup")
async def startup_event():
    seed_database()


# Incluimos las rutas de proveedores requeridas por la rúbrica
app.include_router(suppliers_router)
app.include_router(users_router)
app.include_router(auth_router)
app.include_router(profiles_router)