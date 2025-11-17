"""Asynchronous WebSocket client for the Portal REST server."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional, cast

from websockets.client import WebSocketClientProtocol, connect

from .types import (
    AuthResponseData,
    CashuResponseStatus,
    CloseRecurringPaymentNotification,
    Currency,
    EventCallbacks,
    InvoicePaymentRequestContent,
    InvoiceResponseContent,
    InvoiceStatus,
    NotificationData,
    Profile,
    RecurringPaymentRequestContent,
    RecurringPaymentResponseContent,
    Response,
    SinglePaymentRequestContent,
    Timestamp,
)

LOGGER = logging.getLogger(__name__)
_MISSING = object()


class PortalSDKError(RuntimeError):
    """Custom error raised by the Portal SDK."""


class PortalSDK:
    """Python implementation of the Portal WebSocket client mirroring the TypeScript SDK."""

    def __init__(self, server_url: str, connect_timeout: float = 10.0) -> None:
        self.server_url = server_url
        self.connect_timeout = connect_timeout
        self._socket: Optional[WebSocketClientProtocol] = None
        self._connected = False
        self._receive_task: Optional[asyncio.Task[None]] = None
        self._command_futures: Dict[str, asyncio.Future[Any]] = {}
        self._event_listeners: Dict[str, List[Callable[[Any], None]]] = {}
        self._event_callbacks: EventCallbacks = {}
        self._active_streams: Dict[str, Callable[[NotificationData], None]] = {}

    async def connect(self) -> None:
        """Establish the WebSocket connection."""

        if self._connected:
            return

        try:
            self._socket = await asyncio.wait_for(connect(self.server_url), self.connect_timeout)
        except Exception as exc:  # pragma: no cover - network error
            raise PortalSDKError(f"Failed to connect to {self.server_url}: {exc}") from exc

        self._connected = True
        self._receive_task = asyncio.create_task(self._receive_loop())

        callback = self._event_callbacks.get("onConnected")
        if callback:
            callback()

    async def disconnect(self) -> None:
        """Close the WebSocket connection and clean up."""

        if self._receive_task:
            self._receive_task.cancel()
            with contextlib.suppress(Exception):
                await self._receive_task
            self._receive_task = None

        if self._socket and self._connected:
            await self._socket.close()

        self._socket = None
        self._connected = False
        self._active_streams.clear()
        self._command_futures.clear()
        self._event_listeners.clear()

        callback = self._event_callbacks.get("onDisconnected")
        if callback:
            callback()

    async def sendCommand(self, cmd: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Send a command to the server and await the response."""

        if not self._connected or not self._socket:
            raise PortalSDKError("Not connected to server")

        command_id = uuid.uuid4().hex
        payload: Dict[str, Any] = {"id": command_id, "cmd": cmd}
        if params:
            payload["params"] = self._serialize(params)

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._command_futures[command_id] = future

        try:
            await self._socket.send(json.dumps(payload))
        except Exception as exc:
            self._command_futures.pop(command_id, None)
            future.set_exception(exc)
            raise PortalSDKError(f"Failed to send command {cmd}") from exc

        return await future

    def on(self, event_type_or_callbacks: Any, callback: Optional[Callable[[Any], None]] = None) -> None:
        """Register event listeners or callbacks."""

        if isinstance(event_type_or_callbacks, dict) and callback is None:
            self._event_callbacks.update(event_type_or_callbacks)
            return

        if not isinstance(event_type_or_callbacks, str) or callback is None:
            raise ValueError("Provide an event type and a callback")

        listeners = self._event_listeners.setdefault(event_type_or_callbacks, [])
        listeners.append(callback)

    def off(self, event_type: str, callback: Callable[[Any], None]) -> None:
        """Remove a registered event listener."""

        listeners = self._event_listeners.get(event_type)
        if not listeners:
            return

        with contextlib.suppress(ValueError):
            listeners.remove(callback)

    async def authenticate(self, token: str) -> None:
        response = await self.sendCommand("Auth", {"token": token})
        if response.get("type") != "auth_success":
            raise PortalSDKError(f"Authentication failed: {response}")

    async def newKeyHandshakeUrl(
        self,
        onKeyHandshake: Callable[[str, List[str]], None],
        static_token: Optional[str] = None,
        no_request: Optional[bool] = None,
    ) -> str:
        stream_id_holder = {"value": ""}

        def handler(notification: NotificationData) -> None:
            if notification.get("type") == "key_handshake":
                onKeyHandshake(notification["main_key"], notification.get("preferred_relays", []))
                self._active_streams.pop(stream_id_holder["value"], None)

        response = await self.sendCommand(
            "NewKeyHandshakeUrl",
            {"static_token": static_token, "no_request": no_request},
        )

        if response.get("type") != "key_handshake_url":
            raise PortalSDKError("Unexpected response for NewKeyHandshakeUrl")

        stream_id = response["stream_id"]
        stream_id_holder["value"] = stream_id
        self._active_streams[stream_id] = handler
        return response["url"]

    async def authenticateKey(self, main_key: str, subkeys: Optional[List[str]] = None) -> AuthResponseData:
        response = await self.sendCommand(
            "AuthenticateKey",
            {"main_key": main_key, "subkeys": subkeys or []},
        )
        if response.get("type") != "auth_response":
            raise PortalSDKError("Unexpected response for AuthenticateKey")
        return response["event"]

    async def requestRecurringPayment(
        self,
        main_key: str,
        subkeys: Optional[List[str]] = None,
        payment_request: RecurringPaymentRequestContent = cast(
            RecurringPaymentRequestContent, _MISSING
        ),
    ) -> RecurringPaymentResponseContent:
        if payment_request is _MISSING:
            raise TypeError("payment_request is required")
        payment = cast(RecurringPaymentRequestContent, payment_request)
        response = await self.sendCommand(
            "RequestRecurringPayment",
            {
                "main_key": main_key,
                "subkeys": subkeys or [],
                "payment_request": payment,
            },
        )
        if response.get("type") != "recurring_payment":
            raise PortalSDKError("Unexpected response for RequestRecurringPayment")
        return response["status"]

    async def requestSinglePayment(
        self,
        main_key: str,
        subkeys: Optional[List[str]] = None,
        payment_request: SinglePaymentRequestContent = cast(
            SinglePaymentRequestContent, _MISSING
        ),
        on_status_change: Callable[[InvoiceStatus], None] = cast(
            Callable[[InvoiceStatus], None], _MISSING
        ),
    ) -> None:
        if payment_request is _MISSING:
            raise TypeError("payment_request is required")
        if on_status_change is _MISSING:
            raise TypeError("on_status_change is required")
        payment = cast(SinglePaymentRequestContent, payment_request)
        status_callback = cast(Callable[[InvoiceStatus], None], on_status_change)
        stream_id_holder = {"value": ""}

        def handler(notification: NotificationData) -> None:
            if notification.get("type") == "payment_status_update":
                status_callback(notification["status"])
                status = notification["status"].get("status")
                if status in {"user_failed", "user_rejected"}:
                    self._active_streams.pop(stream_id_holder["value"], None)

        response = await self.sendCommand(
            "RequestSinglePayment",
            {
                "main_key": main_key,
                "subkeys": subkeys or [],
                "payment_request": payment,
            },
        )

        if response.get("type") != "single_payment":
            raise PortalSDKError("Unexpected response for RequestSinglePayment")

        stream_id_holder["value"] = response["stream_id"]
        self._active_streams[stream_id_holder["value"]] = handler

    async def requestInvoicePayment(
        self,
        main_key: str,
        subkeys: Optional[List[str]] = None,
        payment_request: InvoicePaymentRequestContent = cast(
            InvoicePaymentRequestContent, _MISSING
        ),
        on_status_change: Callable[[InvoiceStatus], None] = cast(
            Callable[[InvoiceStatus], None], _MISSING
        ),
    ) -> None:
        if payment_request is _MISSING:
            raise TypeError("payment_request is required")
        if on_status_change is _MISSING:
            raise TypeError("on_status_change is required")
        payment = cast(InvoicePaymentRequestContent, payment_request)
        status_callback = cast(Callable[[InvoiceStatus], None], on_status_change)
        stream_id_holder = {"value": ""}

        def handler(notification: NotificationData) -> None:
            if notification.get("type") == "payment_status_update":
                status_callback(notification["status"])
                status = notification["status"].get("status")
                if status in {"user_failed", "user_rejected"}:
                    self._active_streams.pop(stream_id_holder["value"], None)

        response = await self.sendCommand(
            "RequestPaymentRaw",
            {
                "main_key": main_key,
                "subkeys": subkeys or [],
                "payment_request": payment,
            },
        )
        if response.get("type") != "single_payment":
            raise PortalSDKError("Unexpected response for RequestPaymentRaw")

        stream_id_holder["value"] = response["stream_id"]
        self._active_streams[stream_id_holder["value"]] = handler

    async def fetchProfile(self, main_key: str) -> Optional[Profile]:
        response = await self.sendCommand("FetchProfile", {"main_key": main_key})
        if response.get("type") != "profile":
            raise PortalSDKError("Unexpected response for FetchProfile")
        return response["profile"]

    async def setProfile(self, profile: Profile) -> None:
        await self.sendCommand("SetProfile", {"profile": profile})

    async def closeRecurringPayment(
        self,
        main_key: str,
        subkeys: Optional[List[str]] = None,
        subscription_id: str = cast(str, _MISSING),
    ) -> str:
        if subscription_id is _MISSING:
            raise TypeError("subscription_id is required")
        subscription = cast(str, subscription_id)
        response = await self.sendCommand(
            "CloseRecurringPayment",
            {"main_key": main_key, "subkeys": subkeys or [], "subscription_id": subscription},
        )
        if response.get("type") != "close_recurring_payment_success":
            raise PortalSDKError("Unexpected response for CloseRecurringPayment")
        return response["message"]

    async def listenClosedRecurringPayment(
        self, on_closed: Callable[[CloseRecurringPaymentNotification], None]
    ) -> None:
        def handler(notification: NotificationData) -> None:
            if notification.get("type") == "closed_recurring_payment":
                on_closed(
                    {
                        "reason": notification.get("reason"),
                        "subscription_id": notification["subscription_id"],
                        "main_key": notification["main_key"],
                        "recipient": notification["recipient"],
                    }
                )

        response = await self.sendCommand("ListenClosedRecurringPayment")
        if response.get("type") != "listen_closed_recurring_payment":
            raise PortalSDKError("Unexpected response for ListenClosedRecurringPayment")
        self._active_streams[response["stream_id"]] = handler

    async def requestInvoice(
        self, recipient_key: str, content: InvoicePaymentRequestContent
    ) -> InvoiceResponseContent:
        response = await self.sendCommand(
            "RequestInvoice",
            {"recipient_key": recipient_key, "content": content},
        )
        if response.get("type") != "invoice_payment":
            raise PortalSDKError("Unexpected response for RequestInvoice")
        return {"invoice": response["invoice"], "payment_hash": response["payment_hash"]}

    async def issueJwt(self, target_key: str, duration_hours: int) -> str:
        response = await self.sendCommand(
            "IssueJwt", {"target_key": target_key, "duration_hours": duration_hours}
        )
        if response.get("type") != "issue_jwt":
            raise PortalSDKError("Unexpected response for IssueJwt")
        return response["token"]

    async def verifyJwt(self, public_key: str, token: str) -> Dict[str, str]:
        response = await self.sendCommand("VerifyJwt", {"pubkey": public_key, "token": token})
        if response.get("type") != "verify_jwt":
            raise PortalSDKError("Unexpected response for VerifyJwt")
        return {"target_key": response["target_key"]}

    async def requestCashu(
        self,
        recipient_key: str,
        subkeys: List[str],
        mint_url: str,
        unit: str,
        amount: int,
    ) -> CashuResponseStatus:
        response = await self.sendCommand(
            "RequestCashu",
            {
                "recipient_key": recipient_key,
                "subkeys": subkeys,
                "mint_url": mint_url,
                "unit": unit,
                "amount": amount,
            },
        )
        if response.get("type") != "cashu_response":
            raise PortalSDKError("Unexpected response for RequestCashu")
        return response["status"]

    async def sendCashuDirect(self, main_key: str, subkeys: List[str], token: str) -> str:
        response = await self.sendCommand(
            "SendCashuDirect", {"main_key": main_key, "subkeys": subkeys, "token": token}
        )
        if response.get("type") != "send_cashu_direct_success":
            raise PortalSDKError("Unexpected response for SendCashuDirect")
        return response["message"]

    async def mintCashu(
        self,
        mint_url: str,
        static_auth_token: Optional[str],
        unit: str,
        amount: int,
        description: Optional[str] = None,
    ) -> str:
        response = await self.sendCommand(
            "MintCashu",
            {
                "mint_url": mint_url,
                "static_auth_token": static_auth_token,
                "unit": unit,
                "amount": amount,
                "description": description,
            },
        )
        if response.get("type") != "cashu_mint":
            raise PortalSDKError("Unexpected response for MintCashu")
        return response["token"]

    async def burnCashu(
        self, mint_url: str, unit: str, token: str, static_auth_token: Optional[str] = None
    ) -> int:
        response = await self.sendCommand(
            "BurnCashu",
            {
                "mint_url": mint_url,
                "unit": unit,
                "token": token,
                "static_auth_token": static_auth_token,
            },
        )
        if response.get("type") != "cashu_burn":
            raise PortalSDKError("Unexpected response for BurnCashu")
        return response["amount"]

    async def addRelay(self, relay: str) -> str:
        response = await self.sendCommand("AddRelay", {"relay": relay})
        if response.get("type") != "add_relay":
            raise PortalSDKError("Unexpected response for AddRelay")
        return response["relay"]

    async def removeRelay(self, relay: str) -> str:
        response = await self.sendCommand("RemoveRelay", {"relay": relay})
        if response.get("type") != "remove_relay":
            raise PortalSDKError("Unexpected response for RemoveRelay")
        return response["relay"]

    async def _receive_loop(self) -> None:
        assert self._socket is not None
        try:
            async for message in self._socket:
                await self._handle_message(message)
        except asyncio.CancelledError:  # pragma: no cover - task cancellation
            raise
        except Exception as exc:  # pragma: no cover - network failure
            LOGGER.error("WebSocket receive loop error: %s", exc)
            callback = self._event_callbacks.get("onError")
            if callback:
                callback(exc)
        finally:
            self._connected = False
            callback = self._event_callbacks.get("onDisconnected")
            if callback:
                callback()

    async def _handle_message(self, raw_message: Any) -> None:
        try:
            data: Response = json.loads(raw_message)
        except json.JSONDecodeError as exc:  # pragma: no cover - invalid payload
            LOGGER.warning("Failed to decode message: %s", exc)
            return

        if "id" in data:
            response_type = data.get("type")
            if response_type == "notification":
                handler = self._active_streams.get(data["id"])
                if handler:
                    handler(data["data"])
                else:
                    LOGGER.debug("No handler for stream %s", data["id"])
                return

            future = self._command_futures.pop(data["id"], None)
            if not future:
                LOGGER.debug("No callback for id %s", data["id"])
                return

            if response_type == "error":
                future.set_exception(PortalSDKError(data.get("message", "Unknown error")))
            elif response_type == "success":
                future.set_result(data.get("data"))
            return

        event_type = data.get("type") if isinstance(data, dict) else None
        if event_type and event_type in self._event_listeners:
            for listener in list(self._event_listeners[event_type]):
                listener(data.get("data"))

        for listener in self._event_listeners.get("all", []):
            listener(data)

    def _serialize(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Timestamp):
            return value.to_json()
        if isinstance(value, Currency):
            return value.value
        if is_dataclass(value):
            return {k: self._serialize(v) for k, v in asdict(value).items()}
        if isinstance(value, dict):
            return {k: self._serialize(v) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [self._serialize(v) for v in value]
        return value


__all__ = ["PortalSDK", "PortalSDKError"]
