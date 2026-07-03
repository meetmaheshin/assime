"""Import all models here so Alembic's autogenerate and Base.metadata see them."""
from app.models.conversation import ConversationTurn
from app.models.memory import Memory
from app.models.notification import Notification
from app.models.project import Project
from app.models.push import PushSubscription
from app.models.task import Task, TaskHistory
from app.models.user import User

__all__ = [
    "User",
    "Project",
    "Task",
    "TaskHistory",
    "Memory",
    "ConversationTurn",
    "Notification",
    "PushSubscription",
]
