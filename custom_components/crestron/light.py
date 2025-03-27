"""Platform for Crestron Light integration."""
import voluptuous as vol
import logging

import homeassistant.helpers.config_validation as cv
from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.util import slugify
from homeassistant.const import CONF_NAME
from .const import HUB, DOMAIN, CONF_BRIGHTNESS_JOIN, CONF_BRIGHTNESS_DEFAULT

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_BRIGHTNESS_JOIN): cv.positive_int,
        vol.Optional(CONF_BRIGHTNESS_DEFAULT, default=128): cv.positive_int,
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    hub = hass.data[DOMAIN][HUB]
    entity = [CrestronLight(hub, config)]
    async_add_entities(entity)


class CrestronLight(LightEntity):
    def __init__(self, hub, config):
        self._hub = hub
        self._name = config.get(CONF_NAME)
        self._brightness_join = config.get(CONF_BRIGHTNESS_JOIN)
        self._default_brightness = config.get(CONF_BRIGHTNESS_DEFAULT)
        self._attr_color_mode = ColorMode.BRIGHTNESS
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
        self._unique_id = slugify(f"{DOMAIN}_light_{self._name}")

    async def async_added_to_hass(self):
        self._hub.register_callback(self.process_callback)

    async def async_will_remove_from_hass(self):
        self._hub.remove_callback(self.process_callback)

    async def process_callback(self, cbtype, value):
        self.async_write_ha_state()

    @property
    def available(self):
        return self._hub.is_available()

    @property
    def name(self):
        return self._name

    @property
    def should_poll(self):
        return False

    @property
    def brightness(self):
        return int(self._hub.get_analog(self._brightness_join) / 257)

    @property
    def is_on(self):
        return bool(self.brightness)

    @property
    def unique_id(self):
        return self._unique_id

    async def async_turn_on(self, **kwargs):
        if ATTR_BRIGHTNESS in kwargs:
            self._hub.set_analog(self._brightness_join, int(kwargs[ATTR_BRIGHTNESS] * 257))
        else:
            self._hub.set_analog(self._brightness_join, self._default_brightness * 257)

    async def async_turn_off(self, **kwargs):
        self._hub.set_analog(self._brightness_join, 0)
