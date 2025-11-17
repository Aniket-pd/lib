"""Simple usage example for the Portal Python client."""

import asyncio

from portal_sdk import PortalSDK


async def main() -> None:
    client = PortalSDK("ws://localhost:3000/ws")
    await client.connect()
    await client.authenticate("your-auth-token")

    url = await client.newKeyHandshakeUrl(lambda main_key, relays: print(main_key, relays))
    print("Handshake URL:", url)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
