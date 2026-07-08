"""Import all models here so Alembic's autogenerate and Base.metadata see them."""
from app.models.connection import Connection
from app.models.conversation import ConversationTurn
from app.models.fcm_token import FcmToken
from app.models.goal import Goal
from app.models.memory import Memory
from app.models.notification import Notification
from app.models.profile import UserProfile
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
    "UserProfile",
    "PushSubscription",
    "Connection",
    "FcmToken",
    "Goal",
]
