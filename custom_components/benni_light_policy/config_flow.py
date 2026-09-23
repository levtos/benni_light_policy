"""Config-, Options- und Subentry-Flows für die Light-Policy.

Architektur: **Hub + typisierte Subentries**.
- Hub-Setup fragt die geteilten Foundation-Entities EINMAL ab (auto-vorausgefüllt
  aus der Toolbox), dazu Lampengruppen, Katalog und globale Optionen. Schlank,
  größtenteils nur bestätigen.
- Pro Anwendungsfall (Gaming, Musik, Notification-RGB, Flur, Bad, Schlafzimmer)
  ein **Subentry** mit NUR seinen eigenen 2–4 Feldern → keine „Wall of Entities".

Entity-Selektoren bewusst ungefiltert (volle Flexibilität). Gaming-Quellen
sind dagegen media_device-Tokens und keine Entity-IDs.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    AREA_PREFILL,
    CONF_ACTIVITY_STATE,
    CONF_APPLY_ENABLED,
    CONF_BATHROOM_LIGHT,
    CONF_BATHROOM_TIMEOUT,
    CONF_BATHROOM_VIBRATION,
    CONF_BIO_STATE,
    CONF_CALENDAR_THEME,
    CONF_CLASSIFIER_ENTITY,
    CONF_CROSSFADE_SECONDS,
    CONF_DAY_STATE,
    CONF_ENTERTAINMENT_STABLE,
    CONF_GROUP_ALL,
    CONF_GROUP_CEILING,
    CONF_GROUP_MAIN,
    CONF_GUEST,
    CONF_HALLWAY_LIGHT,
    CONF_HALLWAY_TRIGGERS,
    CONF_LUX,
    CONF_MAPPINGS,
    CONF_MEDIA_CONTEXT,
    CONF_MEDIA_DEVICE,
    CONF_OVERNIGHT_AWAY,
    CONF_PRESENCE_HOUSEHOLD,
    CONF_PRESENCE_PERSONAL,
    CONF_PRESENCE_TRANSITION,
    CONF_REQUIRE_BIRTHDAY,
    CONF_RING_TARGETS,
    CONF_SEASON,
    CONF_SOURCE_ID,
    CONF_SOURCE_PRIORITY,
    CONF_STARTUP_BLOCK_SECONDS,
    CONF_SYSTEM_READY,
    CONF_WAKE_TEARDOWN_AREAS,
    CONF_WAKE_UP_TARGETS,
    CONF_WEATHER,
    CONFIG_ENTRY_VERSION,
    DEFAULT_APPLY_ENABLED,
    DEFAULT_CROSSFADE_SECONDS,
    DEFAULT_STARTUP_BLOCK_SECONDS,
    DOMAIN,
    ENTITY_PREFILL,
    GAMING_DEFAULT_PRIORITY,
    GROUP_PREFILL,
    MAPPING_PRESET_PREFIX,
    MAPPING_SLOT_COUNT,
    MAPPING_VALUE_PREFIX,
    SUBENTRY_BATHROOM,
    SUBENTRY_GAMING,
    SUBENTRY_HALLWAY,
    SUBENTRY_MUSIC,
    SUBENTRY_NOTIFICATION_RING,
    SUBENTRY_PREFILL,
    SUBENTRY_WAKE_UP,
)
from .subentry_titles import SUBENTRY_DEFAULT_TITLE, default_subentry_title

# --- Selektoren (ungefiltert) ---
_ENTITY = selector.EntitySelector(selector.EntitySelectorConfig())
_ENTITIES = selector.EntitySelector(selector.EntitySelectorConfig(multiple=True))
_LIGHT = selector.EntitySelector(selector.EntitySelectorConfig(domain="light"))
_LIGHTS = selector.EntitySelector(selector.EntitySelectorConfig(domain="light", multiple=True))
_AREAS = selector.AreaSelector(selector.AreaSelectorConfig(multiple=True))
# Bad-Licht ist nicht immer ein light.* — z.B. Shelly Switch.
_LIGHT_OR_SWITCH = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=["light", "switch"])
)
_BOOL = selector.BooleanSelector()
_TEXT = selector.TextSelector(selector.TextSelectorConfig())
_SOURCE_ID = selector.SelectSelector(selector.SelectSelectorConfig(
    options=list(GAMING_DEFAULT_PRIORITY),
    mode=selector.SelectSelectorMode.DROPDOWN,
    custom_value=True,
))


def _source_id(value: str) -> str:
    """Accept future source tokens, but never an HA entity ID."""
    token = value.strip().lower()
    if not token or not all(ch.isalnum() or ch in "_-" for ch in token):
        raise vol.Invalid("source_id must be a media_device token, not an entity ID")
    return token


_SECONDS = vol.All(vol.Coerce(int), vol.Range(min=0, max=86400))
_TIMEOUT_SECONDS = vol.All(vol.Coerce(int), vol.Range(min=1, max=86400))
_PRIORITY = vol.All(vol.Coerce(int), vol.Range(min=0, max=1000))

SELECTORS: dict[str, Any] = {
    # Hub-Foundation
    CONF_BIO_STATE: _ENTITY, CONF_ACTIVITY_STATE: _ENTITY, CONF_DAY_STATE: _ENTITY,
    CONF_PRESENCE_PERSONAL: _ENTITY, CONF_PRESENCE_HOUSEHOLD: _ENTITY,
    CONF_LUX: _ENTITY, CONF_WEATHER: _ENTITY, CONF_SEASON: _ENTITY,
    CONF_CALENDAR_THEME: _ENTITY, CONF_ENTERTAINMENT_STABLE: _ENTITY,
    CONF_MEDIA_DEVICE: _ENTITY, CONF_MEDIA_CONTEXT: _ENTITY,
    CONF_GUEST: _ENTITY, CONF_PRESENCE_TRANSITION: _ENTITY,
    CONF_OVERNIGHT_AWAY: _ENTITY, CONF_SYSTEM_READY: _ENTITY,
    CONF_GROUP_MAIN: _LIGHTS, CONF_GROUP_CEILING: _LIGHTS, CONF_GROUP_ALL: _LIGHTS,
    CONF_WAKE_TEARDOWN_AREAS: _AREAS,
    CONF_APPLY_ENABLED: _BOOL, CONF_STARTUP_BLOCK_SECONDS: _SECONDS,
    CONF_CROSSFADE_SECONDS: _SECONDS,
    # Subentry-Felder (Minihub-Schema)
    CONF_CLASSIFIER_ENTITY: _ENTITY,
    CONF_SOURCE_ID: _SOURCE_ID, CONF_SOURCE_PRIORITY: _PRIORITY,
    CONF_REQUIRE_BIRTHDAY: _BOOL, CONF_RING_TARGETS: _LIGHTS,
    CONF_HALLWAY_LIGHT: _LIGHT, CONF_HALLWAY_TRIGGERS: _ENTITIES,
    CONF_BATHROOM_LIGHT: _LIGHT_OR_SWITCH, CONF_BATHROOM_VIBRATION: _ENTITY,
    CONF_BATHROOM_TIMEOUT: _TIMEOUT_SECONDS,
    CONF_WAKE_UP_TARGETS: _LIGHTS,
}

INT_DEFAULTS: dict[str, int] = {
    CONF_STARTUP_BLOCK_SECONDS: DEFAULT_STARTUP_BLOCK_SECONDS,
    CONF_CROSSFADE_SECONDS: DEFAULT_CROSSFADE_SECONDS,
    CONF_BATHROOM_TIMEOUT: 3600,
}
BOOL_KEYS = {CONF_APPLY_ENABLED, CONF_REQUIRE_BIRTHDAY}

# --- Hub-Schritte ---
STEP_CONTEXT = (CONF_BIO_STATE, CONF_ACTIVITY_STATE, CONF_DAY_STATE,
                CONF_PRESENCE_PERSONAL, CONF_PRESENCE_HOUSEHOLD)
STEP_ENVIRONMENT = (CONF_LUX, CONF_WEATHER, CONF_SEASON,
                    CONF_CALENDAR_THEME, CONF_ENTERTAINMENT_STABLE,
                    CONF_MEDIA_DEVICE, CONF_MEDIA_CONTEXT)
STEP_SIGNALS = (CONF_GUEST, CONF_PRESENCE_TRANSITION, CONF_OVERNIGHT_AWAY, CONF_SYSTEM_READY)
STEP_LAMPS = (CONF_GROUP_MAIN, CONF_GROUP_CEILING, CONF_GROUP_ALL, CONF_WAKE_TEARDOWN_AREAS)
STEP_OPTIONS = (CONF_APPLY_ENABLED, CONF_STARTUP_BLOCK_SECONDS, CONF_CROSSFADE_SECONDS)

HUB_MENU = ("context", "environment", "signals", "lamps", "options")
HUB_STEP_KEYS: dict[str, tuple[str, ...]] = {
    "context": STEP_CONTEXT, "environment": STEP_ENVIRONMENT, "signals": STEP_SIGNALS,
    "lamps": STEP_LAMPS, "options": STEP_OPTIONS,
}

# --- Subentry-Felder pro Typ ---
SUBENTRY_FIELDS: dict[str, tuple[str, ...]] = {
    # Minihubs (haben zusätzlich Mapping-Slots — siehe SUBENTRY_HAS_MAPPINGS)
    SUBENTRY_GAMING: (CONF_SOURCE_ID, CONF_SOURCE_PRIORITY, CONF_CLASSIFIER_ENTITY),
    SUBENTRY_MUSIC: (CONF_CLASSIFIER_ENTITY, CONF_REQUIRE_BIRTHDAY),
    SUBENTRY_NOTIFICATION_RING: (CONF_RING_TARGETS, CONF_ACTIVITY_STATE),
    # Single-Rule
    SUBENTRY_HALLWAY: (CONF_HALLWAY_LIGHT, CONF_HALLWAY_TRIGGERS),
    SUBENTRY_BATHROOM: (CONF_BATHROOM_LIGHT, CONF_BATHROOM_VIBRATION, CONF_BATHROOM_TIMEOUT),
    SUBENTRY_WAKE_UP: (CONF_WAKE_UP_TARGETS,),
}
# Subentry-Typen mit interner Mapping-Tabelle (classifier/activity → preset/effect).
SUBENTRY_HAS_MAPPINGS: frozenset[str] = frozenset({
    SUBENTRY_GAMING, SUBENTRY_MUSIC, SUBENTRY_NOTIFICATION_RING,
})
def _marker(key: str, defaults: dict[str, Any]):
    if key == CONF_SOURCE_ID:
        return vol.Required(key, default=defaults[key]) if defaults.get(key) else vol.Required(key)
    if key in INT_DEFAULTS:
        return vol.Optional(key, default=defaults.get(key, INT_DEFAULTS[key]))
    if key in BOOL_KEYS:
        fallback = DEFAULT_APPLY_ENABLED if key == CONF_APPLY_ENABLED else True
        return vol.Optional(key, default=bool(defaults.get(key, fallback)))
    if key in defaults and defaults[key] not in (None, ""):
        return vol.Optional(key, default=defaults[key])
    return vol.Optional(key)


def _schema(keys: tuple[str, ...], defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema({_marker(k, defaults): SELECTORS[k] for k in keys})


def _exists(hass, eid: str) -> bool:
    return bool(eid) and hass.states.get(eid) is not None


def _prefilled(keys: tuple[str, ...], data: dict[str, Any], hass) -> dict[str, Any]:
    """Hub-Defaults inkl. Auto-Prefill (Einzelwerte + Lampengruppen-Listen) —
    jeweils NUR wenn die Entity(en) in HA existieren."""
    defaults = dict(data)
    for key in keys:
        if key in defaults:
            continue
        single = ENTITY_PREFILL.get(key)
        if single and _exists(hass, single):
            defaults[key] = single
            continue
        group = GROUP_PREFILL.get(key)
        if group:
            present = [e for e in group if _exists(hass, e)]
            if present:
                defaults[key] = present
            continue
        # Area-Prefill (Wake-Teardown) — Areas sind keine Entities; ohne
        # Existenz-Check, greift schadlos (fehlende Area → leere Auflösung).
        areas = AREA_PREFILL.get(key)
        if areas:
            defaults[key] = list(areas)
    return defaults


# --------------------------------------------------------------------------- #
# Hub Config-Flow
# --------------------------------------------------------------------------- #
class LightPolicyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = CONFIG_ENTRY_VERSION

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self.async_step_context()

    async def _step(self, step_id: str, next_step: str | None,
                    user_input: dict[str, Any] | None) -> FlowResult:
        keys = HUB_STEP_KEYS[step_id]
        if user_input is not None:
            self._data.update(user_input)
            if next_step is None:
                return self.async_create_entry(title="Light Policy", data=self._data)
            return await getattr(self, f"async_step_{next_step}")()
        return self.async_show_form(
            step_id=step_id, data_schema=_schema(keys, _prefilled(keys, self._data, self.hass))
        )

    async def async_step_context(self, user_input=None):
        return await self._step("context", "environment", user_input)

    async def async_step_environment(self, user_input=None):
        return await self._step("environment", "signals", user_input)

    async def async_step_signals(self, user_input=None):
        return await self._step("signals", "lamps", user_input)

    async def async_step_lamps(self, user_input=None):
        return await self._step("lamps", "options", user_input)

    async def async_step_options(self, user_input=None):
        return await self._step("options", None, user_input)

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return LightPolicyOptionsFlow(entry)

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {
            SUBENTRY_GAMING: GamingSubentryFlow,
            SUBENTRY_MUSIC: MusicSubentryFlow,
            SUBENTRY_NOTIFICATION_RING: NotificationRingSubentryFlow,
            SUBENTRY_HALLWAY: HallwaySubentryFlow,
            SUBENTRY_BATHROOM: BathroomSubentryFlow,
            SUBENTRY_WAKE_UP: WakeUpSubentryFlow,
        }


# --------------------------------------------------------------------------- #
# Options-Flow (Hub-Kategorien als Menü)
# --------------------------------------------------------------------------- #
class LightPolicyOptionsFlow(OptionsFlow):
    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry

    def _defaults(self) -> dict[str, Any]:
        return {**self._entry.data, **self._entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(step_id="init", menu_options=list(HUB_MENU))

    def _edit(self, step_id: str, user_input: dict[str, Any] | None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={**self._entry.options, **user_input})
        keys = HUB_STEP_KEYS[step_id]
        return self.async_show_form(step_id=step_id, data_schema=_schema(keys, self._defaults()))

    async def async_step_context(self, user_input=None):
        return self._edit("context", user_input)

    async def async_step_environment(self, user_input=None):
        return self._edit("environment", user_input)

    async def async_step_signals(self, user_input=None):
        return self._edit("signals", user_input)

    async def async_step_lamps(self, user_input=None):
        return self._edit("lamps", user_input)

    async def async_step_options(self, user_input=None):
        return self._edit("options", user_input)


# --------------------------------------------------------------------------- #
# Subentry-Flows — pro Typ eine kleine Klasse (Typ als eigenes Klassen-Attribut,
# kein Verlass auf HA-interne Typ-Attribute).
# --------------------------------------------------------------------------- #
def _slot_keys(i: int) -> tuple[str, str]:
    return f"{MAPPING_VALUE_PREFIX}{i}", f"{MAPPING_PRESET_PREFIX}{i}"


def _pack_mappings(user_input: dict[str, Any]) -> dict[str, str]:
    """Zieht die N (value/preset)-Slot-Paare aus dem Form-Input und packt sie
    in ein {classifier_value: preset_uuid}-Dict. Leere Slots werden ignoriert.
    Entfernt die Slot-Keys aus user_input (in-place)."""
    packed: dict[str, str] = {}
    for i in range(MAPPING_SLOT_COUNT):
        vkey, pkey = _slot_keys(i)
        v = user_input.pop(vkey, None)
        p = user_input.pop(pkey, None)
        if v in (None, "") or p in (None, ""):
            continue
        packed[str(v).strip()] = str(p).strip()
    return packed


def _unpack_mappings(defaults: dict[str, Any]) -> None:
    """Spielt ein vorhandenes mappings-Dict aus defaults in die Slot-Felder
    zurück (für Reconfigure/Edit)."""
    mappings = defaults.get(CONF_MAPPINGS) or {}
    if not isinstance(mappings, dict):
        return
    items = list(mappings.items())[:MAPPING_SLOT_COUNT]
    for i, (v, p) in enumerate(items):
        vkey, pkey = _slot_keys(i)
        defaults.setdefault(vkey, v)
        defaults.setdefault(pkey, p)


class _BasePolicySubentryFlow(ConfigSubentryFlow):
    policy_type: str = ""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        stype = self.policy_type
        if user_input is not None:
            try:
                source_id = _source_id(user_input[CONF_SOURCE_ID]) if stype == SUBENTRY_GAMING else None
            except (KeyError, vol.Invalid):
                return self._show_subentry_form(
                    "user", dict(user_input),
                    user_input.get("name") or SUBENTRY_DEFAULT_TITLE[stype],
                    {CONF_SOURCE_ID: "invalid_source_id"},
                )
            data = dict(user_input)
            if source_id is not None:
                data[CONF_SOURCE_ID] = source_id
            name = data.pop("name", None)
            if stype in SUBENTRY_HAS_MAPPINGS:
                data[CONF_MAPPINGS] = _pack_mappings(data)
            default = SUBENTRY_DEFAULT_TITLE.get(stype, stype)
            title = name if name and name != default else default_subentry_title(stype, data)
            return self.async_create_entry(title=title, data=data)

        defaults: dict[str, Any] = {}
        # Auto-Prefill eindeutiger Subentry-Felder (z.B. Awake-Dauer), wenn vorhanden.
        for key in SUBENTRY_FIELDS[stype]:
            cand = SUBENTRY_PREFILL.get(key)
            if cand and key not in defaults and _exists(self.hass, cand):
                defaults[key] = cand
        return self._show_subentry_form("user", defaults, SUBENTRY_DEFAULT_TITLE.get(stype, stype))

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing subentry without dropping its mappings or other data."""
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            if self.policy_type == SUBENTRY_GAMING:
                try:
                    source_id = _source_id(
                        user_input.get(CONF_SOURCE_ID, subentry.data.get(CONF_SOURCE_ID, ""))
                    )
                except (KeyError, vol.Invalid):
                    return self._show_subentry_form(
                        "reconfigure", {**subentry.data, **user_input},
                        user_input.get("name", subentry.title),
                        {CONF_SOURCE_ID: "invalid_source_id"},
                    )
                user_input = {**user_input, CONF_SOURCE_ID: source_id}
            data = {**subentry.data, **user_input}
            name = data.pop("name", subentry.title)
            if self.policy_type in SUBENTRY_HAS_MAPPINGS:
                existing = subentry.data.get(CONF_MAPPINGS) or {}
                if any(
                    key in user_input
                    for i in range(1, MAPPING_SLOT_COUNT + 1)
                    for key in _slot_keys(i)
                ):
                    visible_keys = set(list(existing)[:MAPPING_SLOT_COUNT]) if isinstance(existing, dict) else set()
                    retained = (
                        {key: value for key, value in existing.items() if key not in visible_keys}
                        if isinstance(existing, dict) else {}
                    )
                    data[CONF_MAPPINGS] = {**retained, **_pack_mappings(data)}
            previous_default = default_subentry_title(self.policy_type, subentry.data)
            if not name or name in (SUBENTRY_DEFAULT_TITLE.get(self.policy_type), previous_default):
                title = default_subentry_title(self.policy_type, data)
            else:
                title = name
            return self.async_update_and_abort(
                self._get_entry(), subentry, data=data, title=title
            )

        return self._show_subentry_form("reconfigure", dict(subentry.data), subentry.title)

    def _show_subentry_form(
        self, step_id: str, defaults: dict[str, Any], title: str,
        errors: dict[str, str] | None = None,
    ) -> FlowResult:
        stype = self.policy_type
        if stype in SUBENTRY_HAS_MAPPINGS:
            _unpack_mappings(defaults)
        fields: dict[Any, Any] = {
            vol.Optional("name", default=title): _TEXT
        }
        for key in SUBENTRY_FIELDS[stype]:
            fields[_marker(key, defaults)] = SELECTORS[key]
        if stype in SUBENTRY_HAS_MAPPINGS:
            for i in range(MAPPING_SLOT_COUNT):
                vkey, pkey = _slot_keys(i)
                fields[_marker(vkey, defaults)] = _TEXT
                fields[_marker(pkey, defaults)] = _TEXT
        data_schema = vol.Schema(fields)
        if errors:
            return self.async_show_form(step_id=step_id, data_schema=data_schema, errors=errors)
        return self.async_show_form(step_id=step_id, data_schema=data_schema)


class GamingSubentryFlow(_BasePolicySubentryFlow):
    policy_type = SUBENTRY_GAMING


class MusicSubentryFlow(_BasePolicySubentryFlow):
    policy_type = SUBENTRY_MUSIC


class NotificationRingSubentryFlow(_BasePolicySubentryFlow):
    policy_type = SUBENTRY_NOTIFICATION_RING


class HallwaySubentryFlow(_BasePolicySubentryFlow):
    policy_type = SUBENTRY_HALLWAY


class BathroomSubentryFlow(_BasePolicySubentryFlow):
    policy_type = SUBENTRY_BATHROOM


class WakeUpSubentryFlow(_BasePolicySubentryFlow):
    policy_type = SUBENTRY_WAKE_UP
