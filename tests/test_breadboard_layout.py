"""Breadboard layout seats a stepstick on the holes and renders headlessly."""

from pinviz.breadboard import module_column
from pinviz.config_loader import ConfigLoader
from pinviz.model import Device


def test_stepstick_step_pin_is_six_columns_along():
    device = Device(
        name="D1",
        pins=[],
        placement={"column": 2, "role": "module"},
        type_id="tmc2209",
    )
    assert module_column(device, "EN") == 2
    assert module_column(device, "STEP") == 8
    assert module_column(device, "VM") == 2
    assert module_column(device, "IOGND") == 9


def test_breadboard_yaml_renders(tmp_path):
    config = tmp_path / "one.yaml"
    config.write_text(
        """
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
    breadboard: {column: 2, role: module}
connections:
  - board_pin: 36
    device: D1
    device_pin: STEP
    color: "#E2B000"
  - from: {device: Rails, device_pin: "+3V3"}
    to: {device: D1, device_pin: MS1}
    color: "#F08C00"
  - from: {device: Rails, device_pin: "+3V3"}
    to: {device: D1, device_pin: MS2}
    color: "#F08C00"
""",
        encoding="utf-8",
    )
    diagram = ConfigLoader(emit_validation_output=False).load_from_file(config)
    assert diagram.layout_mode == "breadboard"
    output = tmp_path / "one.svg"
    from pinviz.render_svg import SVGRenderer

    SVGRenderer().render(diagram, output)
    text = output.read_text(encoding="utf-8")
    assert "D1" in text
    assert "5V open" in text
    assert "36 STEP" in text
