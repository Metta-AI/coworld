"""Fixed-destination TCP relay for a controller outside an isolated episode network."""

import asyncio
import sys


async def copy_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while chunk := await reader.read(65536):
        writer.write(chunk)
        await writer.drain()
    writer.close()


async def serve(host: str, port: int) -> None:
    async def connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            async with asyncio.timeout(10):
                upstream_reader, upstream_writer = await asyncio.open_connection(host, port)
            try:
                await asyncio.gather(copy_stream(reader, upstream_writer), copy_stream(upstream_reader, writer))
            finally:
                upstream_writer.close()
        finally:
            writer.close()

    server = await asyncio.start_server(connection, "0.0.0.0", port)
    async with server:
        await server.serve_forever()


async def main() -> None:
    await asyncio.gather(*(serve(sys.argv[1], int(port)) for port in sys.argv[2:]))


if __name__ == "__main__":
    asyncio.run(main())
