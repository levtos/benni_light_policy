"""HA-free contract tests for native subentry editing and title migration."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types
from types import SimpleNamespace

import lp_const as C
import pytest
import voluptuous as vol

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG_DIR = os.path.join(ROOT, "custom_components", "benni_light_policy")


@pytest.fixture
def config_flow(monkeypatch):
    """Load the real flow with small Home Assistant API doubles."""
    ha = types.ModuleType("homeassistant")
    ha.__path__ = []
    entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    data_flow = types.ModuleType("homeassistant.data_entry_flow")
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.__path__ = []
    selector = types.ModuleType("homeassistant.helpers.selector")

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    class ConfigSubentryFlow:
        def _get_entry(self):
            return self.parent_entry

        def _get_reconfigure_subentry(self):
            return self.subentry

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_update_and_abort(self, entry, subentry, **kwargs):
            return {"type": "abort", "entry": entry, "subentry": subentry, **kwargs}

    class SelectorConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class Selector:
        def __init__(self, config=None):
            self.config = config

        def __call__(self, value):
            return value

    entries.ConfigEntry = type("ConfigEntry", (), {})
    entries.ConfigFlow = ConfigFlow
    entries.ConfigSubentryFlow = ConfigSubentryFlow
    entries.OptionsFlow = type("OptionsFlow", (), {})
    core.callback = lambda fn: fn
    data_flow.FlowResult = dict
    for name in ("Entity", "Area", "Boolean", "Text", "Select"):
        setattr(selector, f"{name}SelectorConfig", SelectorConfig)
        setattr(selector, f"{name}Selector", Selector)
    selector.SelectSelectorMode = SimpleNamespace(DROPDOWN="dropdown")

    for name, module in (
        ("homeassistant", ha),
        ("homeassistant.config_entries", entries),
        ("homeassistant.core", core),
        ("homeassistant.data_entry_flow", data_flow),
        ("homeassistant.helpers", helpers),
        ("homeassistant.helpers.selector", selector),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    helpers.selector = selector

    spec = importlib.util.spec_from_file_location(
        "lp_pure_pkg.config_flow_issue51", os.path.join(PKG_DIR, "config_flow.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flow(flow_type, subentry=None):
    flow = flow_type()
    flow.hass = SimpleNamespace(states={})
    flow.parent_entry = SimpleNamespace(entry_id="parent")
    flow.subentry = subentry
    return flow


def test_source_selector_has_known_tokens_custom_path_and_rejects_entity_id(config_flow):
    select = config_flow._SOURCE_ID
    assert select.config.options == list(C.GAMING_DEFAULT_PRIORITY)
    assert select.config.custom_value is True
    assert config_flow.SELECTORS[C.CONF_SOURCE_ID] is select
    assert config_flow.SELECTORS[C.CONF_SOURCE_ID]("ps5") == "ps5"
    assert config_flow.SELECTORS[C.CONF_SOURCE_ID]("future_console") == "future_console"
    with pytest.raises(vol.Invalid):
        config_flow._source_id("media_player.living_ps5")


@pytest.mark.parametrize("reconfigure", [False, True])
def test_gaming_form_renders_and_saves_custom_source(config_flow, reconfigure):
    subentry = SimpleNamespace(title="Gaming", data={C.CONF_SOURCE_ID: "pc"})
    flow = _flow(config_flow.GamingSubentryFlow, subentry)
    step = flow.async_step_reconfigure if reconfigure else flow.async_step_user
    form = asyncio.run(step())
    source_field = next(
        value for key, value in form["data_schema"].schema.items()
        if key.schema == C.CONF_SOURCE_ID
    )
    assert source_field is config_flow._SOURCE_ID
    submitted = form["data_schema"]({C.CONF_SOURCE_ID: "future_console"})
    result = asyncio.run(step(submitted))
    assert result["type"] == ("abort" if reconfigure else "create_entry")
    assert result["data"][C.CONF_SOURCE_ID] == "future_console"


@pytest.mark.parametrize("reconfigure", [False, True])
def test_gaming_form_rejects_entity_id_with_field_error(config_flow, reconfigure):
    subentry = SimpleNamespace(title="Gaming", data={C.CONF_SOURCE_ID: "pc"})
    flow = _flow(config_flow.GamingSubentryFlow, subentry)
    step = flow.async_step_reconfigure if reconfigure else flow.async_step_user
    result = asyncio.run(step({
        C.CONF_SOURCE_ID: "media_player.living_ps5",
        C.CONF_CLASSIFIER_ENTITY: "sensor.title_classifier_ps5_enum",
        "mapping_value_0": "1",
        "mapping_preset_0": "diablo",
    }))
    assert result["type"] == "form"
    assert result["errors"] == {C.CONF_SOURCE_ID: "invalid_source_id"}
    defaults = result["data_schema"]({})
    assert defaults[C.CONF_SOURCE_ID] == "media_player.living_ps5"
    assert defaults["mapping_value_0"] == "1"
    assert defaults["mapping_preset_0"] == "diablo"


def test_gaming_reconfigure_repairs_existing_entity_id_without_losing_mappings(config_flow):
    mappings = {"1": "diablo"}
    subentry = SimpleNamespace(title="PS5 Gaming", data={
        C.CONF_SOURCE_ID: "media_player.living_ps5",
        C.CONF_MAPPINGS: mappings,
    })
    flow = _flow(config_flow.GamingSubentryFlow, subentry)
    form = asyncio.run(flow.async_step_reconfigure())
    assert form["data_schema"]({})[C.CONF_SOURCE_ID] == "media_player.living_ps5"
    submitted = form["data_schema"]({C.CONF_SOURCE_ID: "ps5"})
    result = asyncio.run(flow.async_step_reconfigure(submitted))
    assert result["type"] == "abort"
    assert result["data"][C.CONF_SOURCE_ID] == "ps5"
    assert result["data"][C.CONF_MAPPINGS] == mappings


def test_gaming_reconfigure_prefills_and_preserves_all_mappings(config_flow):
    mappings = {str(i): f"look-{i}" for i in range(9)}
    subentry = SimpleNamespace(
        title="Gaming (sensor.old)",
        data={
            C.CONF_SOURCE_ID: "pc",
            C.CONF_CLASSIFIER_ENTITY: "sensor.old",
            C.CONF_SOURCE_PRIORITY: 12,
            C.CONF_MAPPINGS: mappings,
            "future_field": "retained",
        },
    )
    flow = _flow(config_flow.GamingSubentryFlow, subentry)
    form = asyncio.run(flow.async_step_reconfigure())
    assert form["step_id"] == "reconfigure"
    defaults = form["data_schema"]({})
    assert defaults[C.CONF_SOURCE_ID] == "pc"
    assert defaults[C.CONF_CLASSIFIER_ENTITY] == "sensor.old"
    assert defaults[C.CONF_SOURCE_PRIORITY] == 12
    assert defaults["mapping_value_0"] == "0"
    assert defaults["mapping_preset_0"] == "look-0"

    submitted = form["data_schema"]({
        C.CONF_SOURCE_ID: "ps5",
        C.CONF_CLASSIFIER_ENTITY: "sensor.title_classifier_ps5_enum",
        C.CONF_SOURCE_PRIORITY: 9,
    })
    result = asyncio.run(flow.async_step_reconfigure(submitted))
    assert result["type"] == "abort"
    assert result["subentry"] is subentry
    assert result["data"][C.CONF_SOURCE_ID] == "ps5"
    assert result["data"][C.CONF_CLASSIFIER_ENTITY] == "sensor.title_classifier_ps5_enum"
    assert result["data"][C.CONF_SOURCE_PRIORITY] == 9
    assert result["data"][C.CONF_MAPPINGS] == mappings
    assert result["data"]["future_field"] == "retained"
    assert result["title"] == "Gaming (sensor.title_classifier_ps5_enum)"


def test_gaming_reconfigure_without_mapping_fields_keeps_mappings(config_flow):
    mappings = {"2": "overwatch"}
    subentry = SimpleNamespace(title="PC Gaming", data={
        C.CONF_SOURCE_ID: "pc",
        C.CONF_CLASSIFIER_ENTITY: "sensor.title_classifier_pc_enum",
        C.CONF_MAPPINGS: mappings,
    })
    flow = _flow(config_flow.GamingSubentryFlow, subentry)
    result = asyncio.run(flow.async_step_reconfigure({C.CONF_SOURCE_PRIORITY: 11}))
    assert result["data"][C.CONF_MAPPINGS] == mappings
    assert result["title"] == "PC Gaming"


@pytest.mark.parametrize("flow_name,stype,data", [
    ("MusicSubentryFlow", C.SUBENTRY_MUSIC, {C.CONF_CLASSIFIER_ENTITY: "sensor.music", C.CONF_MAPPINGS: {"1": "jazz"}}),
    ("NotificationRingSubentryFlow", C.SUBENTRY_NOTIFICATION_RING, {C.CONF_RING_TARGETS: ["light.ring"], C.CONF_MAPPINGS: {"gaming": "pulse"}}),
    ("HallwaySubentryFlow", C.SUBENTRY_HALLWAY, {C.CONF_HALLWAY_LIGHT: "light.hall"}),
    ("BathroomSubentryFlow", C.SUBENTRY_BATHROOM, {C.CONF_BATHROOM_LIGHT: "switch.bath"}),
    ("WakeUpSubentryFlow", C.SUBENTRY_WAKE_UP, {C.CONF_WAKE_UP_TARGETS: ["light.bed"]}),
])
def test_all_other_subentry_types_reconfigure_without_data_loss(config_flow, flow_name, stype, data):
    subentry = SimpleNamespace(title=f"Custom {stype}", data=data)
    flow = _flow(getattr(config_flow, flow_name), subentry)
    form = asyncio.run(flow.async_step_reconfigure())
    submitted = form["data_schema"]({})
    result = asyncio.run(flow.async_step_reconfigure(submitted))
    assert result["type"] == "abort"
    assert result["title"] == subentry.title
    for key, value in data.items():
        assert result["data"][key] == value


@pytest.mark.parametrize("flow_name,stype,classifier", [
    ("GamingSubentryFlow", C.SUBENTRY_GAMING, "sensor.title_classifier_ps5_enum"),
    ("MusicSubentryFlow", C.SUBENTRY_MUSIC, "sensor.music_classifier"),
])
def test_new_classifier_subentry_gets_entity_default_title(config_flow, flow_name, stype, classifier):
    flow = _flow(getattr(config_flow, flow_name))
    form = asyncio.run(flow.async_step_user())
    values = {C.CONF_CLASSIFIER_ENTITY: classifier}
    if stype == C.SUBENTRY_GAMING:
        values[C.CONF_SOURCE_ID] = "ps5"
    result = asyncio.run(flow.async_step_user(form["data_schema"](values)))
    assert classifier in result["title"]
    assert result["data"][C.CONF_CLASSIFIER_ENTITY] == classifier


def test_setup_title_migration_updates_only_legacy_defaults():
    titles = importlib.import_module("lp_pure_pkg.subentry_titles")
    old_pc = SimpleNamespace(
        subentry_type=C.SUBENTRY_GAMING, title="Gaming",
        data={C.CONF_CLASSIFIER_ENTITY: "sensor.title_classifier_pc_enum"},
    )
    old_ps5 = SimpleNamespace(
        subentry_type=C.SUBENTRY_GAMING, title="Gaming",
        data={C.CONF_CLASSIFIER_ENTITY: "sensor.title_classifier_ps5_enum"},
    )
    custom = SimpleNamespace(
        subentry_type=C.SUBENTRY_GAMING, title="Bennis PS5",
        data={C.CONF_CLASSIFIER_ENTITY: "sensor.title_classifier_ps5_enum"},
    )
    entry = SimpleNamespace(subentries={"pc": old_pc, "ps5": old_ps5, "custom": custom})
    calls = []

    def update(actual_entry, subentry, *, title):
        assert actual_entry is entry
        calls.append((subentry, title))
        subentry.title = title

    titles.migrate_subentry_titles(entry, update)
    assert calls == [
        (old_pc, "Gaming (sensor.title_classifier_pc_enum)"),
        (old_ps5, "Gaming (sensor.title_classifier_ps5_enum)"),
    ]
    assert custom.title == "Bennis PS5"
    titles.migrate_subentry_titles(entry, update)
    assert len(calls) == 2
