import asyncio
import struct
import logging

_LOGGER = logging.getLogger(__name__)


class CrestronXsig:
    def __init__(self):
        """ Initialize CrestronXsig object """
        self._digital = {}
        self._analog = {}
        self._serial = {}
        self._writer = None
        self._callbacks = set()
        self._server = None
        self._available = False
        self._sync_all_joins_callback = None
        _LOGGER.critical("CrestronXsig initialized")

    async def listen(self, port):
        """ Start TCP XSIG server listening on configured port """
        try:
            _LOGGER.critical(f"Starting server on port {port}")
            server = await asyncio.start_server(self.handle_connection, "0.0.0.0", port)
            self._server = server
            addr = server.sockets[0].getsockname()
            _LOGGER.critical(f"Server started successfully, listening on {addr}:{port}")
            asyncio.create_task(server.serve_forever())
        except Exception as e:
            _LOGGER.critical(f"Failed to start server: {e}", exc_info=True)
            raise

    async def stop(self):
        """ Stop TCP XSIG server """
        try:
            _LOGGER.critical("Stopping server...")
            self._available = False
            for callback in self._callbacks:
                await callback("available", "False")
            _LOGGER.critical("Closing server connection")
            self._server.close()
            _LOGGER.critical("Server stopped successfully")
        except Exception as e:
            _LOGGER.critical(f"Error stopping server: {e}", exc_info=True)

    def register_sync_all_joins_callback(self, callback):
        """ Allow callback to be registred for when control system requests an update to all joins """
        _LOGGER.debug("Sync-all-joins callback registered")
        self._sync_all_joins_callback = callback

    def register_callback(self, callback):
        """ Allow callbacks to be registered for when dict entries change """
        self._callbacks.add(callback)

    def remove_callback(self, callback):
        """ Allow callbacks to be de-registered """
        self._callbacks.discard(callback)

    async def handle_connection(self, reader, writer):
        """ Parse packets from Crestron XSIG symbol """
        try:
            self._writer = writer
            peer = writer.get_extra_info("peername")
            _LOGGER.critical(f"New connection from {peer}")
            self._available = True
            for callback in self._callbacks:
                await callback("available", "True")

            _LOGGER.critical("Sending update request to control system")
            writer.write(b"\xfd")
            connected = True
            while connected:
                data = await reader.read(1)
                if data:
                    _LOGGER.critical(f"Received raw data: {data.hex()}")
                    # Sync all joins request
                    if data[0] == 0xFB:
                        _LOGGER.critical("Received update all joins request")
                        if self._sync_all_joins_callback is not None:
                            try:
                                _LOGGER.critical("Executing sync-all-joins callback")
                                await self._sync_all_joins_callback()
                            except ValueError as e:
                                _LOGGER.error(f"Error in sync callback: {e}")
                                # Continue running even if sync fails
                                continue
                    else:
                        data += await reader.read(1)
                        _LOGGER.critical(f"Received complete packet: {data.hex()}")
                        # Digital Join
                        if (
                            data[0] & 0b11000000 == 0b10000000
                            and data[1] & 0b10000000 == 0b00000000
                        ):
                            header = struct.unpack("BB", data)
                            join = ((header[0] & 0b00011111) << 7 | header[1]) + 1
                            value = ~header[0] >> 5 & 0b1
                            self._digital[join] = True if value == 1 else False
                            _LOGGER.critical(f"Received Digital Join: {join} = {value}")
                            for callback in self._callbacks:
                                await callback(f"d{join}", str(value))
                        # Analog Join
                        elif (
                            data[0] & 0b11001000 == 0b11000000
                            and data[1] & 0b10000000 == 0b00000000
                        ):
                            data += await reader.read(2)
                            header = struct.unpack("BBBB", data)
                            join = ((header[0] & 0b00000111) << 7 | header[1]) + 1
                            value = (
                                (header[0] & 0b00110000) << 10 | header[2] << 7 | header[3]
                            )
                            self._analog[join] = value
                            _LOGGER.critical(f"Received Analog Join: {join} = {value}")
                            for callback in self._callbacks:
                                await callback(f"a{join}", str(value))
                        # Serial Join
                        elif (
                            data[0] & 0b11001000 == 0b11001000
                            and data[1] & 0b10000000 == 0b00000000
                        ):
                            data += await reader.read(1)
                            header = struct.unpack("BBB", data)
                            join = ((header[0] & 0b00000111) << 7 | header[1]) + 1
                            length = header[2]
                            data = await reader.read(length)
                            value = data.decode("ascii")
                            self._serial[join] = value
                            _LOGGER.critical(f"Received Serial Join: {join} = {value}")
                            for callback in self._callbacks:
                                await callback(f"s{join}", value)
                else:
                    _LOGGER.warning("No data received, connection might be closed")
                    connected = False
        except Exception as e:
            _LOGGER.error(f"Error in handle_connection: {e}", exc_info=True)
        finally:
            _LOGGER.info("Closing connection")
            writer.close()
            await writer.wait_closed()
            self._available = False
            for callback in self._callbacks:
                await callback("available", "False")

    def is_available(self):
        """Returns True if control system is connected"""
        return self._available

    def get_analog(self, join):
        """ Return analog value for join"""
        return self._analog.get(join, 0)

    def get_digital(self, join):
        """ Return digital value for join"""
        return self._digital.get(join, False)

    def get_serial(self, join):
        """ Return serial value for join"""
        return self._serial.get(join, "")

    def set_analog(self, join, value):
        """ Send Analog Join to Crestron XSIG symbol """
        if self._writer:
            data = struct.pack(
                ">BBBB",
                0b11000000 | (value >> 10 & 0b00110000) | (join - 1) >> 7,
                (join - 1) & 0b01111111,
                value >> 7 & 0b01111111,
                value & 0b01111111,
            )
            self._writer.write(data)
            _LOGGER.debug(f"Sending Analog: {join}, {value}")
        else:
            _LOGGER.info("Could not send.  No connection to hub")

    def set_digital(self, join, value):
        """ Send Digital Join to Crestron XSIG symbol """
        if self._writer:
            data = struct.pack(
                ">BB",
                0b10000000 | (~value << 5 & 0b00100000) | (join - 1) >> 7,
                (join - 1) & 0b01111111,
            )
            self._writer.write(data)
            _LOGGER.debug(f"Sending Digital: {join}, {value}")
        else:
            _LOGGER.info("Could not send.  No connection to hub")

    def set_serial(self, join, string):
        """ Send String Join to Crestron XSIG symbol """
        if len(string) > 252:
            _LOGGER.info(f"Could not send. String too long ({len(string)}>252)")
            return
        elif self._writer:
            data = struct.pack(
                ">BB", 0b11001000 | ((join - 1) >> 7), (join - 1) & 0b01111111
            )
            data += string.encode()
            data += b"\xff"
            self._writer.write(data)
            _LOGGER.debug(f"Sending Serial: {join}, {string}")
        else:
            _LOGGER.info("Could not send.  No connection to hub")
