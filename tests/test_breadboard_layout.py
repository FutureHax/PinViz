"""Breadboard layout seats stepsticks on the holes and renders headlessly."""

import pytest

from pinviz.breadboard import module_row_offset, stepstick_seat
from pinviz.config_loader import ConfigLoader
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


def test_stepstick_seats_with_dir_at_the_top():
    device = Device(name="D1", pins=[], type_id="tmc2209")
    assert stepstick_seat(device, "DIR") == ("b", 0)
    assert stepstick_seat(device, "STEP") == ("b", 1)
    assert stepstick_seat(device, "EN") == ("b", 7)
    assert stepstick_seat(device, "IOGND") == ("f", 0)
    assert module_row_offset(device, "VM") == 7


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
