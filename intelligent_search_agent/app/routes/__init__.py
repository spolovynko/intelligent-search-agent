from intelligent_search_agent.app.routes.admin import router as admin_router
from intelligent_search_agent.app.routes.assets import router as assets_router
from intelligent_search_agent.app.routes.chat import router as chat_router
from intelligent_search_agent.app.routes.documents import router as documents_router
from intelligent_search_agent.app.routes.meetings import router as meetings_router
from intelligent_search_agent.app.routes.search import router as search_router

__all__ = [
    "admin_router",
    "assets_router",
    "chat_router",
    "documents_router",
    "meetings_router",
    "search_router",
]
