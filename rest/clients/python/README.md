# Portal SDK - Python Client

A Python client for the Portal WebSocket server. The implementation mirrors the TypeScript SDK that lives in [`rest/clients/ts`](../ts) including its method names and streaming patterns.

## Installation

```bash
pip install -e .
```

## Usage

```python
import asyncio
from portal_sdk import PortalSDK, Currency, Timestamp

async def main():
    client = PortalSDK("ws://localhost:3000/ws")
    await client.connect()
    await client.authenticate("your-auth-token")

    async def on_status(status):
        print("status:", status)

    await client.requestSinglePayment(
        main_key="user-pubkey",
        subkeys=[],
        payment_request={
            "description": "Example",
            "amount": 1000,
            "currency": Currency.Millisats,
        },
        on_status_change=lambda status: print(status)
    )

    await client.disconnect()

asyncio.run(main())
```

See [`portal_sdk/client.py`](portal_sdk/client.py) for the full API surface.
