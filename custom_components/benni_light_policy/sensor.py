"""Sensor-Plattform: Mode, Scene-Hash, Brightness/CCT-Target, Preset-Enum, Plan, Debug."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DATA_COORDINATOR,
    DOMAIN,
    OBJID_MODE,
    OBJID_PLAN,
    UID_BRIGHTNESS,
    UID_COLOR_TEMP,
    UID_DEBUG,
    UID_MODE,
    UID_PLAN,
    UID_PRESET_ENUM,
    UID_RING_MODE,
    UID_SCENE_HASH,
    unique_id,
)
from .entity import LightPolicyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coord = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    async_add_entities([
        ModeSensor(coord, entry),
        SceneHashSensor(coord, entry),
        BrightnessTargetSensor(coord, entry),
        ColorTempTargetSensor(coord, entry),
        PresetEnumSensor(coord, entry),
        PlanSensor(coord, entry),
        RingModeSensor(coord, entry),
        DebugSensor(coord, entry),
    ])


class ModeSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_MODE)
        self._attr_name = "Living Room Mode"
        self._attr_suggested_object_id = OBJID_MODE

    @property
    def native_value(self):
        p = self.coord.last_plan
        return p.mode if p else None


class SceneHashSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:pound"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_SCENE_HASH)
        self._attr_name = "Living Room Scene Hash"
        self._attr_suggested_object_id = "living_room_scene_hash_combined"

    @property
    def native_value(self):
        p = self.coord.last_plan
        return p.scene_hash if p else None


class BrightnessTargetSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:brightness-6"
    _attr_native_unit_of_measurement = "bri"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_BRIGHTNESS)
        self._attr_name = "Living Room Brightness Target"
        self._attr_suggested_object_id = "living_room_brightness_target_combined"

    @property
    def native_value(self):
        p = self.coord.last_plan
        return p.brightness if p else None


class ColorTempTargetSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:temperature-kelvin"
    _attr_native_unit_of_measurement = "K"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_COLOR_TEMP)
        self._attr_name = "Living Room Color Temp Target"
        self._attr_suggested_object_id = "living_room_color_temp_target_combined"

    @property
    def native_value(self):
        p = self.coord.last_plan
        return p.color_temp if p else None


class PresetEnumSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:palette"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_PRESET_ENUM)
        self._attr_name = "Living Room Preset Enum"
        self._attr_suggested_object_id = "living_room_preset_combined"

    @property
    def native_value(self):
        p = self.coord.last_plan
        return (p.preset_enum or "none") if p else None


class PlanSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:clipboard-list-outline"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_PLAN)
        self._attr_name = "Living Room Plan"
        self._attr_suggested_object_id = OBJID_PLAN

    @property
    def native_value(self):
        p = self.coord.last_plan
        return p.mode if p else None

    @property
    def extra_state_attributes(self):
        p = self.coord.last_plan
        return p.as_dict() if p else {}


class RingModeSensor(LightPolicyEntity, SensorEntity):
    """R17: aktiv am T1M RGB Ring angezeigter Activity State."""

    _attr_icon = "mdi:circle-outline"

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_RING_MODE)
        self._attr_name = "Ring Mode"
        self._attr_suggested_object_id = "lights_ring_mode_combined"

    @property
    def native_value(self):
        return self.coord.ring_mode or self.coord.current_activity()


class DebugSensor(LightPolicyEntity, SensorEntity):
    _attr_icon = "mdi:bug-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coord, entry):
        super().__init__(coord, entry)
        self._attr_unique_id = unique_id(UID_DEBUG)
        self._attr_name = "Living Room Debug"
        self._attr_suggested_object_id = "living_room_debug"

    @property
    def native_value(self):
        p = self.coord.last_plan
        return p.debug_reason if p else None

    @property
    def extra_state_attributes(self):
        attrs = {
            "lux_gate": self.coord.gate_internals(),
            "ring_mode": self.coord.ring_mode,
        }
        p = self.coord.last_plan
        if p:
            attrs["plan"] = p.as_dict()
            attrs["subentry_diagnostics"] = [dict(item) for item in p.subentry_diagnostics]
        return attrs
