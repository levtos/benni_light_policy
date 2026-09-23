"""Light-Policy-Coordinator (Single-Instance).

Hört auf alle Quell-Entities, rechnet bei jedem Trigger eine neue Decision
(`policy.decide`) und wendet sie an — aber nur wenn `apply_enabled` an ist.
Default ist `apply_enabled=False` (Shadow-safe für Phase-4-Cut-Over).

Apply läuft über die Look-Ebene von benni_scene_presets: pro Decision EIN
`apply_look {look, brightness}`. Der Look trägt Targets, Off-Bindings und Crossfade
selbst (`look_transition`); apply_look stoppt überschneidende Lampen, Off-Bindings
clearen den Rest. Brightness kommt aus der Tagesphase. Ausnahmen: wake_up (freie
raw_targets) = direkter light.turn_on; Hard-Off = light.turn_off auf GROUP_ALL.
Script-Modus `restart` wird durch Abbrechen eines laufenden Apply-Tasks nachgebildet.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

try:
    from homeassistant.helpers.start import async_at_started
except Exception:  # pragma: no cover
    async_at_started = None  # type: ignore[assignment]

from . import areas, policy
from .const import (
    BIO_AWAKE,
    BIO_SLEEP_CONTEXTS,
    BRIGHTNESS_CHANGE_TRANSITION_SECONDS,
    CONF_ACTIVITY_STATE,
    CONF_APPLY_ENABLED,
    CONF_BIO_STATE,
    CONF_BRIGHTNESS,
    CONF_CALENDAR_THEME,
    CONF_CLASSIFIER_ENTITY,
    CONF_CROSSFADE_SECONDS,
    CONF_CUSTOM_THEMES,
    CONF_DAY_STATE,
    CONF_ENTERTAINMENT_STABLE,
    CONF_GROUP_ALL,
    CONF_GROUP_CEILING,
    CONF_GROUP_MAIN,
    CONF_GUEST,
    CONF_LOOK_MAP,
    CONF_LUX,
    CONF_LUX_THRESHOLDS,
    CONF_MAPPINGS,
    CONF_MEDIA_CONTEXT,
    CONF_MEDIA_DEVICE,
    CONF_OVERNIGHT_AWAY,
    CONF_PRESENCE_HOUSEHOLD,
    CONF_PRESENCE_PERSONAL,
    CONF_PRESENCE_TRANSITION,
    CONF_REQUIRE_BIRTHDAY,
    CONF_SCENE_INTERVAL_SECONDS,
    CONF_SEASON,
    CONF_SOURCE_ID,
    CONF_SOURCE_PRIORITY,
    CONF_STARTUP_BLOCK_SECONDS,
    CONF_SYSTEM_READY,
    CONF_TITLE_CLASSIFIER,
    CONF_WAKE_TEARDOWN_AREAS,
    CONF_WAKE_UP_TARGETS,
    CONF_WEATHER,
    DATA_SKIP_RELOAD_COUNT,
    DEFAULT_APPLY_ENABLED,
    DEFAULT_BRIGHTNESS,
    DEFAULT_CROSSFADE_SECONDS,
    DEFAULT_SCENE_INTERVAL_SECONDS,
    DEFAULT_STARTUP_BLOCK_SECONDS,
    DEFAULT_SYSTEM_READY_ENTITY,
    DEFAULT_WAKE_TEARDOWN_AREAS,
    DOMAIN,
    GAMING_DEFAULT_PRIORITY,
    GROUP_ALL,
    GROUP_CEILING,
    GROUP_MAIN,
    PHASE_EARLY_MORNING,
    POLICY_FIXED_MODES,
    POLICY_THEMES,
    PRESENCE_TRANSITION_COMING_HOME,
    SCENE_PRESETS_DOMAIN,
    SP_ATTR_BRIGHTNESS,
    SP_ATTR_LOOK,
    SP_ATTR_TRANSITION,
    SP_SERVICE_APPLY_LOOK,
    SP_SERVICE_STOP_LOOK,
    SUBENTRY_GAMING,
    SUBENTRY_MUSIC,
    SUBENTRY_WAKE_UP,
    SUPPORTED_DAY_PHASES,
    TMC_FALLBACK_HOUR,
    TMC_TRIGGER_LUX,
    WEATHER_DARK_WINDOW_SECONDS,
)
from .policy import APPLY_CCT, APPLY_OFF
from .startup_recovery import LuxSample, StartupRecoveryState, classify_lux
from .storage import make_store

_LOGGER = logging.getLogger(__name__)

RECENT_APPLY_GUARD_SECONDS = 8  # eigener Schreibvorgang ≠ externe Interaktion


def _bool_state(s: str | None) -> bool | None:
    if s is None or s in ("unknown", "unavailable"):
        return None
    return s.lower() in ("on", "true", "1", "home", "active", "playing")


def _bounded_int(
    raw: Any,
    default: int,
    *,
    minimum: int = 0,
    maximum: int = 86400,
) -> int:
    """Read a legacy option without allowing malformed values to break evaluation."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


