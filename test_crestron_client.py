import asyncio
import struct
import logging
import argparse

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


class CrestronTestClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.reader = None
        self.writer = None
        self.connected = False

    async def connect(self):
        """Connect to the server"""
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.connected = True
            _LOGGER.info(f"Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            _LOGGER.error(f"Could not connect: {e}")
            return False

    async def disconnect(self):
        """Disconnect from the server"""
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            self.connected = False
            _LOGGER.info("Disconnected from server")

    async def send_digital(self, join, value):
        """Send digital join"""
        if not self.connected:
            _LOGGER.error("Not connected to server")
            return

        data = struct.pack(
            ">BB",
            0b10000000 | (~value << 5 & 0b00100000) | (join - 1) >> 7,
            (join - 1) & 0b01111111,
        )
        self.writer.write(data)
        await self.writer.drain()
        _LOGGER.info(f"Sent digital join {join} = {value}")

    async def send_analog(self, join, value):
        """Send analog join"""
        if not self.connected:
            _LOGGER.error("Not connected to server")
            return

        data = struct.pack(
            ">BBBB",
            0b11000000 | (value >> 10 & 0b00110000) | (join - 1) >> 7,
            (join - 1) & 0b01111111,
            value >> 7 & 0b01111111,
            value & 0b01111111,
        )
        self.writer.write(data)
        await self.writer.drain()
        _LOGGER.info(f"Sent analog join {join} = {value}")

    async def send_serial(self, join, string):
        """Send serial join"""
        if not self.connected:
            _LOGGER.error("Not connected to server")
            return

        if len(string) > 252:
            _LOGGER.error(f"String too long ({len(string)}>252)")
            return

        data = struct.pack(
            ">BB", 0b11001000 | ((join - 1) >> 7), (join - 1) & 0b01111111
        )
        data += string.encode()
        data += b"\xff"
        _LOGGER.info(f"Sending serial data: {data.hex()}")
        self.writer.write(data)
        await self.writer.drain()
        _LOGGER.info(f"Sent serial join {join} = {string}")

    async def request_update(self):
        """Request update of all joins"""
        if not self.connected:
            _LOGGER.error("Not connected to server")
            return

        self.writer.write(b"\xfd")
        await self.writer.drain()
        _LOGGER.info("Sent update request")

    async def listen(self):
        """Listen for received messages"""
        while self.connected:
            try:
                data = await self.reader.read(1)
                if not data:
                    _LOGGER.warning("No data received, disconnecting")
                    break

                _LOGGER.info(f"Received raw data: {data.hex()}")

                # Handle different message types
                if data[0] == 0xFB:
                    _LOGGER.info("Received update request")
                elif data[0] == 0xC8:  # Serial data
                    _LOGGER.info("Received serial data header")
                    data += await self.reader.read(1)
                    _LOGGER.info(f"Received complete serial packet: {data.hex()}")
                else:
                    data += await self.reader.read(1)
                    _LOGGER.info(f"Received complete packet: {data.hex()}")

            except Exception as e:
                _LOGGER.error(f"Error while listening: {e}")
                break


async def main(args):
    client = CrestronTestClient(args.host, args.port)

    # Connect to server
    if not await client.connect():
        return

    # Start listening in background
    listen_task = asyncio.create_task(client.listen())

    try:
        if args.digital:
            join, value = args.digital
            await client.send_digital(join, value)
            await asyncio.sleep(args.delay)

        if args.analog:
            join, value = args.analog
            await client.send_analog(join, value)
            await asyncio.sleep(args.delay)

        if args.serial:
            join, text = args.serial
            await client.send_serial(join, text)
            await asyncio.sleep(args.delay)

        if args.update:
            await client.request_update()

        # Wait to see received messages
        await asyncio.sleep(args.wait)

    except KeyboardInterrupt:
        _LOGGER.info("Shutting down...")
    finally:
        await client.disconnect()
        listen_task.cancel()


def parse_join_value(value_str):
    """Parse join and value from string format 'join:value'"""
    try:
        join, value = value_str.split(':')
        return int(join), int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid format. Use 'join:value' (e.g. '1:1')")


def parse_join_text(value_str):
    """Parse join and text from string format 'join:text'"""
    try:
        join, text = value_str.split(':', 1)
        return int(join), text
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid format. Use 'join:text' (e.g. '1:Hello')")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Crestron XSIG Test Client')
    parser.add_argument('host', help='Host to connect to')
    parser.add_argument('--port', type=int, default=16384, help='Port to connect to (default: 16384)')
    parser.add_argument('--digital', type=parse_join_value, help='Send digital join (format: join:value, e.g. 1:1)')
    parser.add_argument('--analog', type=parse_join_value, help='Send analog join (format: join:value, e.g. 1:250)')
    parser.add_argument('--serial', type=parse_join_text, help='Send serial join (format: join:text, e.g. 1:Hello)')
    parser.add_argument('--update', action='store_true', help='Request update of all joins')
    parser.add_argument('--delay', type=float, default=1.0, help='Delay between operations (default: 1.0)')
    parser.add_argument('--wait', type=float, default=5.0, help='Wait time after operations (default: 5.0)')

    args = parser.parse_args()
    asyncio.run(main(args))
