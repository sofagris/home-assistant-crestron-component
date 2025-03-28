"""The Crestron Integration Component"""

import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import TrackTemplate, async_track_template_result
from homeassistant.helpers.template import Template
from homeassistant.helpers.script import Script
from homeassistant.core import callback, Context
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    CONF_VALUE_TEMPLATE,
    CONF_ATTRIBUTE,
    CONF_ENTITY_ID,
    STATE_ON,
    STATE_OFF,
    CONF_SERVICE,
    CONF_SERVICE_DATA,
)

from .crestron import CrestronXsig
from .const import CONF_PORT, HUB, DOMAIN, CONF_JOIN, CONF_SCRIPT, CONF_TO_HUB, CONF_FROM_HUB, CONF_VALUE_JOIN, CONF_SET_DIGITAL, CONF_SET_ANALOG, CONF_SET_SERIAL

_LOGGER = logging.getLogger(__name__)

TO_JOINS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_JOIN): cv.string,
        vol.Optional(CONF_ENTITY_ID): cv.entity_id,
        vol.Optional(CONF_ATTRIBUTE): cv.string,
        vol.Optional(CONF_VALUE_TEMPLATE): cv.template
    }
)

FROM_JOINS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_JOIN): cv.string,
        vol.Required(CONF_SCRIPT): cv.SCRIPT_SCHEMA
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PORT): cv.port,
                vol.Optional(CONF_TO_HUB): vol.All(cv.ensure_list, [TO_JOINS_SCHEMA]),
                vol.Optional(CONF_FROM_HUB): vol.All(cv.ensure_list, [FROM_JOINS_SCHEMA])
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

SET_DIGITAL_SCHEME = vol.Schema(
    {
        vol.Required(CONF_JOIN): cv.positive_int,
        vol.Required(CONF_VALUE_JOIN): cv.boolean
    }
)

SET_ANALOG_SCHEME = vol.Schema(
    {
        vol.Required(CONF_JOIN): cv.positive_int,
        vol.Required(CONF_VALUE_JOIN): int
    }
)

SET_SERIAL_SCHEME = vol.Schema(
    {
        vol.Required(CONF_JOIN): cv.positive_int,
        vol.Required(CONF_VALUE_JOIN): cv.string
    }
)


async def async_setup(hass, config):
    """Set up the crestron component."""
    print("Crestron setup started")  # Basic print for debugging
    _LOGGER.critical("Crestron setup started")  # Critical level to ensure it shows up
    try:
        _LOGGER.info("Starting Crestron integration setup")
        if config.get(DOMAIN) is not None:
            _LOGGER.info("Crestron configuration found")
            hass.data[DOMAIN] = {}
            hub = CrestronHub(hass, config[DOMAIN])

            _LOGGER.info("Starting Crestron hub")
            await hub.start()
            _LOGGER.info("Crestron hub started successfully")
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, hub.stop)

            # Last plattformer som er konfigurert
            platforms = ["binary_sensor", "sensor", "switch", "light", "cover", "media_player", "climate"]
            for platform in platforms:
                if platform in config:
                    _LOGGER.info(f"Loading platform: {platform}")
                    hass.async_create_task(
                        async_load_platform(hass, platform, DOMAIN, {}, config)
                    )

            return True
        else:
            _LOGGER.error("No Crestron configuration found")
            return False
    except Exception as err:
        _LOGGER.error("Error setting up Crestron integration: %s", err, exc_info=True)
        return False


