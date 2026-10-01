"""Breadboard layout seats stepsticks on the holes and renders headlessly."""

import pytest

from pinviz.breadboard import (
    STEPSTICK_LABELS,
    STEPSTICK_LEFT,
    STEPSTICK_RIGHT,
    BreadboardRenderer,
    module_row_offset,
    stepstick_seat,
)
from pinviz.config_loader import ConfigLoader
from pinviz.devices import get_registry
from pinviz.model import Device
from pinviz.render_svg import SVGRenderer

ONE_DRIVER = """
title: "One stepstick"
board: raspberry_pi_4
layout: breadboard
show_title: true
show_board_name: false
devices:
  - type: breadboard_rail
    name: Rails
    breadboard: {role: rail}
  - type: tmc2209
    name: D1
    breadboard: {role: module}
{extra_devices}
connections:
  - {board_pin: 36, device: D1, device_pin: STEP, color: "#E2B000"}
  - from: {device: Rails, device_pin: "+3V3"}
    to: {device: D1, device_pin: MS1}
    color: "#F08C00"
  - from: {device: Rails, device_pin: "+24V"}
    to: {device: D1, device_pin: VM}
    color: "#D31212"
{extra_connections}
"""


def _render(tmp_path, extra_devices="", extra_connections=""):
    config = tmp_path / "one.yaml"
    config.write_text(
        ONE_DRIVER.replace("{extra_devices}", extra_devices).replace(
            "{extra_connections}", extra_connections
        ),
        encoding="utf-8",
    )
    diagram = ConfigLoader(emit_validation_output=False).load_from_file(config)
    output = tmp_path / "one.svg"
    SVGRenderer().render(diagram, output)
    return diagram, output.read_text(encoding="utf-8")


def test_stepstick_seats_as_the_silkscreen_reads():
    """EN top left, DIR bottom left, VM top right, GND bottom right."""
    device = Device(name="D1", pins=[], type_id="tmc2209")
    assert STEPSTICK_LEFT == ("EN", "MS1", "MS2", "PDN", "PDN_ALT", "CLK", "STEP", "DIR")
    assert STEPSTICK_RIGHT == ("VM", "VMGND", "A2", "A1", "B1", "B2", "VDD", "IOGND")
    assert stepstick_seat(device, "EN") == ("b", 0)
    assert stepstick_seat(device, "STEP") == ("b", 6)
    assert stepstick_seat(device, "DIR") == ("b", 7)
    assert stepstick_seat(device, "VM") == ("f", 0)
    assert stepstick_seat(device, "A2") == ("f", 2)
    assert stepstick_seat(device, "VDD") == ("f", 6)
    assert module_row_offset(device, "IOGND") == 7


def test_stepstick_part_matches_the_seat_order():
    """The device JSON lists the pins in the same order the renderer seats them."""
    device = get_registry().create("tmc2209")
    names = tuple(pin.name for pin in device.pins)
    assert names == STEPSTICK_LEFT + STEPSTICK_RIGHT
    assert STEPSTICK_LABELS == {"PDN_ALT": "PDN", "VMGND": "GND", "IOGND": "GND"}


def test_unknown_stepstick_pin_is_rejected():
    device = Device(name="D1", pins=[], type_id="tmc2209")
    with pytest.raises(ValueError, match="no stepstick pin"):
        stepstick_seat(device, "UART")


def test_breadboard_yaml_renders(tmp_path):
    diagram, text = _render(tmp_path)
    assert diagram.layout_mode == "breadboard"
    assert "D1" in text
    assert "5V open" in text
    assert "36 STEP D1" in text


def test_capacitor_plugs_into_the_rails(tmp_path):
    _diagram, text = _render(
        tmp_path,
        extra_devices="""  - type: electrolytic
    name: C1
    breadboard: {role: capacitor}""",
        extra_connections="""  - from: {device: C1, device_pin: "+"}
    to: {device: Rails, device_pin: "+24V"}
    color: "#D31212"
  - from: {device: C1, device_pin: "-"}
    to: {device: Rails, device_pin: MGND}
    color: "#1A1A1A\"""",
    )
    assert "C1" in text
    assert "stripe (-) on GND" in text


def test_floating_part_fails_the_render(tmp_path):
    with pytest.raises(ValueError, match="no connections for C1"):
        _render(
            tmp_path,
            extra_devices="""  - type: electrolytic
    name: C1
    breadboard: {role: capacitor}""",
        )


def test_en_hops_up_the_board_edge_to_the_top_pin(tmp_path):
    """EN leaves the header after STEP and DIR but is the top pin, so it lands
    below the ribbon and climbs the left edge once instead of crossing them."""
    _diagram, text = _render(
        tmp_path,
        extra_connections="""  - {board_pin: 38, device: D1, device_pin: DIR, color: "#1F9D55"}
  - {board_pin: 40, device: D1, device_pin: EN, color: "#7C3AED"}
  - from: {device: Rails, device_pin: MGND}
    to: {device: D1, device_pin: VMGND}
    color: "#1A1A1A"
  - from: {device: Rails, device_pin: MGND}
    to: {device: D1, device_pin: IOGND}
    color: "#1A1A1A"
  - from: {device: Rails, device_pin: "+3V3"}
    to: {device: D1, device_pin: VDD}
    color: "#F08C00\"""",
    )
    assert "40 EN D1" in text
    assert ">PDN<" in text
    assert "PDN_UART" not in text
    assert ">VDD<" in text
    assert ">A2<" in text and ">A1<" in text and ">B1<" in text and ">B2<" in text
    renderer = BreadboardRenderer()
    renderer.render(_diagram, tmp_path / "again.svg")
    y_en = renderer.geo.y(renderer.module_row["D1"])
    y_dir = renderer.geo.y(renderer.module_row["D1"] + 7)
    # The hop turns the corner at the board edge, on the EN row, below DIR.
    assert f"Q {renderer.x_hop:.1f} {y_en:.1f}" in text
    assert f"Q {renderer.x_hop:.1f} {y_dir + 0.9 * renderer.geo.pitch:.1f}" in text


def test_logic_gnd_must_use_the_right_hand_rail(tmp_path):
    with pytest.raises(ValueError, match="right-hand ground rail"):
        _render(
            tmp_path,
            extra_connections="""  - from: {device: Rails, device_pin: GND}
    to: {device: D1, device_pin: IOGND}
    color: "#1A1A1A\"""",
        )
