from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings
import logging

logger = logging.getLogger("kagazastra")

class Database:
    client: AsyncIOMotorClient = None
    db = None

db_instance = Database()

async def connect_to_mongo():
    try:
        db_instance.client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=2000)
        db_instance.db = db_instance.client[settings.DATABASE_NAME]
        # Ping mongo
        await db_instance.client.admin.command('ping')
        logger.info("MongoDB connection established successfully.")
    except Exception as e:
        if db_instance.client:
            db_instance.client.close()
        db_instance.client = None
        db_instance.db = None
        logger.warning(
            "MongoDB connection failed. Account and panel features require a reachable database. "
            "Error type: %s",
            type(e).__name__,
        )

async def close_mongo_connection():
    if db_instance.client:
        db_instance.client.close()
        logger.info("MongoDB connection closed.")

def get_database():
    return db_instance.db
