"""Type definitions for the Portal Python client."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, TypedDict, Union


class Currency(str, Enum):
    """Supported currency units (mirrors the TypeScript enum)."""

    Millisats = "Millisats"


@dataclass
class Timestamp:
    """Chrono style timestamp helper used by the API."""

    value: int

    @classmethod
    def from_date(cls, value: datetime) -> "Timestamp":
        return cls(int(value.replace(tzinfo=timezone.utc).timestamp()))

    @classmethod
    def from_datetime(cls, value: datetime) -> "Timestamp":
        return cls.from_date(value)

    @classmethod
    def from_now(cls, seconds: int) -> "Timestamp":
        return cls(int(datetime.now(tz=timezone.utc).timestamp()) + seconds)

    def __int__(self) -> int:  # pragma: no cover - trivial
        return self.value

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)

    def to_json(self) -> str:
        return str(self.value)


@dataclass
class RecurrenceInfo:
    calendar: str
    first_payment_due: Timestamp
    until: Optional[Timestamp] = None
    max_payments: Optional[int] = None


@dataclass
class RecurringPaymentRequestContent:
    amount: int
    currency: Currency
    recurrence: RecurrenceInfo
    expires_at: Timestamp
    current_exchange_rate: Optional[Any] = None
    auth_token: Optional[str] = None


@dataclass
class InvoicePaymentRequestContent:
    amount: int
    currency: Currency
    description: str
    subscription_id: Optional[str] = None
    auth_token: Optional[str] = None
    current_exchange_rate: Optional[Any] = None
    expires_at: Optional[Timestamp] = None
    invoice: Optional[str] = None


@dataclass
class SinglePaymentRequestContent:
    description: str
    amount: int
    currency: Currency
    subscription_id: Optional[str] = None
    auth_token: Optional[str] = None


@dataclass
class RecurringPaymentStatusContent:
    subscription_id: str
    authorized_amount: int
    authorized_currency: Currency
    authorized_recurrence: RecurrenceInfo


@dataclass
class RecurringPaymentResponseContent:
    request_id: str
    status: RecurringPaymentStatusContent


class InvoiceStatus(TypedDict, total=False):
    status: Literal[
        "paid",
        "timeout",
        "error",
        "user_approved",
        "user_success",
        "user_failed",
        "user_rejected",
    ]
    preimage: Optional[str]
    reason: Optional[str]


class AuthResponseStatus(TypedDict, total=False):
    status: Literal["approved", "declined"]
    reason: Optional[str]
    granted_permissions: Optional[List[str]]
    session_token: Optional[str]


class AuthResponseData(TypedDict):
    user_key: str
    recipient: str
    challenge: str
    status: AuthResponseStatus


class Profile(TypedDict, total=False):
    id: str
    pubkey: str
    name: Optional[str]
    display_name: Optional[str]
    picture: Optional[str]
    about: Optional[str]
    nip05: Optional[str]


class InvoiceResponseContent(TypedDict):
    invoice: str
    payment_hash: Optional[str]


class Event(TypedDict):
    type: str
    data: Any


class CashuRequestContent(TypedDict):
    request_id: str
    mint_url: str
    unit: str
    amount: int


class CashuRequestContentWithKey(TypedDict):
    inner: CashuRequestContent
    main_key: str
    recipient: str


class CashuResponseStatusSuccess(TypedDict):
    status: Literal["success"]
    token: str


class CashuResponseStatusInsufficient(TypedDict):
    status: Literal["insufficient_funds"]


class CashuResponseStatusRejected(TypedDict, total=False):
    status: Literal["rejected"]
    reason: Optional[str]


CashuResponseStatus = Union[
    CashuResponseStatusSuccess,
    CashuResponseStatusInsufficient,
    CashuResponseStatusRejected,
]


class CloseRecurringPaymentNotification(TypedDict):
    reason: Optional[str]
    subscription_id: str
    main_key: str
    recipient: str


class NotificationKeyHandshake(TypedDict):
    type: Literal["key_handshake"]
    main_key: str
    preferred_relays: List[str]


class NotificationPaymentStatus(TypedDict):
    type: Literal["payment_status_update"]
    status: InvoiceStatus


class NotificationClosedRecurringPayment(TypedDict):
    type: Literal["closed_recurring_payment"]
    reason: Optional[str]
    subscription_id: str
    main_key: str
    recipient: str


class NotificationCashuRequest(TypedDict):
    type: Literal["cashu_request"]
    request: CashuRequestContentWithKey


NotificationData = Union[
    NotificationKeyHandshake,
    NotificationPaymentStatus,
    NotificationClosedRecurringPayment,
    NotificationCashuRequest,
]


class ResponseSuccess(TypedDict):
    type: Literal["success"]
    id: str
    data: Any


class ResponseError(TypedDict):
    type: Literal["error"]
    id: str
    message: str


class ResponseNotification(TypedDict):
    type: Literal["notification"]
    id: str
    data: NotificationData


Response = Union[ResponseSuccess, ResponseError, ResponseNotification]


class EventCallbacks(TypedDict, total=False):
    onKeyHandshake: Callable[[str], None]
    onError: Callable[[Exception], None]
    onConnected: Callable[[], None]
    onDisconnected: Callable[[], None]


CommandParams = Dict[str, Any]


class Command(TypedDict, total=False):
    id: str
    cmd: str
    params: CommandParams
