from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import connect_to_mongo, close_mongo_connection
from app.api.endpoints import router as api_router, router as files_router
from app.services.auth import auth_router, initialize_auth
from app.api.panels import router as panels_router
import os
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
app = FastAPI(
    title=settings.APP_NAME,
    description="The Zero-Upload Document Super-App for Indian Students, Aspirants & Offices",
    version="3.0-PROD"
)

# CORS Middleware - Allow frontend to call backend APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CORS Middleware - Allow frontend to call backend APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CORS Middleware - Allow frontend to call backend APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("app/static", exist_ok=True)
os.makedirs("app/templates", exist_ok=True)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

@app.on_event("startup")
async def startup_event():
    await connect_to_mongo()
    from app.database import get_database

    database = get_database()
    if database is not None:
        await initialize_auth(database)

@app.on_event("shutdown")
async def shutdown_event():
    await close_mongo_connection()

app.include_router(api_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(files_router, prefix="/api")  # File management
app.include_router(panels_router, prefix="/api")

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={"app_name": settings.APP_NAME}
    )


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})


@app.get("/client")
async def client_panel(request: Request):
    return templates.TemplateResponse(request=request, name="client.html", context={})


@app.get("/admin")
async def admin_panel(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html", context={})