class CrestronHub:
    """Wrapper for the CrestronXsig library."""
    def __init__(self, hass, config):
        print("CrestronHub init started")  # Basic print for debugging
        _LOGGER.critical("CrestronHub init started")  # Critical level to ensure it shows up
        self.hass = hass
        self.hub = hass.data[DOMAIN][HUB] = CrestronXsig()
        self.port = config.get(CONF_PORT)
        _LOGGER.info(f"CrestronHub initialized with port {self.port}")
        self.context = Context()
        self.to_hub = {}
        self.from_hub = []
        self.tracker = None

        if CONF_TO_HUB in config:
            _LOGGER.info("Configuring to_hub")
            self.hub.register_sync_all_joins_callback(self.sync_joins_to_hub)
            track_templates = []
            for entity in config[CONF_TO_HUB]:
                template_string = None
                if CONF_VALUE_TEMPLATE in entity:
                    template = entity[CONF_VALUE_TEMPLATE]
                    self.to_hub[entity[CONF_JOIN]] = template
                    track_templates.append(TrackTemplate(template, None))
                elif CONF_ATTRIBUTE in entity and CONF_ENTITY_ID in entity:
                    template_string = (
                        "{{state_attr('"
                        + entity[CONF_ENTITY_ID]
                        + "','"
                        + entity[CONF_ATTRIBUTE]
                        + "')}}"
                    )
                    template = Template(template_string, hass)
                    self.to_hub[entity[CONF_JOIN]] = template
                    track_templates.append(TrackTemplate(template, None))
                elif CONF_ENTITY_ID in entity:
                    template_string = "{{states('" + entity[CONF_ENTITY_ID] + "')}}"
                    template = Template(template_string, hass)
                    self.to_hub[entity[CONF_JOIN]] = template
                    track_templates.append(TrackTemplate(template, None))
            if track_templates:
                self.tracker = async_track_template_result(
                    self.hass, track_templates, self.template_change_callback
                )

        if CONF_FROM_HUB in config:
            _LOGGER.info("Configuring from_hub")
            self.from_hub = config[CONF_FROM_HUB]
            self.hub.register_callback(self.join_change_callback)

        async def async_set_digital(call):
            _LOGGER.debug(
                f"async_service_callback setting digital join {call.data[CONF_JOIN]} to {call.data[CONF_VALUE_JOIN]}"
            )
            self.hub.set_digital(call.data[CONF_JOIN], call.data[CONF_VALUE_JOIN])

        self.hass.services.async_register(
            DOMAIN,
            CONF_SET_DIGITAL,
            async_set_digital,
            schema=SET_DIGITAL_SCHEME,
        )

        async def async_set_analog(call):
            _LOGGER.debug(
                f"async_service_callback setting analog join {call.data[CONF_JOIN]} to {call.data[CONF_VALUE_JOIN]}"
            )
            self.hub.set_analog(call.data[CONF_JOIN], call.data[CONF_VALUE_JOIN])

        self.hass.services.async_register(
            DOMAIN,
            CONF_SET_ANALOG,
            async_set_analog,
            schema=SET_ANALOG_SCHEME,
        )

        async def async_set_serial(call):
            _LOGGER.debug(
                f"async_service_callback setting serial join {call.data[CONF_JOIN]} to {call.data[CONF_VALUE_JOIN]}"
            )
            self.hub.set_serial(call.data[CONF_JOIN], str(call.data[CONF_VALUE_JOIN]))

        self.hass.services.async_register(
            DOMAIN,
            CONF_SET_SERIAL,
            async_set_serial,
            schema=SET_SERIAL_SCHEME,
        )

    async def start(self):
        """Start the Crestron hub."""
        print("Starting Crestron hub")  # Basic print for debugging
        _LOGGER.critical("Starting Crestron hub")  # Critical level to ensure it shows up
        try:
            _LOGGER.info(f"Attempting to start server on port {self.port}")
            await self.hub.listen(self.port)
            _LOGGER.info("Server started successfully")
        except Exception as e:
            _LOGGER.error(f"Failed to start server: {e}", exc_info=True)
            raise

    async def stop(self, event):
        """Remove callback(s) and template trackers."""
        print("Stopping Crestron hub")  # Basic print for debugging
        _LOGGER.critical("Stopping Crestron hub")  # Critical level to ensure it shows up
        try:
            self.hub.remove_callback(self.join_change_callback)
            if hasattr(self, 'tracker'):
                self.tracker.async_remove()
            await self.hub.stop()
            _LOGGER.info("Crestron hub stopped successfully")
        except Exception as e:
            _LOGGER.error(f"Error stopping hub: {e}", exc_info=True)

    async def join_change_callback(self, cbtype, value):
        """ Call service for tracked join change (from_hub)"""
        for join in self.from_hub:
            if cbtype == join[CONF_JOIN]:
                # For digital joins, ignore on>off transitions  (avoids double calls to service for momentary presses)
                if cbtype[:1] == "d" and value == "0":
                    pass
                else:
                    if CONF_SERVICE in join and CONF_SERVICE_DATA in join:
                        data = dict(join[CONF_SERVICE_DATA])
                        _LOGGER.debug(
                            f"join_change_callback calling service {join[CONF_SERVICE]} with data = {data} from join {cbtype} = {value}"
                        )
                        domain, service = join[CONF_SERVICE].split(".")
                        await self.hass.services.async_call(domain, service, data)
                    elif CONF_SCRIPT in join:
                        sequence = join[CONF_SCRIPT]
                        script = Script(
                            self.hass, sequence, "Crestron Join Change", DOMAIN
                        )
                        await script.async_run({"value": value}, self.context)
                        _LOGGER.debug(
                            f"join_change_callback calling script {join[CONF_SCRIPT]} from join {cbtype} = {value}"
                        )

    @callback
    def template_change_callback(self, event, updates):
        """ Set join from value_template (to_hub)"""
        # track_template_result = updates.pop()
        for track_template_result in updates:
            update_result = track_template_result.result
            update_template = track_template_result.template
            if update_result != "None":
                for join, template in self.to_hub.items():
                    if template == update_template:
                        _LOGGER.debug(
                            f"processing template_change_callback for join {join} with result {update_result}"
                        )
                        # Digital Join
                        if join[:1] == "d":
                            value = None
                            if update_result == STATE_ON or update_result == "True" or update_result is True:
                                value = True
                            elif update_result == STATE_OFF or update_result == "False" or update_result is False:
                                value = False
                            if value is not None:
                                _LOGGER.debug(
                                    f"template_change_callback setting digital join {int(join[1:])} to {value}"
                                )
                                self.hub.set_digital(int(join[1:]), value)
                        # Analog Join
                        if join[:1] == "a":
                            _LOGGER.debug(
                                f"template_change_callback setting analog join {int(join[1:])} to {int(update_result)}"
                            )
                            self.hub.set_analog(int(join[1:]), int(update_result))
                        # Serial Join
                        if join[:1] == "s":
                            _LOGGER.debug(
                                f"template_change_callback setting serial join {int(join[1:])} to {str(update_result)}"
                            )
                            self.hub.set_serial(int(join[1:]), str(update_result))

    async def sync_joins_to_hub(self):
        """Sync all joins to hub"""
        try:
            for join in self.to_hub:
                template = self.to_hub[join]
                try:
                    # Evaluate the template
                    result = template.async_render()
                    if result is None or result == "unknown":
                        _LOGGER.warning(f"Skipping sync for join {join} with value {result}")
                        continue

                    if join.startswith("d"):
                        # Handle digital joins
                        value = None
                        if result == STATE_ON or result == "True" or result is True:
                            value = True
                        elif result == STATE_OFF or result == "False" or result is False:
                            value = False
                        if value is not None:
                            _LOGGER.debug(f"sync_joins_to_hub setting digital join {int(join[1:])} to {value}")
                            self.hub.set_digital(int(join[1:]), value)
                    elif join.startswith("a"):
                        # Handle analog joins
                        try:
                            value = int(result)
                            _LOGGER.debug(f"sync_joins_to_hub setting analog join {int(join[1:])} to {value}")
                            self.hub.set_analog(int(join[1:]), value)
                        except (ValueError, TypeError) as e:
                            _LOGGER.error(f"Invalid analog value for join {join}: {result}")
                    elif join.startswith("s"):
                        # Handle serial joins
                        value = str(result)
                        _LOGGER.debug(f"sync_joins_to_hub setting serial join {int(join[1:])} to {value}")
                        self.hub.set_serial(int(join[1:]), value)
                except Exception as e:
                    _LOGGER.error(f"Error processing join {join}: {e}")
                    continue

        except Exception as e:
            _LOGGER.error(f"Error in sync_joins_to_hub: {e}")
            raise
