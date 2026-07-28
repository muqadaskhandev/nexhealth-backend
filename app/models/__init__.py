"""ORM models package.

Importing this package ensures every model is registered on Base.metadata,
which Alembic autogenerate and create_all rely on.
"""
from app.models.appointment_types import AppointmentTypeDef, InsertionRule, MappingRule, PatientTypeRule
from app.models.booking_form import BookingFieldType, BookingFormField, BookingInsurance
from app.models.communications import (
    CommunicationTemplate,
    CommunicationTemplateStep,
    TemplateCategory,
    TemplateConfiguration,
    TemplateStepKind,
)
from app.models.ehr_connection import ConnectionMode, EhrConnection, EhrSyncLog
from app.models.invite import InviteToken, InviteType
from app.models.location import Location, UserLocation
from app.models.practice import (
    DEFAULT_PRODUCTS,
    EhrSystem,
    Practice,
    SubscriptionPlan,
    SyncStatus,
)
from app.models.providers import AvailabilityBlock, AvailabilitySlot, Operatory, Provider, ProviderStatus, RepeatMode
from app.models.staff import (
    ActivityType,
    Appointment,
    AppointmentStatus,
    FormRequest,
    FormSubmission,
    FormTemplate,
    Message,
    MessageThread,
    Patient,
    PatientActivity,
    PaymentLink,
    WaitlistEntry,
)
from app.models.token import PasswordResetToken, RefreshToken, SsoTotpTransaction
from app.models.user import AccountType, AuthProvider, User, UserRole
from app.models.waitlist import WaitlistRequest, WaitlistRequestPatient, WaitlistRequestSlot, WaitlistRequestStatus

__all__ = [
    "User",
    "UserRole",
    "AccountType",
    "AuthProvider",
    "Location",
    "UserLocation",
    "Practice",
    "SubscriptionPlan",
    "EhrSystem",
    "SyncStatus",
    "DEFAULT_PRODUCTS",
    "EhrConnection",
    "EhrSyncLog",
    "ConnectionMode",
    "InviteToken",
    "InviteType",
    "RefreshToken",
    "PasswordResetToken",
    "SsoTotpTransaction",
]
