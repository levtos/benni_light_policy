"""Pure Entscheidungs-Engine für die Light-Policy — HA-frei, voll testbar.

Trennt strikt:
  * `decide()`  — ermittelt den *gewünschten* Plan (mode/preset/brightness/targets)
                  rein aus dem Context. Hier landet die Lastenheft-Logik §4.1/§7.
  * Gating      — apply_enabled / startup / manual_off setzen nur `apply_allowed`
                  + `blockers`, ohne den Plan zu verändern. So bleibt der Plan
                  (und sein scene_hash) für den Phase-4-Shadow-Vergleich aussagekräftig,
                  auch wenn gerade nicht angewendet werden darf.

Der Lux-Gate-Zustand ist zustandsbehaftet (Hysterese) und wird vom Coordinator
gehalten/persistiert; `lux_gate()` ist trotzdem pure (prev_gate als Eingabe).
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from .const import (
    ACTIVITY_HOUSEHOLD,
    ACTIVITY_PRESET_DRIVING,
    ACTIVITY_PRIVATE_TIME,
    ACTIVITY_WORK_HOME,
    BIO_SLEEP_CONTEXTS,
    BIO_WAKING,
    CALENDAR_BIRTHDAY,
    COLOR_TEMP_WAKING,
    COLOR_TEMP_WORK_HOME,
    DEFAULT_BRIGHTNESS,
    DEFAULT_LUX_THRESHOLDS,
    GAMING_ACTIVITY_STATES,
    GROUP_ALL,
    GROUP_CEILING,
    GROUP_MAIN,
    MASTER_PHASE_DAYTIME,
    MEDIA_DEVICE_TV,
    MODE_CINEMA,
    MODE_HOUSEHOLD,
    MODE_IDLE,
    MODE_MUSIC_PARTY,
    MODE_PRESENCE_SIM,
    MODE_PRIVATE_TIME,
    MODE_WAKING,
    MODE_WORK_HOME,
    PRESENCE_SIM_PHASES,
    PRESENCE_SIM_TRIGGERS,
    PRESENCE_TRANSITION_COMING_HOME,
    SEASON_WINTER,
    SUBENTRY_GAMING,
    SUBENTRY_MUSIC,
    SUPPORTED_DAY_PHASES,
    TV_MEDIA_CONTEXTS,
    WEATHER_DARK_DROP_RATIO,
    WEATHER_DARK_ICONS,
)

# Apply-Kind: wie die Apply-Schicht den Plan umsetzt.
APPLY_OFF = "off"      # Hard-Off (alle WZ-Lampen aus)
APPLY_CCT = "cct"      # Kelvin-Modi (work_home, waking): über Kelvin-Look, außer wake_up
                       # (raw_targets, preset_enum=None) → direkter light.turn_on
APPLY_SCENE = "scene"  # benni_scene_presets.apply_look (Look trägt Targets/Off/Crossfade)

# Kalender-Thema (deutsch, aus benni_context) → Preset-Theme (Katalog-Schlüssel).
THEME_MAP = {
    "weihnachten": "christmas",
    "ostern": "easter",
    "halloween": "halloween",
    "karneval": "carnival",
    "fasching": "carnival",
    "carnival": "carnival",
    "geburtstag": "geburtstag",
    "silvester": "silvester",
    "pride": "pride",
    "advent_1": "advent_1",
    "advent_2": "advent_2",
    "advent_3": "advent_3",
    "advent_4": "advent_4",
    "stpatricks": "stpatricks",
}
# Party-Musik-Enums sind noch nicht definiert (Lastenheft OQ-2) — bis dahin
# triggert music_party nicht.
PARTY_TITLES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Context:
    """Snapshot aller Quell-Inputs für eine Entscheidung. None = unknown."""

    bio_state: str | None = None
    day_state: str | None = None          # Detailphase (early_morning ..)
    activity_state: str | None = None
    presence_personal: str | None = None
    presence_household: str | None = None
    guest: bool | None = None             # Eltern anwesend
    season: str | None = None
    calendar_theme: str | None = None
    title_classifier: str | None = None
    entertainment_stable: bool | None = None
    overnight_away: bool | None = None     # Benni übernachtet auswärts
    presence_transition: str | None = None  # coming_home / leaving_home / none
    lux: float | None = None
    weather: str | None = None
    master_phase: str | None = None
    custom_themes: tuple[str, ...] = ()
    # Spider-Web: aus benni_media_state — kein eigenes Power-/Source-Tracking.
    media_device: str | None = None         # "pc"/"ps5"/"nintendo"/"tv"/"none"
    media_context: str | None = None        # "gaming"/"tv"/"streaming"/"private_time"/"idle"


@dataclass
class Plan:
    mode: str
    preset_enum: str | None
    brightness: int | None
    color_temp: int | None
    apply_kind: str
    targets: list[str] = field(default_factory=list)         # logische Gruppen-Namen
    raw_targets: list[str] = field(default_factory=list)     # rohe entity_ids (z.B. Wake-Up Subentry)
    exclusive_off: list[str] = field(default_factory=list)
    reason: str = ""
    lux_gate_on: bool = False
    blockers: list[str] = field(default_factory=list)
    subentry_diagnostics: list[dict[str, str]] = field(default_factory=list)
    apply_allowed: bool = True

    @property
    def scene_hash(self) -> str:
        """16-stelliger Hash über die *wirksamen* (sichtbaren) Plan-Parameter.

        Bewusst OHNE apply_allowed/blockers — der Hash beschreibt die Szenen-Identität,
        nicht das Gating. Konsumenten triggern auf hash-Change; das Gating wird separat
        über den apply_blocked-Sensor signalisiert.
        """
        payload = {
            "mode": self.mode,
            "preset_enum": self.preset_enum,
            "brightness": self.brightness,
            "color_temp": self.color_temp,
            "apply_kind": self.apply_kind,
            "targets": sorted(self.targets),
            "raw_targets": sorted(self.raw_targets),
            "exclusive_off": sorted(self.exclusive_off),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @property
    def debug_reason(self) -> str:
        if not self.subentry_diagnostics:
            return self.reason
        first = self.subentry_diagnostics[0]
        source = first.get("source_id") or first["subentry_id"]
        issue = f"{first['type']}:{source}:{first['code']}"
        if first.get("classifier_value"):
            issue += f"={first['classifier_value']}"
        remaining = len(self.subentry_diagnostics) - 1
        suffix = f" (+{remaining} weitere)" if remaining else ""
        return f"{self.reason} | {issue}{suffix}"[-255:]

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "preset_enum": self.preset_enum,
            "brightness": self.brightness,
            "color_temp": self.color_temp,
            "apply_kind": self.apply_kind,
            "targets": list(self.targets),
            "raw_targets": list(self.raw_targets),
            "exclusive_off": list(self.exclusive_off),
            "reason": self.reason,
            "lux_gate_on": self.lux_gate_on,
            "scene_hash": self.scene_hash,
            "blockers": list(self.blockers),
            "subentry_diagnostics": [dict(item) for item in self.subentry_diagnostics],
            "apply_allowed": self.apply_allowed,
        }


def normalize_lux_thresholds(
    thresholds: dict[str, Any] | None,
) -> dict[str, tuple[int, int]]:
    """Return structurally valid seasonal Lux thresholds with safe defaults.

    Options may contain either the historical ``(dark, bright)`` tuple/list or
    the documented ``{"dark": ..., "bright": ...}`` shape. Invalid, reversed,
    or out-of-range seasons are ignored instead of crashing evaluation.
    """
    normalized = dict(DEFAULT_LUX_THRESHOLDS)
    if not isinstance(thresholds, dict):
        return normalized

    for season, raw in thresholds.items():
        if isinstance(raw, dict):
            values = (raw.get("dark"), raw.get("bright"))
        elif isinstance(raw, (tuple, list)) and len(raw) == 2:
            values = (raw[0], raw[1])
        else:
            continue
        try:
            dark, bright = (int(value) for value in values)
        except (TypeError, ValueError):
            continue
        if not (0 <= dark <= bright <= 100_000):
            continue
        normalized[str(season)] = (dark, bright)
    return normalized


def normalize_brightness_profile(profile: dict[str, Any] | None) -> dict[str, int]:
    """Keep only scalar brightness values and clamp them to HA's 0..255 range."""
    if not isinstance(profile, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, raw in profile.items():
        if not isinstance(key, str) or isinstance(raw, bool):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        normalized[key.strip()] = max(0, min(255, value))
    return {key: value for key, value in normalized.items() if key}


def resolve_priority(raw: Any, default: int) -> int:
    """Parse an optional policy priority without losing an explicit zero."""
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(0, value)


# --------------------------------------------------------------------------- #
# Lux-Gate (R1, Schmitt-Trigger mit saisonalen Schwellen)
# --------------------------------------------------------------------------- #
def lux_gate(
    lux: float | None,
    season: str | None,
    prev_gate: bool | None,
    *,
    day_state_known: bool,
    tmc_set: bool = True,
    weather_dark: bool = False,
    thresholds: dict[str, tuple[int, int]] | None = None,
) -> bool:
    """True = Gate offen (dunkel genug, Licht erlaubt).

    - Day State unbekannt  → Gate zu (Lastenheft Edge Case).
    - weather_dark (R10)   → Gate offen (wetterbedingte Dunkelheit am Tag).
    - Lux unavailable      → letzten Zustand halten (prev), sonst zu.
    - TMC noch nicht gesetzt → einfacher Vergleich ohne Hysterese (R1/R2):
      Gate offen iff lux < dunkel-Schwelle.
    - TMC gesetzt → Schmitt-Trigger: lux < dunkel → an; lux >= hell → aus; dazwischen halten.
    """
    if not day_state_known:
        return False
    if weather_dark:
        return True
    thr = normalize_lux_thresholds(thresholds)
    dark, bright = thr.get(season or SEASON_WINTER, thr[SEASON_WINTER])
    if lux is None:
        return bool(prev_gate)
    if not tmc_set:
        return lux < dark
    if lux < dark:
        return True
    if lux >= bright:
        return False
    return bool(prev_gate)


def bedtime_signal_due(
    day_state: str | None,
    bio_state: str | None,
    awake_minutes: float | None,
    *,
    threshold_minutes: int = 840,
) -> bool:
    """R16: Schlafzimmer-Bettgeh-Signal — early/late_night + awake + ≥14h wach."""
    return (
        day_state in ("early_night", "late_night")
        and bio_state == "awake"
        and awake_minutes is not None
        and awake_minutes >= threshold_minutes
    )


def hallway_should_light(trigger_active: bool, lux_gate_on: bool) -> bool:
    """R14: Flurlicht an iff Trigger (Tür/Bewegung) UND draußen dunkel."""
    return bool(trigger_active and lux_gate_on)


# Modi, die den Wecklicht-Look fahren (raumübergreifend, inkl. Schlafzimmer).
# work_home + waking mappen beide auf Wecklicht (User-Vorgabe FLEET-151).
WAKE_MODES: frozenset[str] = frozenset({MODE_WAKING, MODE_WORK_HOME})


def wake_exit(prev_mode: str | None, new_mode: str | None) -> bool:
    """FLEET-151: True beim Übergang RAUS aus einem Wake-Zustand in einen
    Nicht-Wake-Zustand. Quellenagnostisch — hängt am Policy-STATE (Modus verlässt
    Wake), nicht am Look. Auslöser für den Wake-only-Bereichs-Teardown.

    - prev ∉ WAKE_MODES → False (wir waren nicht im Wake).
    - prev ∈ WAKE_MODES und new ∈ WAKE_MODES → False (waking↔work_home, kein Flicker).
    - prev ∈ WAKE_MODES und new ∉ WAKE_MODES → True (z.B. waking→awake/idle).
    """
    return prev_mode in WAKE_MODES and new_mode not in WAKE_MODES


def stranded_entities(prev: Iterable[str], keep: Iterable[str]) -> list[str]:
    """Cross-Area-Teardown (FLEET-74): Entities, die der vorige Apply konkret
    eingeschaltet hat (`prev`), aber der neue Apply nicht mehr besitzt (`keep`).

    Gibt `prev` MINUS `keep` zurück (reihenfolgestabil, dedupliziert). Substrat für
    den Diff-Teardown: light_policy schaltet rohe Cross-Area-Lampen (Wecklicht in
    Schlafzimmer/Küche via `raw_targets`) direkt ein und ist ihr einziger Owner —
    scene_presets-Looks räumen nur ihre eigene Area über Off-Bindings ab. Ohne
    diesen Diff blieben gestrandete Lampen beim State-Wechsel (waking→awake) an.
    """
    keep_set = set(keep)
    seen: set[str] = set()
    out: list[str] = []
    for eid in prev:
        if eid in keep_set or eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
    return out


def weather_darkness(
    lux_now: float | None,
    lux_baseline: float | None,
    weather: str | None,
    master_phase: str | None,
    *,
    drop_ratio: float = WEATHER_DARK_DROP_RATIO,
) -> bool:
    """R10: True wenn am Tag (morning/midday) der Lux um > drop_ratio gefallen ist
    UND das Wetter-Icon dunkel ist. lux_baseline = Lux vor ~10 min."""
    if master_phase not in MASTER_PHASE_DAYTIME:
        return False
    if (weather or "") not in WEATHER_DARK_ICONS:
        return False
    if lux_now is None or lux_baseline is None or lux_baseline <= 0:
        return False
    return (lux_baseline - lux_now) / lux_baseline > drop_ratio


# --------------------------------------------------------------------------- #
# Preset-/Brightness-Helfer
# --------------------------------------------------------------------------- #
def _effective_theme(ctx: Context) -> str:
    """Event-Thema gewinnt über Jahreszeit, sonst Jahreszeit (Fallback winter)."""
    calendar_theme = (ctx.calendar_theme or "").lower()
    mapped = THEME_MAP.get(calendar_theme)
    if mapped:
        return mapped
    if calendar_theme in ctx.custom_themes:
        return calendar_theme
    return ctx.season or SEASON_WINTER


def _phase_preset(ctx: Context, phase: str) -> str:
    return f"{_effective_theme(ctx)}_{phase}"


def _brightness(profile: dict[str, int], key: str) -> int | None:
    return profile.get(key)


def _phase_brightness(ctx: Context, profile: dict[str, int], phase: str) -> int | None:
    """Theme-specific phase brightness wins over the global phase default."""
    theme_key = f"{_effective_theme(ctx)}_{phase}"
    return profile.get(theme_key, profile.get(phase))


# --------------------------------------------------------------------------- #
# Wohnzimmer-Policies (Lastenheft §4.1) — typisierte, prioritäts-geordnete Registry.
#
# Jede Policy ist ein Evaluator (Context, lux_gate, profile) -> Plan | None.
# `None` = Policy trifft nicht zu. Der Arbiter nimmt die erste zutreffende in
# Prioritätsreihenfolge (== „erste zutreffende Bedingung gewinnt" aus §4.1).
# Diese Registry ist das Fundament für den späteren Hub + Subentries (Phase 2):
# jede dieser Arten wird dort zu einem konfigurierbaren Subentry-Typ.
# --------------------------------------------------------------------------- #
def _awake_phase(ctx: Context) -> str | None:
    return ctx.day_state if ctx.day_state in SUPPORTED_DAY_PHASES else None


def _presence_sim_active(ctx: Context) -> bool:
    """Return whether the documented presence-simulation exception is active."""
    awake_phase = _awake_phase(ctx)
    return bool(
        ctx.presence_personal in PRESENCE_SIM_TRIGGERS
        and awake_phase in PRESENCE_SIM_PHASES
        and not ctx.overnight_away
        and ctx.presence_transition != PRESENCE_TRANSITION_COMING_HOME
    )


def _eval_waking(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    if ctx.bio_state != BIO_WAKING:
        return None
    return Plan(
        mode=MODE_WAKING, preset_enum=MODE_WAKING,   # Look-Ref → Kelvin-Look "waking"
        brightness=_brightness(profile, MODE_WAKING), color_temp=COLOR_TEMP_WAKING,
        apply_kind=APPLY_CCT, targets=[GROUP_ALL], lux_gate_on=gate,
        reason="waking: bio=waking (Weckerlicht, Lux-Gate ignoriert)",
    )


def _eval_sleep_off(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    if ctx.bio_state not in BIO_SLEEP_CONTEXTS:
        return None
    return Plan(
        mode=MODE_IDLE, preset_enum=MODE_IDLE, brightness=0, color_temp=None,
        apply_kind=APPLY_OFF, targets=[], exclusive_off=[GROUP_ALL],
        lux_gate_on=gate, reason=f"hard_off: bio={ctx.bio_state}",
    )


def _eval_lux_off(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    if ctx.presence_personal in PRESENCE_SIM_TRIGGERS and not _presence_sim_active(ctx):
        return Plan(
            mode=MODE_IDLE, preset_enum=MODE_IDLE, brightness=0, color_temp=None,
            apply_kind=APPLY_OFF, targets=[], exclusive_off=[GROUP_ALL],
            lux_gate_on=gate, reason="hard_off: presence_personal away/parents",
        )
    if gate:
        return None
    return Plan(
        mode=MODE_IDLE, preset_enum=MODE_IDLE, brightness=0, color_temp=None,
        apply_kind=APPLY_OFF, targets=[], exclusive_off=[GROUP_ALL],
        lux_gate_on=gate, reason="hard_off: lux_gate off (zu hell)",
    )


def _eval_private_time(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    if ctx.activity_state != ACTIVITY_PRIVATE_TIME:
        return None
    return Plan(
        mode=MODE_PRIVATE_TIME, preset_enum=MODE_PRIVATE_TIME,
        brightness=_brightness(profile, MODE_PRIVATE_TIME), color_temp=None,
        apply_kind=APPLY_SCENE, targets=[GROUP_MAIN], exclusive_off=[GROUP_CEILING],
        lux_gate_on=gate, reason="private_time: activity=private_time",
    )


def _eval_work_home(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    if ctx.activity_state != ACTIVITY_WORK_HOME:
        return None
    return Plan(
        mode=MODE_WORK_HOME, preset_enum=MODE_WORK_HOME,   # Look-Ref → Kelvin-Look "work_home"
        brightness=_brightness(profile, MODE_WORK_HOME), color_temp=COLOR_TEMP_WORK_HOME,
        apply_kind=APPLY_CCT, targets=[GROUP_CEILING, GROUP_MAIN],
        lux_gate_on=gate, reason="work_home: activity=work_home (CCT 5000K)",
    )


def _eval_household(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    if ctx.activity_state != ACTIVITY_HOUSEHOLD:
        return None
    phase = _awake_phase(ctx) or "early_evening"
    return Plan(
        mode=MODE_HOUSEHOLD, preset_enum=_phase_preset(ctx, phase),
        brightness=_phase_brightness(ctx, profile, phase), color_temp=None,
        apply_kind=APPLY_SCENE, targets=[GROUP_MAIN], lux_gate_on=gate,
        reason=f"household: activity=household, phase={phase}",
    )


def _eval_presence_sim(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    # R12: coming_home beendet die Simulation sofort (noch bevor presence_personal flippt).
    awake_phase = _awake_phase(ctx)
    if not _presence_sim_active(ctx):
        return None
    return Plan(
        mode=MODE_PRESENCE_SIM, preset_enum=_phase_preset(ctx, awake_phase),
        brightness=_phase_brightness(ctx, profile, awake_phase), color_temp=None,
        apply_kind=APPLY_SCENE, targets=[GROUP_MAIN], lux_gate_on=gate,
        reason=f"presence_sim: presence={ctx.presence_personal}, phase={awake_phase}",
    )


def _eval_cinema(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
    """Cinema = TV-Watching. Spec-Tightening: braucht ein *positives* TV-Signal,
    sonst kapert es jedes Entertainment (z.B. Gaming am PC) — `entertainment_stable`
    allein ist zu grob. TV-Signal = media_context ∈ {tv, streaming} ODER
    media_device == "tv". Backward-Compat: nur wenn WEDER media_context NOCH
    media_device verdrahtet ist (beide None), gilt die alte lose Regel."""
    if not (ctx.entertainment_stable and not ctx.guest):
        return None
    if ctx.media_context is not None or ctx.media_device is not None:
        tv_signal = (
            ctx.media_context in TV_MEDIA_CONTEXTS
            or ctx.media_device == MEDIA_DEVICE_TV
        )
        if not tv_signal:
            return None
    return Plan(
        mode=MODE_CINEMA, preset_enum=MODE_CINEMA, brightness=None, color_temp=None,
        apply_kind=APPLY_SCENE, targets=[GROUP_MAIN], exclusive_off=[GROUP_CEILING],
        lux_gate_on=gate, reason=f"cinema: entertainment+TV (media_context={ctx.media_context})",
    )


def _eval_dayphase(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan:
    """Terminal — liefert immer einen Plan (saisonales Preset der Tagesphase)."""
    phase = _awake_phase(ctx) or "early_evening"
    return Plan(
        mode=phase, preset_enum=_phase_preset(ctx, phase),
        brightness=_phase_brightness(ctx, profile, phase), color_temp=None,
        apply_kind=APPLY_SCENE, targets=[GROUP_MAIN], lux_gate_on=gate,
        reason=f"dayphase fallback: {phase}",
    )


@dataclass(frozen=True)
class PolicyDef:
    """Typisierte Wohnzimmer-Policy. priority: kleiner = höher (§4.1)."""

    kind: str
    priority: int
    evaluate: Callable[[Context, bool, dict[str, int]], Plan | None]


# Prioritäten (§4.1). Kleiner = höher.
PRIO_WAKING = 1
PRIO_IDLE_SLEEP = 2
PRIO_IDLE_LUX = 3
PRIO_PRIVATE_TIME = 4
PRIO_WORK_HOME = 5
PRIO_HOUSEHOLD = 6
PRIO_PRESENCE_SIM = 7
PRIO_MUSIC_PARTY = 8
PRIO_GAMING = 9     # default Gaming-Priorität, pro Subentry per source_priority überschreibbar
PRIO_CINEMA = 11    # zwischen Nintendo (10) und PC (12) per alter Logik
PRIO_DAYPHASE = 13  # absoluter Fallback (verschoben von 12 wg. PC-Gaming auf 12)

# Kern-Policies: immer vorhanden, brauchen nur Foundation + Lampengruppen (Hub).
# gaming/music_party sind NICHT im Kern — sie werden per Subentry beigesteuert
# (eigener Title-Classifier + Mapping) und über `extra_policies` eingespeist.
LIVING_ROOM_POLICIES: tuple[PolicyDef, ...] = (
    PolicyDef("waking", PRIO_WAKING, _eval_waking),
    PolicyDef("idle_sleep", PRIO_IDLE_SLEEP, _eval_sleep_off),
    PolicyDef("idle_lux", PRIO_IDLE_LUX, _eval_lux_off),
    PolicyDef("private_time", PRIO_PRIVATE_TIME, _eval_private_time),
    PolicyDef("work_home", PRIO_WORK_HOME, _eval_work_home),
    PolicyDef("household", PRIO_HOUSEHOLD, _eval_household),
    PolicyDef("presence_sim", PRIO_PRESENCE_SIM, _eval_presence_sim),
    PolicyDef("cinema", PRIO_CINEMA, _eval_cinema),
    PolicyDef("dayphase", PRIO_DAYPHASE, _eval_dayphase),
)

POLICY_KINDS: tuple[str, ...] = tuple(p.kind for p in LIVING_ROOM_POLICIES)


# --- Subentry-Minihubs (Policy-Kategorie mit interner Mapping-Tabelle) -----------
def _classifier_mapping_issue(
    classifier_value: str | None, mappings: dict[str, str]
) -> str | None:
    if not isinstance(classifier_value, str) or not classifier_value.strip():
        return "classifier_unavailable"
    preset = mappings.get(classifier_value)
    if not isinstance(preset, str) or not preset.strip():
        return "classifier_unmapped"
    return None


def mapping_subentry_diagnostics(
    subentry_id: str,
    subentry_type: str,
    source_id: str,
    classifier_value: str | None,
    mappings: Any,
    ctx: Context,
    *,
    require_birthday: bool = True,
) -> list[dict[str, str]]:
    """Explain ineffective Gaming/Music rules without changing arbitration."""
    if subentry_type not in (SUBENTRY_GAMING, SUBENTRY_MUSIC):
        return []
    base = {"subentry_id": subentry_id, "type": subentry_type}
    if subentry_type == SUBENTRY_GAMING and source_id:
        base["source_id"] = source_id
    issues: list[dict[str, str]] = []
    if subentry_type == SUBENTRY_GAMING and not source_id:
        issues.append({**base, "code": "missing_source_id"})
    if not isinstance(mappings, dict) or not mappings:
        code = "missing_mappings" if not mappings else "invalid_mappings"
        issues.append({**base, "code": code})
    if issues:
        return issues

    if subentry_type == SUBENTRY_GAMING:
        active = ctx.media_device == source_id and ctx.activity_state in GAMING_ACTIVITY_STATES
    else:
        active = (
            ctx.activity_state in ACTIVITY_PRESET_DRIVING
            and (not require_birthday or (ctx.calendar_theme or "").lower() == CALENDAR_BIRTHDAY)
        )
    if active:
        issue = _classifier_mapping_issue(classifier_value, mappings)
        if issue:
            detail = {**base, "code": issue}
            if isinstance(classifier_value, str) and classifier_value.strip():
                detail["classifier_value"] = classifier_value
            issues.append(detail)
    return issues


def make_gaming_policy(
    source_id: str,
    classifier_value: str | None,
    mappings: dict[str, str],
    *,
    priority: int = PRIO_GAMING,
    target: str = GROUP_MAIN,
) -> PolicyDef:
    """Gaming-Minihub: eine Subentry pro Quelle (PC, PS5, Nintendo …).
    Gate: media_device == source_id (Source ist aktiv) + activity in
    GAMING_ACTIVITY_STATES (`gaming` kanonisch, `free_time`/`idle` rückwärts-
    kompatibel; `pc_active` bewusst ausgeschlossen — nur „PC an").
    Mapping classifier_value → Look-Ref (Name/Slug). Mehrere Quellen gleichzeitig:
    Konflikt wird über priority gelöst (PS5=9 < Nintendo=10 < Cinema=11 < PC=12).
    Die effektive Gaming-Priorität kann den Lux-Hard-Off nicht überstimmen:
    persistierte source_priority-Werte unter PRIO_IDLE_LUX werden auf diese
    Grenze angehoben; Werte an oder über der Grenze behalten ihre Reihenfolge.
    """

    def _ev(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
        if ctx.media_device != source_id:
            return None
        # Eigenes Gaming-Gate (nicht ACTIVITY_PRESET_DRIVING, das die Musik-Policy
        # nutzt): der Activity-Vertrag liefert bei aktivem Spiel `gaming`.
        if ctx.activity_state not in GAMING_ACTIVITY_STATES:
            return None
        if _classifier_mapping_issue(classifier_value, mappings):
            return None
        preset = mappings[classifier_value].strip()
        # Brightness wie bei den Tagesphasen-Modi aus dem Profil (theme_phase) —
        # Gaming-Looks sollen die Tageszeit-/Theme-Helligkeit respektieren, nicht
        # auf der Preset-Default (255) landen. (Doku: „Brightness aus der Tagesphase".)
        phase = _awake_phase(ctx) or "early_evening"
        return Plan(
            mode=f"gaming:{source_id}:{classifier_value}", preset_enum=preset,
            brightness=_phase_brightness(ctx, profile, phase),
            color_temp=None, apply_kind=APPLY_SCENE,
            targets=[target], lux_gate_on=gate,
            reason=f"gaming:{source_id}: classifier={classifier_value} → {preset} @{phase}",
        )

    effective_priority = max(PRIO_IDLE_LUX, priority)
    return PolicyDef(f"gaming_{source_id}", effective_priority, _ev)


def make_music_policy(
    classifier_value: str | None,
    mappings: dict[str, str],
    *,
    require_birthday: bool = True,
    priority: int = PRIO_MUSIC_PARTY,
    target: str = GROUP_MAIN,
) -> PolicyDef:
    """Musik-Minihub: classifier_value → Look-Ref (Name/Slug) (optional Geburtstag-Gate).
    Strukturgleich zum Gaming-Minihub, ohne source_id (Musik-Quelle ist
    typischerweise singulär; bei Bedarf später erweiterbar)."""

    def _ev(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
        if ctx.activity_state not in ACTIVITY_PRESET_DRIVING:
            return None
        if require_birthday and (ctx.calendar_theme or "").lower() != CALENDAR_BIRTHDAY:
            return None
        if _classifier_mapping_issue(classifier_value, mappings):
            return None
        preset = mappings[classifier_value].strip()
        phase = _awake_phase(ctx) or "early_evening"
        return Plan(
            mode=MODE_MUSIC_PARTY, preset_enum=preset,
            brightness=_phase_brightness(ctx, profile, phase),
            color_temp=None, apply_kind=APPLY_SCENE,
            targets=[target], lux_gate_on=gate,
            reason=f"music: classifier={classifier_value} → {preset} @{phase}",
        )

    return PolicyDef("music_party", priority, _ev)


def make_wake_up_policy(
    targets: list[str],
    *,
    priority: int = 0,
) -> PolicyDef:
    """Wake-Up-Subentry (R6): überschreibt das Kern-`waking` und richtet die
    Helligkeit/CCT-Sequenz auf die konfigurierten Lampen aus (vom wake_planner
    via bio_state=waking ausgelöst). Priorität 0 = vor dem Kern-`waking`."""

    def _ev(ctx: Context, gate: bool, profile: dict[str, int]) -> Plan | None:
        if ctx.bio_state != BIO_WAKING or not targets:
            return None
        return Plan(
            mode=MODE_WAKING, preset_enum=None,
            brightness=_brightness(profile, MODE_WAKING), color_temp=COLOR_TEMP_WAKING,
            apply_kind=APPLY_CCT, raw_targets=list(targets), lux_gate_on=gate,
            reason=f"wake_up: bio=waking → {len(targets)} Lampen",
        )

    return PolicyDef("wake_up", priority, _ev)


def _arbitrate(
    ctx: Context, lux_gate_on: bool, profile: dict[str, int],
    extra_policies: Iterable[PolicyDef],
) -> Plan:
    """Kern-Policies + Subentry-Policies, nach Priorität; erste zutreffende gewinnt."""
    ordered = sorted([*LIVING_ROOM_POLICIES, *extra_policies], key=lambda p: p.priority)
    for pol in ordered:
        result = pol.evaluate(ctx, lux_gate_on, profile)
        if result is not None:
            return result
    return _eval_dayphase(ctx, lux_gate_on, profile)  # Sicherheitsnetz


def decide(
    ctx: Context,
    *,
    lux_gate_on: bool,
    startup_ready: bool,
    apply_enabled: bool,
    manual_off_active: bool,
    brightness_profile: dict[str, int] | None = None,
    extra_policies: Iterable[PolicyDef] = (),
) -> Plan:
    """Vollständige Entscheidung inkl. Gating-Overlay.

    `extra_policies` = vom Hub aus Subentries gebaute Policies (Gaming/Musik),
    die mit den Kern-Policies nach Priorität konkurrieren.
    """
    profile = {**DEFAULT_BRIGHTNESS, **normalize_brightness_profile(brightness_profile)}
    plan = _arbitrate(ctx, lux_gate_on, profile, extra_policies)

    # Gating-Overlay — verändert nur apply_allowed/blockers, nie den Plan selbst.
    if not apply_enabled:
        plan.blockers.append("apply_disabled")
        plan.apply_allowed = False
    if not startup_ready:
        plan.blockers.append("startup_block")
        plan.apply_allowed = False
    if manual_off_active:
        # R9 — Hold gewinnt: kein Hard-Off, kein Einschalten.
        plan.blockers.append("manual_off")
        plan.apply_allowed = False

    return plan
