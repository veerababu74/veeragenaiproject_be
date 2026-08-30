import certifi
from pymongo import AsyncMongoClient

from .config import settings


client = AsyncMongoClient(
    settings.mongodb_url,
    serverSelectionTimeoutMS=5_000,
    tlsCAFile=certifi.where(),
)
database = client[settings.mongodb_database]
users = database.users
landing_content = database.landing_content
project_catalog = database.project_catalog
blogs = database.blogs


async def close_database():
    await client.close()