class LightPolicyCoordinator:
    """Eine Instanz pro Config-Entry (Single-Instance-Modell)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store = make_store(hass, entry.entry_id)
        self._unsub: list[CALLBACK_TYPE] = []
        self._listeners: list[CALLBACK_TYPE] = []

        self._started_at = time.monotonic()
        self._ha_started = False
        self._ha_started_at: datetime | None = None
        self._startup_recovery = StartupRecoveryState()
        self._last_lux_sample = LuxSample(None, None, "not_started")

        self._prev_lux_gate: bool | None = None
        self._prev_bio: str | None = None
        self._manual_off = False

        self._tmc_set = False
        self._prev_day_state: str | None = None
        self._prev_presence_transition: str | None = None
        self._lux_history: list[tuple[float, float]] = []  # (monotonic_ts, lux)

        self._last_plan: policy.Plan | None = None
        # FLEET-151: zuletzt entschiedener Modus — Substrat für die Wake-Exit-
        # Erkennung. Bewusst NICHT persistiert (restart-trivial): nach Neustart
        # beobachtet die Policy den nächsten Übergang live und räumt dann ab.
        self._prev_mode: str | None = None
        self._last_wake_teardown: list[str] = []  # nur für Debug/Observability
        self._last_applied_hash: str | None = None  # hash actually pushed to lights
        # Überlebt den Reload (persistiert): erlaubt „selber Look, andere Brightness"-
        # Erkennung → kurzer Fade statt Look-Default-Crossfade.
        self._last_applied_look_ref: str | None = None
        self._last_applied_brightness: int | None = None
        # FLEET-74: konkret kommandierte Cross-Area-Entities (rohe raw_targets, die
        # light_policy selbst per light.turn_on schaltet und allein besitzt). Persistiert,
        # damit der nächste Apply gestrandete Lampen (Wecklicht) abräumen kann.
        self._last_commanded_entities: list[str] = []
        self._last_apply_ts = 0.0
        self._apply_task: asyncio.Task | None = None
        self._evaluation_task: asyncio.Task | None = None
        self._evaluation_pending = False
        self._evaluation_lock = asyncio.Lock()
        self._stopping = False

        self._areas: list = []
        self._ring_mode: str | None = None
        self._last_weather_dark = False

    # ----- options helpers -----
    @property
    def _opts(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    def _opt(self, key: str, default: Any = None) -> Any:
        return self._opts.get(key, default)

    @property
    def apply_enabled(self) -> bool:
        return bool(self._opt(CONF_APPLY_ENABLED, DEFAULT_APPLY_ENABLED))

    @property
    def startup_block_seconds(self) -> int:
        return _bounded_int(
            self._opt(CONF_STARTUP_BLOCK_SECONDS, DEFAULT_STARTUP_BLOCK_SECONDS),
            DEFAULT_STARTUP_BLOCK_SECONDS,
        )

    @property
    def crossfade_seconds(self) -> int:
        return _bounded_int(
            self._opt(CONF_CROSSFADE_SECONDS, DEFAULT_CROSSFADE_SECONDS),
            DEFAULT_CROSSFADE_SECONDS,
        )

    @property
    def scene_interval_seconds(self) -> int:
        return _bounded_int(
            self._opt(CONF_SCENE_INTERVAL_SECONDS, DEFAULT_SCENE_INTERVAL_SECONDS),
            DEFAULT_SCENE_INTERVAL_SECONDS,
        )

    @property
    def manual_off_active(self) -> bool:
        return self._manual_off

    @property
    def look_map(self) -> dict[str, str]:
        """Zentrale Map policy_key -> Look-Ref (Slug/Name). Aus den Options."""
        raw = self._opt(CONF_LOOK_MAP) or {}
        return dict(raw) if isinstance(raw, dict) else {}

    @property
    def custom_themes(self) -> tuple[str, ...]:
        raw = self._opt(CONF_CUSTOM_THEMES) or ()
        if not isinstance(raw, (list, tuple)):
            return ()
        out: list[str] = []
        for item in raw:
            value = str(item).strip().lower()
            if value and value not in out:
                out.append(value)
        return tuple(out)

    def resolve_look_ref(self, policy_key: str | None) -> str | None:
        """policy_key -> Look-Ref. Map gewinnt; sonst Key selbst (Fallback ohne
        Namenskonvention). Leere Map-Werte werden ignoriert."""
        if not policy_key:
            return None
        mapped = self.look_map.get(policy_key)
        return mapped.strip() if isinstance(mapped, str) and mapped.strip() else policy_key

    def _policy_managed_look_refs(self) -> list[str]:
        """Look-Refs that may be controlled by this policy.

        Scene Presets can also host manually started looks/effects. Only stop
        refs that belong to the policy catalog or policy subentry mappings.
        """
        refs: dict[str, str] = {}

        def add(ref: Any) -> None:
            if not isinstance(ref, str):
                return
            value = ref.strip()
            if value:
                refs.setdefault(value.casefold(), value)

        for key in POLICY_FIXED_MODES:
            add(self.resolve_look_ref(key))

        for theme in (*POLICY_THEMES, *self.custom_themes):
            for phase in SUPPORTED_DAY_PHASES:
                add(self.resolve_look_ref(f"{theme}_{phase}"))

        for key in self.look_map:
            add(self.resolve_look_ref(key))

        for sub in self.entry.subentries.values():
            if sub.subentry_type not in (SUBENTRY_GAMING, SUBENTRY_MUSIC):
                continue
            mappings = sub.data.get(CONF_MAPPINGS) or {}
            if isinstance(mappings, dict):
                for ref in mappings.values():
                    add(ref)

        return list(refs.values())

    @staticmethod
    def _look_switch_entity_id(look_ref: str) -> str:
        return f"switch.benni_look_{look_ref.replace('-', '_')}"

    def _scene_presets_look_is_on(self, look_ref: str) -> bool:
        state = self.hass.states.get(self._look_switch_entity_id(look_ref))
        return state is not None and state.state == "on"

    def _skip_next_entry_reload(self) -> None:
        data = self.hass.data.setdefault(DOMAIN, {})
        data[DATA_SKIP_RELOAD_COUNT] = int(data.get(DATA_SKIP_RELOAD_COUNT) or 0) + 1

    def _async_update_entry_options_runtime(self, options: dict[str, Any]) -> None:
        self._skip_next_entry_reload()
        self.hass.config_entries.async_update_entry(self.entry, options=options)

    async def _async_runtime_setting_changed(self, *, force_reapply: bool) -> None:
        if force_reapply:
            self._last_applied_hash = None
        await self.async_evaluate()

    @staticmethod
    def _state_timestamp(state: Any) -> datetime | None:
        """Use recorder-visible source reporting time with HA compatibility fallbacks."""
        for attr in ("last_reported", "last_updated", "last_changed"):
            value = getattr(state, attr, None)
            if isinstance(value, datetime):
                return dt_util.as_utc(value)
        return None

    def _core_startup_started_at(self) -> datetime | None:
        """Read the lifecycle reference from the canonical Core-State contract."""
        state = self.hass.states.get(DEFAULT_SYSTEM_READY_ENTITY)
        if state is not None:
            raw = state.attributes.get("startup_started_at")
            if isinstance(raw, datetime):
                return dt_util.as_utc(raw)
            if isinstance(raw, str):
                parsed = dt_util.parse_datetime(raw)
                if parsed is not None:
                    return dt_util.as_utc(parsed)
        return self._ha_started_at

    def _lux_sample(self) -> LuxSample:
        entity_id = self._opt(CONF_LUX)
        startup_started_at = self._core_startup_started_at()
        if not entity_id:
            return LuxSample(None, None, "source_not_configured")
        state = self.hass.states.get(entity_id)
        if state is None:
            return LuxSample(None, None, "source_missing")
        return classify_lux(
            state.state,
            self._state_timestamp(state),
            startup_started_at,
            attributes=state.attributes,
            source_key=entity_id,
        )

    def _core_state_ready(self) -> bool:
        state = self.hass.states.get(DEFAULT_SYSTEM_READY_ENTITY)
        return state is not None and _bool_state(state.state) is True

    def _startup_ready(self) -> bool:
        if not self._ha_started:
            return False
        if (time.monotonic() - self._started_at) < self.startup_block_seconds:
            return False

        # The Core-State process gate is mandatory.  A missing/empty legacy
        # option must never bypass it.  A separately configured entity is
        # retained only as an additional consumer-local gate until its cutover
        # is explicitly proven; the two known old IDs are migrated before setup.
        if not self._core_state_ready():
            return False

        system_ready_entity = self._opt(CONF_SYSTEM_READY)
        if not system_ready_entity or system_ready_entity == DEFAULT_SYSTEM_READY_ENTITY:
            return True
        return _bool_state(self._read(CONF_SYSTEM_READY)) is True

    # ----- lifecycle -----
    @callback
    def async_start(self) -> None:
        self._stopping = False
        if async_at_started is not None:
            self._unsub.append(async_at_started(self.hass, self._on_started))
        elif self.hass.is_running:
            self._on_started(None)
        else:
            self._unsub.append(
                self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_started)
            )

        watch: set[str] = set()
        for key in (
            CONF_BIO_STATE, CONF_DAY_STATE, CONF_ACTIVITY_STATE, CONF_LUX,
            CONF_PRESENCE_PERSONAL, CONF_PRESENCE_HOUSEHOLD, CONF_GUEST,
            CONF_PRESENCE_TRANSITION,
            CONF_SEASON, CONF_CALENDAR_THEME,
            CONF_ENTERTAINMENT_STABLE, CONF_MEDIA_DEVICE, CONF_MEDIA_CONTEXT,
            CONF_OVERNIGHT_AWAY, CONF_SYSTEM_READY,
            CONF_WEATHER,
            CONF_GROUP_MAIN, CONF_GROUP_CEILING, CONF_GROUP_ALL,
        ):
            v = self._opt(key)
            if isinstance(v, str) and v:
                watch.add(v)
        # Always observe the mandatory process-wide gate, even for an older
        # entry that has no persisted system_ready_entity value.
        watch.add(DEFAULT_SYSTEM_READY_ENTITY)
        # Subentry-Quellen (Gaming/Musik-Classifier) mitbeobachten.
        for sub in self.entry.subentries.values():
            v = sub.data.get(CONF_CLASSIFIER_ENTITY)
            if isinstance(v, str) and v:
                watch.add(v)

        if watch:
            self._unsub.append(
                async_track_state_change_event(self.hass, list(watch), self._on_state_change)
            )
        self._unsub.append(
            async_track_time_interval(self.hass, self._on_interval, timedelta(seconds=30))
        )

        # Bereichs-Controller je Subentry (Flur/Bad/Notification-RGB) starten.
        self._areas = areas.build_controllers_from_subentries(self, self.entry.subentries.values())
        for ctrl in self._areas:
            ctrl.start()

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsub:
            unsub()
        self._unsub.clear()
        for ctrl in self._areas:
            ctrl.stop()
        self._areas = []
        if self._apply_task and not self._apply_task.done():
            self._apply_task.cancel()
        self._stopping = True
        if self._evaluation_task and not self._evaluation_task.done():
            self._evaluation_task.cancel()
        self._evaluation_pending = False

    @callback
    def _on_started(self, _event) -> None:
        if self._ha_started:
            return
        self._ha_started = True
        self._started_at = time.monotonic()
        self._ha_started_at = dt_util.utcnow()
        self._schedule_evaluate()

    @callback
    def _on_interval(self, _now) -> None:
        self._schedule_evaluate()

    @callback
    def _on_state_change(self, _event: Event) -> None:
        self._schedule_evaluate()

    def _schedule_evaluate(self) -> None:
        """Coalesce event bursts into serialized, tracked evaluations."""
        if self._stopping:
            return
        if self._evaluation_task and not self._evaluation_task.done():
            self._evaluation_pending = True
            return
        self._evaluation_pending = False
        self._evaluation_task = self.hass.async_create_task(
            self._run_scheduled_evaluations()
        )

    async def _run_scheduled_evaluations(self) -> None:
        current = asyncio.current_task()
        try:
            while not self._stopping:
                self._evaluation_pending = False
                try:
                    await self.async_evaluate()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _LOGGER.exception("light_policy: scheduled evaluation failed")
                if not self._evaluation_pending:
                    break
        finally:
            if self._evaluation_task is current:
                self._evaluation_task = None

    # ----- persistence -----
    async def async_load(self) -> None:
        raw = await self._store.async_load() or {}
        self._prev_lux_gate = raw.get("lux_gate")
        self._manual_off = bool(raw.get("manual_off", False))
        self._prev_bio = raw.get("prev_bio")
        self._tmc_set = bool(raw.get("tmc_set", False))
        self._prev_day_state = raw.get("prev_day_state")
        self._last_applied_look_ref = raw.get("last_applied_look_ref")
        self._last_applied_brightness = raw.get("last_applied_brightness")
        commanded = raw.get("last_commanded_entities")
        self._last_commanded_entities = (
            [e for e in commanded if isinstance(e, str)] if isinstance(commanded, list) else []
        )

    async def _async_save(self) -> None:
        await self._store.async_save({
            "lux_gate": self._prev_lux_gate,
            "manual_off": self._manual_off,
            "prev_bio": self._prev_bio,
            "tmc_set": self._tmc_set,
            "prev_day_state": self._prev_day_state,
            "last_applied_look_ref": self._last_applied_look_ref,
            "last_applied_brightness": self._last_applied_brightness,
            "last_commanded_entities": list(self._last_commanded_entities),
            "last_plan": self._last_plan.as_dict() if self._last_plan else None,
        })

    # ----- context -----
    def _read(self, key: str) -> str | None:
        eid = self._opt(key)
        if not eid:
            return None
        st = self.hass.states.get(eid)
        if st is None or st.state in ("unknown", "unavailable"):
            return None
        return st.state

    def _read_attr(self, key: str, attr: str) -> str | None:
        eid = self._opt(key)
        if not eid:
            return None
        st = self.hass.states.get(eid)
        if st is None:
            return None
        val = st.attributes.get(attr)
        return str(val) if val is not None else None

    def build_context(self, *, lux_sample: LuxSample | None = None) -> policy.Context:
        sample = lux_sample or self._lux_sample()
        self._last_lux_sample = sample
        return policy.Context(
            bio_state=self._read(CONF_BIO_STATE),
            day_state=self._read(CONF_DAY_STATE),
            master_phase=self._read_attr(CONF_DAY_STATE, "master_phase"),
            activity_state=self._read(CONF_ACTIVITY_STATE),
            presence_personal=self._read(CONF_PRESENCE_PERSONAL),
            presence_household=self._read(CONF_PRESENCE_HOUSEHOLD),
            guest=_bool_state(self._read(CONF_GUEST)),
            season=self._read(CONF_SEASON),
            calendar_theme=self._read(CONF_CALENDAR_THEME),
            title_classifier=self._read(CONF_TITLE_CLASSIFIER),
            entertainment_stable=_bool_state(self._read(CONF_ENTERTAINMENT_STABLE)),
            media_device=self._read(CONF_MEDIA_DEVICE),
            media_context=self._read(CONF_MEDIA_CONTEXT),
            overnight_away=_bool_state(self._read(CONF_OVERNIGHT_AWAY)),
            presence_transition=self._read(CONF_PRESENCE_TRANSITION),
            lux=sample.value,
            weather=self._read(CONF_WEATHER),
            custom_themes=self.custom_themes,
        )

    # ----- evaluation -----
    def _update_tmc(self, ctx: policy.Context) -> None:
        """R2: TMC-Latch setzen/zurücksetzen. „War es heute schon hell?"."""
        # Reset bei Eintritt in early_morning.
        if ctx.day_state == PHASE_EARLY_MORNING and self._prev_day_state != PHASE_EARLY_MORNING:
            self._tmc_set = False
        self._prev_day_state = ctx.day_state
        if self._tmc_set:
            return
        if ctx.lux is not None and ctx.lux > TMC_TRIGGER_LUX:
            self._tmc_set = True
            return
        # Fallback 09:00 wenn User wach.
        if dt_util.now().hour >= TMC_FALLBACK_HOUR and ctx.bio_state == BIO_AWAKE:
            self._tmc_set = True

    def _weather_dark(self, ctx: policy.Context) -> bool:
        """R10: gleitender 10-min-Lux-Baseline-Vergleich + Wetter-Icon."""
        now = time.monotonic()
        if ctx.lux is not None:
            self._lux_history.append((now, ctx.lux))
        cutoff = now - WEATHER_DARK_WINDOW_SECONDS
        self._lux_history = [(t, v) for (t, v) in self._lux_history if t >= cutoff]
        baseline = self._lux_history[0][1] if self._lux_history else None
        return policy.weather_darkness(ctx.lux, baseline, ctx.weather, ctx.master_phase)

    async def async_evaluate(self) -> policy.Plan:
        """Serialize direct service calls and scheduled state evaluations."""
        async with self._evaluation_lock:
            return await self._async_evaluate()

    async def _async_evaluate(self) -> policy.Plan:
        lux_sample = self._lux_sample()
        ctx = self.build_context(lux_sample=lux_sample)
        self._update_tmc(ctx)
        weather_dark = self._weather_dark(ctx)
        self._last_weather_dark = weather_dark

        startup_ready = self._startup_ready()
        recovery_crossed = self._startup_recovery.maybe_complete(
            startup_ready=startup_ready,
            lux_fresh=lux_sample.fresh,
        )
        if recovery_crossed:
            # The first valid post-start Lux value is an explicit recovery edge,
            # even when the resulting plan hash equals a prior persisted plan.
            self._last_applied_hash = None

        gate = policy.lux_gate(
            ctx.lux, ctx.season, self._prev_lux_gate,
            day_state_known=ctx.day_state is not None,
            tmc_set=self._tmc_set,
            weather_dark=weather_dark,
            thresholds=self._opt(CONF_LUX_THRESHOLDS),
        )
        self._prev_lux_gate = gate

        # Issue #59: PS und S sind derselbe Consumer-Schlafkontext.
        if self._prev_bio in BIO_SLEEP_CONTEXTS and ctx.bio_state == BIO_AWAKE and self._manual_off:
            self._manual_off = False
        self._prev_bio = ctx.bio_state

        # R12 Heimkommen: coming_home-Flanke erzwingt einen Re-Apply (applied-hash
        # reset), damit das Licht sofort sitzt, auch wenn presence_personal erst
        # gleich umflippt.
        if (
            self._prev_presence_transition != PRESENCE_TRANSITION_COMING_HOME
            and ctx.presence_transition == PRESENCE_TRANSITION_COMING_HOME
        ):
            self._last_applied_hash = None
        self._prev_presence_transition = ctx.presence_transition

        extra_policies, subentry_diagnostics = self._build_extra_policies(ctx)
        plan = policy.decide(
            ctx,
            lux_gate_on=gate,
            startup_ready=startup_ready,
            apply_enabled=self.apply_enabled,
            manual_off_active=self._manual_off,
            brightness_profile=self._opt(CONF_BRIGHTNESS),
            extra_policies=extra_policies,
        )
        plan.subentry_diagnostics.extend(subentry_diagnostics)

        if self._startup_recovery.pending:
            # The plan remains fully visible, but stale/unknown/unavailable/
            # fallback Lux must never authorize the first post-start Apply.
            plan.blockers.append("startup_lux_block")
            plan.apply_allowed = False

        if self._stopping:
            return plan

        # Re-apply is keyed on the last *applied* hash, not the last *decided*
        # plan. Otherwise a plan that was decided but blocked (startup gate,
        # apply disabled, manual-off) marks the hash as "seen", so when the gate
        # later clears with an unchanged hash it never applies — e.g. after an HA
        # restart the dynamic scenes/looks are gone (they live only in RAM) but
        # the policy thinks nothing changed and never re-applies the look.
        hash_changed = self._last_applied_hash != plan.scene_hash
        self._last_plan = plan

        if plan.apply_allowed and hash_changed:
            look_ref = self.resolve_look_ref(plan.preset_enum)
            previous_look_ref = self._last_applied_look_ref
            # „Selber Look, andere Brightness" → kurzer Fade (sofort sichtbar),
            # statt des langen Look-Crossfades, der für Look-WECHSEL gedacht ist.
            brightness_only = (
                look_ref is not None
                and look_ref == previous_look_ref
                and plan.brightness != self._last_applied_brightness
            )
            self._last_applied_hash = plan.scene_hash
            self._last_applied_look_ref = look_ref
            self._last_applied_brightness = plan.brightness
            self._schedule_apply(
                plan,
                brightness_only=brightness_only,
                previous_look_ref=previous_look_ref,
            )

        # FLEET-151: Wake-only-Bereichs-Teardown. Beim Verlassen eines Wake-Zustands
        # (waking/work_home → Nicht-Wake) räumt die Policy raumübergreifend die
        # Nicht-Wohnzimmer-Wake-Lampen (Schlafzimmer-Strips, ggf. Küche) per direktem
        # light.turn_off ab — der eingehende Wohnzimmer-Look kann sie nicht erreichen.
        # Quellenagnostisch (am STATE-Exit, nicht am Look) und gated wie der Apply.
        if self.apply_enabled and policy.wake_exit(self._prev_mode, plan.mode):
            await self._wake_area_teardown()
        self._prev_mode = plan.mode

        await self._async_save()
        for cb in self._listeners:
            cb()
        return plan

    def _read_entity(self, eid: str | None) -> str | None:
        if not eid:
            return None
        st = self.hass.states.get(eid)
        if st is None or st.state in ("unknown", "unavailable"):
            return None
        return st.state

    def _build_extra_policies(
        self, ctx: policy.Context
    ) -> tuple[list[policy.PolicyDef], list[dict[str, str]]]:
        """Subentry-getriebene Policies: Gaming/Musik (Classifier+Mapping)
        + Wake-Up (vereinigte Ziel-Lampen aller wake_up-Subentries)."""
        out: list[policy.PolicyDef] = []
        diagnostics: list[dict[str, str]] = []
        wake_up_targets: list[str] = []
        for sub in self.entry.subentries.values():
            d = sub.data
            if sub.subentry_type == SUBENTRY_WAKE_UP:
                for eid in (d.get(CONF_WAKE_UP_TARGETS) or []):
                    if isinstance(eid, str) and eid and eid not in wake_up_targets:
                        wake_up_targets.append(eid)
                continue
            if sub.subentry_type not in (SUBENTRY_GAMING, SUBENTRY_MUSIC):
                continue
            raw_source_id = d.get(CONF_SOURCE_ID)
            source_id = (
                raw_source_id.strip().lower()
                if isinstance(raw_source_id, str)
                else ""
            )
            # Minihub: mappings = dict {classifier_value (str) → preset_uuid (str)}
            mappings = d.get(CONF_MAPPINGS) or {}
            value = self._read_entity(d.get(CONF_CLASSIFIER_ENTITY))
            diagnostics.extend(policy.mapping_subentry_diagnostics(
                sub.subentry_id, sub.subentry_type, source_id, value, mappings, ctx,
                require_birthday=bool(d.get(CONF_REQUIRE_BIRTHDAY, True)),
            ))
            if not isinstance(mappings, dict) or not mappings:
                continue
            if sub.subentry_type == SUBENTRY_GAMING:
                if not source_id:
                    continue
                priority = policy.resolve_priority(
                    d.get(CONF_SOURCE_PRIORITY),
                    GAMING_DEFAULT_PRIORITY.get(source_id, policy.PRIO_GAMING),
                )
                out.append(policy.make_gaming_policy(
                    source_id, value, mappings, priority=priority,
                ))
            elif sub.subentry_type == SUBENTRY_MUSIC:
                out.append(policy.make_music_policy(
                    value, mappings,
                    require_birthday=bool(d.get(CONF_REQUIRE_BIRTHDAY, True)),
                ))
        if wake_up_targets:
            out.append(policy.make_wake_up_policy(wake_up_targets))
        return out, diagnostics

    # (R16 Bettgeh-Signal entfernt — User: stattdessen Wake-Up via wake_planner.)

    # ----- apply (gated, R3/R3b Crossfade) -----
    def _resolve_targets(self, logical: list[str]) -> list[str]:
        mapping = {
            GROUP_MAIN: self._opt(CONF_GROUP_MAIN),
            GROUP_CEILING: self._opt(CONF_GROUP_CEILING),
            GROUP_ALL: self._opt(CONF_GROUP_ALL),
        }
        out: list[str] = []
        for g in logical:
            val = mapping.get(g)
            if not val:
                continue
            if isinstance(val, str):
                out.append(val)
            else:  # Liste von Einzellampen
                out.extend(val)
        # Duplikate raus, Reihenfolge erhalten (z.B. GROUP_ALL ∪ GROUP_MAIN).
        seen: set[str] = set()
        return [e for e in out if not (e in seen or seen.add(e))]

    def _schedule_apply(
        self,
        plan: policy.Plan,
        *,
        brightness_only: bool = False,
        previous_look_ref: str | None = None,
    ) -> None:
        # mode: restart — laufenden Crossfade abbrechen, neuen starten.
        if self._apply_task and not self._apply_task.done():
            self._apply_task.cancel()
        self._apply_task = self.hass.async_create_task(
            self._apply(
                plan,
                brightness_only=brightness_only,
                previous_look_ref=previous_look_ref,
            )
        )

    async def _apply(
        self,
        plan: policy.Plan,
        *,
        brightness_only: bool = False,
        previous_look_ref: str | None = None,
    ) -> None:
        try:
            self._last_apply_ts = time.monotonic()

            if plan.apply_kind == APPLY_OFF:
                await self._stop_scene_presets_policy_looks(
                    keep_look_ref=None,
                    previous_look_ref=previous_look_ref,
                )
                off_targets = (
                    self._resolve_targets([GROUP_ALL])
                    or self._resolve_targets(plan.exclusive_off)
                )
                # FLEET-74: Hard-Off räumt zusätzlich gestrandete Cross-Area-Lampen
                # (z.B. Wecklicht-Schlafzimmer/Küche) mit ab — sonst nur GROUP_ALL (WZ).
                stranded = policy.stranded_entities(self._last_commanded_entities, off_targets)
                await self._turn_off([*off_targets, *stranded])
                self._last_commanded_entities = []
                return

            # wake_up-Sonderfall: freie raw_targets, kein Look → direkter CCT-turn_on.
            if plan.apply_kind == APPLY_CCT and not plan.preset_enum:
                if not plan.raw_targets:
                    _LOGGER.warning("light_policy: %s ohne konfigurierte Targets", plan.mode)
                    self._last_applied_hash = None  # nichts angewandt → nächster Tick retry
                    return
                await self._stop_scene_presets_policy_looks(
                    keep_look_ref=None,
                    previous_look_ref=previous_look_ref,
                )
                # FLEET-74: gestrandete Lampen aus dem vorigen Raw-Apply (die diesmal
                # nicht mehr Ziel sind) zuerst abschalten, dann die neuen einschalten.
                stranded = policy.stranded_entities(
                    self._last_commanded_entities, plan.raw_targets
                )
                await self._turn_off(stranded)
                await self.hass.services.async_call(
                    "light", "turn_on",
                    {
                        "entity_id": list(plan.raw_targets),
                        "brightness": plan.brightness,
                        "color_temp_kelvin": plan.color_temp,
                        "transition": min(self.crossfade_seconds, 30),
                    },
                    blocking=False,
                )
                self._last_commanded_entities = list(plan.raw_targets)
                return

            # Alle übrigen Modi (CCT-Kelvin-Look + Szene): EIN apply_look. Der Look trägt
            # Targets, Off-Bindings und Crossfade selbst; apply_look stoppt überschneidende
            # Lampen, Off-Bindings clearen den Rest. Brightness kommt aus der Tagesphase.
            # Der Policy-Key (preset_enum) wird über die zentrale Look-Map auf einen echten
            # Look-Ref (Slug/Name) aufgelöst — fällt auf den Key selbst zurück.
            look_ref = self.resolve_look_ref(plan.preset_enum)
            if not look_ref:
                _LOGGER.warning(
                    "light_policy: apply übersprungen — keine Look-Ref (mode=%s)", plan.mode
                )
                self._last_applied_hash = None  # nichts angewandt → nächster Tick retry
                return
            data: dict[str, Any] = {SP_ATTR_LOOK: look_ref}
            if plan.brightness is not None:
                data[SP_ATTR_BRIGHTNESS] = plan.brightness
            # Reine Brightness-Änderung am selben Look: kurzer Fade, damit der neue
            # Wert sofort sichtbar wird (statt des langen Look-Default-Crossfades).
            if brightness_only:
                data[SP_ATTR_TRANSITION] = BRIGHTNESS_CHANGE_TRANSITION_SECONDS
            await self._stop_scene_presets_policy_looks(
                keep_look_ref=look_ref,
                previous_look_ref=previous_look_ref,
            )
            # FLEET-74: rohe Cross-Area-Lampen aus einem vorigen Raw-Apply (Wecklicht)
            # abräumen — der Look räumt nur seine eigene Area via Off-Bindings ab. Die vom
            # neuen Look abgedeckten Gruppen (plan.targets) bleiben verschont (kein Flicker).
            owned = self._resolve_targets(plan.targets)
            stranded = policy.stranded_entities(self._last_commanded_entities, owned)
            await self._turn_off(stranded)
            await self.hass.services.async_call(
                SCENE_PRESETS_DOMAIN, SP_SERVICE_APPLY_LOOK, data, blocking=False,
            )
            self._last_commanded_entities = []
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - ein fehlgeschlagener Apply darf den Loop nicht killen
            _LOGGER.warning("light_policy: apply failed: %s", err)
            self._last_applied_hash = None  # Apply gescheitert → nächster Tick retry

    async def _stop_scene_presets_look(self, look_ref: str | None) -> None:
        if not look_ref:
            return
        try:
            await self.hass.services.async_call(
                SCENE_PRESETS_DOMAIN,
                SP_SERVICE_STOP_LOOK,
                {SP_ATTR_LOOK: look_ref},
                blocking=True,
            )
        except Exception as err:  # noqa: BLE001 - Stop ist best effort vor Apply/Off
            _LOGGER.warning("light_policy: could not stop previous look %s: %s", look_ref, err)

    async def _stop_scene_presets_policy_looks(
        self,
        *,
        keep_look_ref: str | None,
        previous_look_ref: str | None,
    ) -> None:
        keep = keep_look_ref.casefold() if keep_look_ref else None
        refs: dict[str, str] = {}

        def add(ref: str | None) -> None:
            if not ref:
                return
            value = ref.strip()
            if value and value.casefold() != keep:
                refs.setdefault(value.casefold(), value)

        add(previous_look_ref)
        for ref in self._policy_managed_look_refs():
            if ref == previous_look_ref or self._scene_presets_look_is_on(ref):
                add(ref)

        for ref in refs.values():
            await self._stop_scene_presets_look(ref)

    async def _turn_off(self, targets: list[str]) -> None:
        if not targets:
            return
        await self.hass.services.async_call(
            "light", "turn_off", {"entity_id": targets}, blocking=False,
        )

    # ----- FLEET-151: Wake-only-Bereichs-Teardown -----
    def wake_teardown_targets(self) -> list[str]:
        """Light-Entities der konfigurierten Wake-Teardown-Areas (Default:
        Schlafzimmer), zur Laufzeit aus der Area-Zugehörigkeit aufgelöst — eine
        neue Lampe im Bereich ist automatisch dabei (keine Handliste). Area kommt
        aus Entity- ODER Geräte-Registry. Wohnzimmer-Lampen (GROUP_ALL) werden zur
        Sicherheit ausgeschlossen, damit der Teardown den WZ-Look nie anfasst."""
        raw = self._opt(CONF_WAKE_TEARDOWN_AREAS)
        if raw is None:
            raw = list(DEFAULT_WAKE_TEARDOWN_AREAS)
        if isinstance(raw, str):
            raw = [raw]
        area_set = {a for a in raw if isinstance(a, str) and a}
        if not area_set:
            return []
        ent_reg = er.async_get(self.hass)
        dev_reg = dr.async_get(self.hass)
        living = set(self._resolve_targets([GROUP_ALL]))
        out: list[str] = []
        seen: set[str] = set()
        for ent in ent_reg.entities.values():
            if not ent.entity_id.startswith("light."):
                continue
            area_id = ent.area_id
            if area_id is None and ent.device_id:
                dev = dev_reg.async_get(ent.device_id)
                area_id = dev.area_id if dev else None
            if area_id in area_set and ent.entity_id not in living and ent.entity_id not in seen:
                seen.add(ent.entity_id)
                out.append(ent.entity_id)
        return out

    async def _wake_area_teardown(self) -> None:
        targets = self.wake_teardown_targets()
        self._last_wake_teardown = list(targets)
        if not targets:
            return
        _LOGGER.info("light_policy: wake-exit teardown → %s", targets)
        await self._turn_off(targets)

    # ----- service surface -----
    async def async_apply_now(self) -> policy.Plan:
        self._last_applied_hash = None  # erzwingt hash_changed → Re-Apply
        return await self.async_evaluate()

    async def async_set_manual_off(self) -> None:
        self._manual_off = True
        await self.async_evaluate()

    async def async_clear_manual_off(self) -> None:
        self._manual_off = False
        await self.async_evaluate()

    async def async_set_apply_enabled(self, value: bool) -> None:
        """Apply zur Laufzeit an/aus (vom Apply-Switch)."""
        new_options = {**self.entry.options, CONF_APPLY_ENABLED: bool(value)}
        self._async_update_entry_options_runtime(new_options)
        await self._async_runtime_setting_changed(force_reapply=bool(value))

    async def async_set_look_map(self, mapping: dict[str, str]) -> dict[str, str]:
        """Zentrale Look-Map schreiben (policy_key -> Look-Ref). Leere Werte werden
        entfernt (= Mapping gelöscht)."""
        cleaned = {
            str(k): str(v).strip()
            for k, v in (mapping or {}).items()
            if isinstance(v, str) and v.strip()
        }
        new_options = {**self.entry.options, CONF_LOOK_MAP: cleaned}
        self._async_update_entry_options_runtime(new_options)
        await self._async_runtime_setting_changed(force_reapply=True)
        return cleaned

    async def async_set_brightness_profile(self, profile: dict[str, Any]) -> dict[str, int]:
        """Speichert Helligkeiten als Options. Keys sind phase/mode oder theme_phase."""
        allowed = set(DEFAULT_BRIGHTNESS) | {
            f"{theme}_{phase}"
            for theme in (*POLICY_THEMES, *self.custom_themes)
            for phase in SUPPORTED_DAY_PHASES
        }
        # Existing look-map themes from the frontend may include built-in themes too.
        for key in self.look_map:
            if key.endswith(tuple(SUPPORTED_DAY_PHASES)):
                allowed.add(key)

        cleaned: dict[str, int] = {}
        for key, raw in (profile or {}).items():
            skey = str(key).strip()
            if skey not in allowed:
                continue
            try:
                value = int(raw)
            except (TypeError, ValueError):
                continue
            cleaned[skey] = max(0, min(255, value))
        new_options = {**self.entry.options, CONF_BRIGHTNESS: cleaned}
        self._async_update_entry_options_runtime(new_options)
        await self._async_runtime_setting_changed(force_reapply=True)
        return {**DEFAULT_BRIGHTNESS, **cleaned}

    async def async_set_custom_themes(self, themes: list[str]) -> tuple[str, ...]:
        cleaned: list[str] = []
        for item in themes or []:
            value = str(item).strip().lower().replace(" ", "_")
            if value and value not in cleaned:
                cleaned.append(value)
        new_options = {**self.entry.options, CONF_CUSTOM_THEMES: cleaned}
        self._async_update_entry_options_runtime(new_options)
        await self._async_runtime_setting_changed(force_reapply=False)
        return tuple(cleaned)

    async def async_set_subentry_mappings(
        self, subentry_id: str, mappings: dict[str, str]
    ) -> dict[str, str]:
        """Gaming/Musik/Ring-Subentry: classifier_value -> Look-Ref schreiben.
        Aktualisiert die Subentry-Daten (kein UUID/Preset mehr)."""
        sub = self.entry.subentries.get(subentry_id)
        if sub is None:
            raise ValueError(f"unknown subentry {subentry_id}")
        cleaned = {
            str(k).strip(): str(v).strip()
            for k, v in (mappings or {}).items()
            if str(k).strip() and isinstance(v, str) and v.strip()
        }
        new_data = {**sub.data, CONF_MAPPINGS: cleaned}
        self._skip_next_entry_reload()
        self.hass.config_entries.async_update_subentry(self.entry, sub, data=new_data)
        await self._async_runtime_setting_changed(force_reapply=True)
        return cleaned

    # ----- helpers für Bereichs-Controller -----
    def get_option(self, key: str, default=None):
        return self._opt(key, default)

    def current_day_state(self) -> str | None:
        return self._read(CONF_DAY_STATE)

    def current_activity(self) -> str | None:
        return self._read(CONF_ACTIVITY_STATE)

    def brightness_for(self, key: str | None) -> int | None:
        return self.brightness_profile().get(key) if key else None

    def brightness_profile(self) -> dict[str, int]:
        return {
            **DEFAULT_BRIGHTNESS,
            **policy.normalize_brightness_profile(self._opt(CONF_BRIGHTNESS)),
        }

    def lux_gate_on(self) -> bool:
        return bool(self._prev_lux_gate)

    def set_ring_mode(self, mode: str | None) -> None:
        self._ring_mode = mode
        for cb in self._listeners:
            cb()

    @property
    def ring_mode(self) -> str | None:
        return self._ring_mode

    # ----- Lux-Gate-Internals (für Debug-Sensor + Diagnostics) -----
    @property
    def startup_ready(self) -> bool:
        return self._startup_ready()

    def gate_internals(self) -> dict[str, Any]:
        season = self._read(CONF_SEASON)
        thresholds = policy.normalize_lux_thresholds(self._opt(CONF_LUX_THRESHOLDS))
        dark, bright = thresholds.get(season, thresholds["winter"])
        return {
            "lux_gate_on": bool(self._prev_lux_gate),
            "tmc_set": self._tmc_set,
            "weather_dark": self._last_weather_dark,
            "startup_ready": self._startup_ready(),
            "startup_recovery_pending": self._startup_recovery.pending,
            "startup_recovery_apply_count": self._startup_recovery.apply_count,
            "lux_fresh": self._last_lux_sample.fresh,
            "lux_sample_reason": self._last_lux_sample.reason,
            "lux_sample_timestamp": (
                self._last_lux_sample.timestamp.isoformat()
                if self._last_lux_sample.timestamp is not None
                else None
            ),
            "season": season,
            "thresholds": {"dark": dark, "bright": bright},
            "lux_samples": len(self._lux_history),
            "apply_enabled": self.apply_enabled,
            "manual_off_active": self._manual_off,
            "prev_mode": self._prev_mode,
            "wake_teardown_targets": self.wake_teardown_targets(),
            "last_wake_teardown": list(self._last_wake_teardown),
        }

    # ----- accessors -----
    @property
    def last_plan(self) -> policy.Plan | None:
        return self._last_plan

    def add_listener(self, cb: CALLBACK_TYPE) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb: CALLBACK_TYPE) -> None:
        if cb in self._listeners:
            self._listeners.remove(cb)
