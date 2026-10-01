"""Pictorial solderless-breadboard layout.

``layout: breadboard`` draws the real board artwork beside a vertical
breadboard with plug-in modules seated on its holes, and colored jumpers
between the actual pins. Schematic layout is unchanged.

Layout rules, chosen so that different modules' wires never cross:

- The breadboard stands upright. Rails run top to bottom: logic ground and
  3.3 V on the left, motor ground and motor supply on the right.
- A 16-pin stepstick straddles the trench, one 8-pin column on row ``b``
  and one on row ``f`` (0.6 inch apart), seated as the silkscreen reads
  from above: EN top left, DIR bottom left, VM top right, GND bottom
  right. Modules stack top to bottom in YAML order, so they should be
  listed in the order their signals leave the header.
- Each module's header wires travel as one ribbon, sorted by header
  height, from beside the header to row ``a`` beside the module. A wire
  whose pin sits above the pins of wires that leave the header before it
  (EN, the top pin, with STEP and DIR at the bottom) cannot reach its row
  without crossing them, so it lands below the ribbon and climbs the left
  edge of the breadboard to its row: one deliberate hop per module instead
  of a tangle.
- Rail power reaches a module as a short stub (MS1, MS2, VM, both GNDs)
  or a lane under the module (VIO), never across another module's ribbon.
- A motor sits beside its own module; coil leads are straight.
- Logic GND and motor MGND are tied at the bottom of the board whenever
  MGND is used; PinViz rejects a Rails-to-Rails connection as a cycle.
- Any device with no connection fails the render.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import drawsvg as draw

from .model import Connection, Device, Diagram

# BIGTREETECH TMC2209 V1.2/V1.3 silkscreen viewed from above, both columns top
# to bottom: EN top left, DIR bottom left, VM top right, GND bottom right.
STEPSTICK_LEFT = ("EN", "MS1", "MS2", "PDN_UART", "PDN_UART_ALT", "CLK", "STEP", "DIR")
STEPSTICK_RIGHT = ("VM", "VMGND", "2B", "2A", "1A", "1B", "VIO", "IOGND")
STEPSTICK_PINS = STEPSTICK_LEFT + STEPSTICK_RIGHT
# Silkscreen text for pins whose PinViz names had to be made unique.
STEPSTICK_LABELS = {"PDN_UART_ALT": "PDN_UART", "VMGND": "GND", "IOGND": "GND"}

RAIL_PINS = ("GND", "+3V3", "MGND", "+24V")

PI_ORIGIN = (24.0, 78.0)
PI_SCALE = 2.35
PITCH = 22.0
MODULE_ROWS = 12
FIRST_MODULE_ROW = 4
RIBBON_SPACING = 9.0
FONT = "Arial, sans-serif"
LABEL_CHAR_WIDTH = 7.4

GRAY = "#5C6570"
RAIL_COLORS = {"GND": "#2C4A6E", "+3V3": "#F08C00", "MGND": "#2C4A6E", "+24V": "#D31212"}
RAIL_TITLES = {"GND": "GND", "+3V3": "3.3 V", "MGND": "GND", "+24V": "+24 V"}


@dataclass
class Geometry:
    """Hole coordinates of an upright breadboard."""

    left: float
    top: float
    rows: int
    pitch: float = PITCH
    x: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        p = self.pitch
        self.x["GND"] = self.left + 18
        self.x["+3V3"] = self.x["GND"] + p
        start = self.x["+3V3"] + 1.7 * p
        for index, name in enumerate("abcde"):
            self.x[name] = start + index * p
        start = self.x["e"] + 3 * p
        for index, name in enumerate("fghij"):
            self.x[name] = start + index * p
        self.x["MGND"] = self.x["j"] + 1.7 * p
        self.x["+24V"] = self.x["MGND"] + p

    def y(self, row: float) -> float:
        return self.top + 16 + row * self.pitch

    @property
    def right(self) -> float:
        return self.x["+24V"] + 18

    @property
    def bottom(self) -> float:
        return self.y(self.rows - 1) + 16


def stepstick_seat(device: Device, pin_name: str) -> tuple[str, int]:
    """Return ``(column, row offset)`` of a stepstick pin from the module's first row."""
    if pin_name in STEPSTICK_LEFT:
        return "b", STEPSTICK_LEFT.index(pin_name)
    if pin_name in STEPSTICK_RIGHT:
        return "f", STEPSTICK_RIGHT.index(pin_name)
    raise ValueError(f"{device.name} has no stepstick pin {pin_name}")


def _role(device: Device) -> str:
    if device.type_id == "tmc2209":
        return "module"
    return (device.placement or {}).get("role", "module")


def _rounded(points: list[tuple[float, float]], radius: float = 7.0) -> str:
    """Polyline path with rounded corners."""
    if len(points) < 2:
        raise ValueError("A wire needs two points")
    path = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for index in range(1, len(points) - 1):
        (x0, y0), (x1, y1), (x2, y2) = points[index - 1], points[index], points[index + 1]
        in_len = max(abs(x1 - x0), abs(y1 - y0))
        out_len = max(abs(x2 - x1), abs(y2 - y1))
        r = min(radius, in_len / 2, out_len / 2)
        ax = x1 - (r if x1 > x0 else -r if x1 < x0 else 0)
        ay = y1 - (r if y1 > y0 else -r if y1 < y0 else 0)
        bx = x1 + (r if x2 > x1 else -r if x2 < x1 else 0)
        by = y1 + (r if y2 > y1 else -r if y2 < y1 else 0)
        path.append(f"L {ax:.1f} {ay:.1f} Q {x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}")
    path.append(f"L {points[-1][0]:.1f} {points[-1][1]:.1f}")
    return " ".join(path)


def check_connected(diagram: Diagram) -> None:
    """Fail when a device has no wire, so a floating part cannot be drawn."""
    used: set[str] = set()
    for connection in diagram.connections:
        if connection.device_name:
            used.add(connection.device_name)
        if connection.source_device:
            used.add(connection.source_device)
    floating = [device.name for device in diagram.devices if device.name not in used]
    if floating:
        raise ValueError(
            "Breadboard layout: no connections for "
            + ", ".join(floating)
            + ". Wire it or remove it."
        )


class BreadboardRenderer:
    """Render a diagram as a pictorial breadboard."""

    def render(self, diagram: Diagram, output_path: str | Path) -> None:
        check_connected(diagram)
        self.diagram = diagram
        self.devices = {device.name: device for device in diagram.devices}
        self.modules = [device for device in diagram.devices if _role(device) == "module"]
        self.module_row: dict[str, int] = {}
        for index, module in enumerate(self.modules):
            row = (module.placement or {}).get("row")
            self.module_row[module.name] = (
                row if isinstance(row, int) else FIRST_MODULE_ROW + index * MODULE_ROWS
            )
        last = max(self.module_row.values(), default=FIRST_MODULE_ROW)
        rows = last + MODULE_ROWS + 2
        header_right = (
            PI_ORIGIN[0]
            + max(pin.position.x for pin in diagram.board.pins if pin.position) * PI_SCALE
        )
        self.header_right = header_right
        self.header_left = (
            PI_ORIGIN[0]
            + min(pin.position.x for pin in diagram.board.pins if pin.position) * PI_SCALE
        )
        self.geo = Geometry(left=header_right + 308, top=70, rows=rows)
        self.x_fan = header_right + 60
        self.x_ribbon_end = self.geo.x["GND"] - 48
        self.x_hop = self.geo.x["GND"] - 31
        self.motor_x = self.geo.x["+24V"] + 58

        width = self.motor_x + 150
        height = self.geo.bottom + 160
        canvas = draw.Drawing(width, height, origin=(0, 0))
        canvas.append(draw.Rectangle(0, 0, width, height, fill="#FFFFFF"))
        self.canvas = canvas

        self._draw_title()
        self._draw_pi()
        self._draw_breadboard()
        for module in self.modules:
            self._draw_module(module)
        self._draw_wires()
        self._draw_header_labels()
        self._draw_key(height)
        canvas.save_svg(str(Path(output_path)))

    # Parts -----------------------------------------------------------------

    def _draw_title(self) -> None:
        if self.diagram.show_title:
            self.canvas.append(
                draw.Text(
                    self.diagram.title,
                    22,
                    24,
                    44,
                    font_family=FONT,
                    font_weight="bold",
                    fill="#1A1A1A",
                )
            )

    def _draw_pi(self) -> None:
        from .render_svg import SVGRenderer

        asset = self.diagram.board.svg_asset_path
        if not asset or not Path(asset).exists():
            raise ValueError(
                f"Board {self.diagram.board.name} has no SVG asset for a pictorial layout"
            )
        root = ET.parse(asset).getroot()
        group = draw.Group(transform=f"translate({PI_ORIGIN[0]}, {PI_ORIGIN[1]}) scale({PI_SCALE})")
        SVGRenderer()._inline_svg_elements(group, root, self.canvas, show_board_name=False)
        self.canvas.append(group)

    def _header_xy(self, pin_number: int) -> tuple[float, float]:
        pin = next((item for item in self.diagram.board.pins if item.number == pin_number), None)
        if pin is None or pin.position is None:
            raise ValueError(f"Board pin {pin_number} has no position")
        return PI_ORIGIN[0] + pin.position.x * PI_SCALE, PI_ORIGIN[1] + pin.position.y * PI_SCALE

    def _draw_breadboard(self) -> None:
        geo, c = self.geo, self.canvas
        c.append(
            draw.Rectangle(
                geo.left,
                geo.top,
                geo.right - geo.left,
                geo.bottom - geo.top,
                rx=10,
                fill="#F6F3EC",
                stroke="#D9D3C5",
                stroke_width=1.5,
            )
        )
        trench = (geo.x["e"] + geo.x["f"]) / 2
        c.append(
            draw.Rectangle(
                trench - 8, geo.top + 10, 16, geo.bottom - geo.top - 20, rx=4, fill="#E7E1D6"
            )
        )
        for rail in RAIL_PINS:
            x = geo.x[rail]
            c.append(
                draw.Line(
                    x,
                    geo.y(0) - 10,
                    x,
                    geo.y(geo.rows - 1) + 10,
                    stroke=RAIL_COLORS[rail],
                    stroke_width=3,
                    stroke_opacity=0.45,
                )
            )
        for row in range(geo.rows):
            for name in RAIL_PINS + tuple("abcdefghij"):
                c.append(
                    draw.Circle(
                        geo.x[name],
                        geo.y(row),
                        3.0,
                        fill="#C8C2B6",
                        stroke="#8E887C",
                        stroke_width=0.6,
                    )
                )
        for rail in ("MGND", "+24V"):
            x, y = geo.x[rail] + 4, geo.y(0) - 14
            c.append(
                draw.Text(
                    RAIL_TITLES[rail],
                    11,
                    x,
                    y,
                    font_family=FONT,
                    font_weight="bold",
                    fill=RAIL_COLORS[rail],
                    transform=f"rotate(-90 {x} {y})",
                )
            )
        for rail in ("GND", "+3V3"):
            x, y = geo.x[rail] + 4, geo.y(geo.rows - 1) + 32
            c.append(
                draw.Text(
                    RAIL_TITLES[rail],
                    11,
                    x,
                    y,
                    text_anchor="end",
                    font_family=FONT,
                    font_weight="bold",
                    fill=RAIL_COLORS[rail],
                    transform=f"rotate(-90 {x} {y})",
                )
            )

    def _draw_module(self, module: Device) -> None:
        geo, c, p = self.geo, self.canvas, self.geo.pitch
        top = self.module_row[module.name]
        x0, x1 = geo.x["b"] - 0.5 * p, geo.x["f"] + 0.5 * p
        y0, y1 = geo.y(top) - 0.45 * p, geo.y(top + 7) + 0.45 * p
        c.append(
            draw.Rectangle(
                x0, y0, x1 - x0, y1 - y0, rx=4, fill="#2B241C", stroke="#1A140F", stroke_width=1
            )
        )
        shown = STEPSTICK_LABELS
        for index in range(8):
            y = geo.y(top + index)
            c.append(
                draw.Circle(geo.x["b"], y, 3.6, fill="#E6C36A", stroke="#8A6A22", stroke_width=0.6)
            )
            c.append(
                draw.Circle(geo.x["f"], y, 3.6, fill="#E6C36A", stroke="#8A6A22", stroke_width=0.6)
            )
            left = STEPSTICK_LEFT[index]
            c.append(
                draw.Text(
                    shown.get(left, left),
                    10.5,
                    geo.x["b"] + 8,
                    y + 4,
                    font_family=FONT,
                    font_weight="bold",
                    fill="#F4EFE4",
                )
            )
            right = STEPSTICK_RIGHT[index]
            c.append(
                draw.Text(
                    shown.get(right, right),
                    10.5,
                    geo.x["f"] - 8,
                    y + 4,
                    text_anchor="end",
                    font_family=FONT,
                    font_weight="bold",
                    fill="#F4EFE4",
                )
            )
        # The name sits between the short labels of rows 1 and 2 (MS1/GND,
        # MS2/2B); rows 3 and 4 carry the long PDN_UART text.
        cx = (x0 + x1) / 2
        c.append(
            draw.Text(
                module.name,
                13,
                cx,
                geo.y(top + 1) + 5,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        c.append(
            draw.Text(
                "TMC2209",
                9,
                cx,
                geo.y(top + 2) + 4,
                text_anchor="middle",
                font_family=FONT,
                fill="#CFC6B6",
            )
        )

    def _draw_motor(self, motor: Device, leads: list[tuple[str, float]]) -> None:
        c = self.canvas
        top = min(y for _pin, y in leads) - 26
        bottom = max(y for _pin, y in leads) + 26
        box_x = self.motor_x + 32
        size = bottom - top
        c.append(
            draw.Rectangle(
                box_x, top, size, size, rx=5, fill="#4A4E54", stroke="#2A2D31", stroke_width=1.5
            )
        )
        c.append(
            draw.Circle(
                box_x + size / 2,
                top + size / 2 - 6,
                20,
                fill="#C5A46E",
                stroke="#6E5A38",
                stroke_width=2,
            )
        )
        c.append(draw.Circle(box_x + size / 2, top + size / 2 - 6, 6, fill="#2A2D31"))
        c.append(
            draw.Text(
                motor.name,
                13,
                box_x + size / 2,
                bottom - 10,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        for pin, y in leads:
            c.append(
                draw.Circle(self.motor_x, y, 4, fill="#F4F1EA", stroke="#333333", stroke_width=1)
            )
            c.append(
                draw.Text(pin, 10.5, self.motor_x + 8, y + 4, font_family=FONT, fill="#1A1A1A")
            )

    def _draw_supply(self, supply: Device) -> tuple[float, float, float]:
        geo, c = self.geo, self.canvas
        top = geo.y(geo.rows - 1) + 62
        left = geo.x["MGND"] - 104
        c.append(
            draw.Rectangle(
                left, top, 230, 54, rx=4, fill="#F4F6F8", stroke="#5C6770", stroke_width=1.5
            )
        )
        c.append(
            draw.Text(
                supply.name,
                13,
                left + 115,
                top + 22,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#1A1A1A",
            )
        )
        c.append(
            draw.Text(
                "-V  GND",
                11,
                geo.x["MGND"] - 44,
                top + 42,
                text_anchor="middle",
                font_family=FONT,
                fill="#1A1A1A",
            )
        )
        c.append(
            draw.Text(
                "+V  24 V",
                11,
                geo.x["+24V"] + 44,
                top + 42,
                text_anchor="middle",
                font_family=FONT,
                fill="#D31212",
            )
        )
        return top, geo.x["MGND"] - 44, geo.x["+24V"] + 44

    def _draw_capacitor(self, capacitor: Device, minus_rail: str, plus_rail: str, row: int) -> None:
        geo, c = self.geo, self.canvas
        xm, xp, y = geo.x[minus_rail], geo.x[plus_rail], geo.y(row)
        cx = (xm + xp) / 2
        body_top, body_bottom = y - 58, y - 14
        for leg_x, hole_x in ((cx - 6, xm), (cx + 6, xp)):
            c.append(draw.Line(leg_x, body_bottom, hole_x, y, stroke="#8E8E8E", stroke_width=2))
            c.append(draw.Circle(hole_x, y, 3.2, fill="#8E8E8E"))
        c.append(
            draw.Rectangle(
                cx - 15,
                body_top,
                30,
                body_bottom - body_top,
                rx=7,
                fill="#3E6A9A",
                stroke="#1F3A57",
                stroke_width=1,
            )
        )
        stripe_left = cx - 15 if xm < xp else cx + 3
        c.append(
            draw.Rectangle(
                stripe_left, body_top + 1, 12, body_bottom - body_top - 2, fill="#E8EEF4"
            )
        )
        minus_x = stripe_left + 6
        plus_x = cx + 9 if xm < xp else cx - 9
        c.append(
            draw.Text(
                "-",
                13,
                minus_x,
                body_top + 26,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#1F3A57",
            )
        )
        c.append(
            draw.Text(
                "+",
                12,
                plus_x,
                body_top + 26,
                text_anchor="middle",
                font_family=FONT,
                font_weight="bold",
                fill="#FFFFFF",
            )
        )
        label_x = max(xm, xp) + 16
        c.append(
            draw.Text(
                capacitor.name,
                11,
                label_x,
                body_top + 18,
                font_family=FONT,
                font_weight="bold",
                fill="#1A1A1A",
            )
        )
        c.append(
            draw.Text("stripe (-) on GND", 10, label_x, body_top + 32, font_family=FONT, fill=GRAY)
        )
        c.append(draw.Text("+ on +24 V", 10, label_x, body_top + 45, font_family=FONT, fill=GRAY))

    # Wires -----------------------------------------------------------------

    def _wire(self, path: str, color: str) -> None:
        self.canvas.append(
            draw.Path(
                path,
                stroke="#FFFFFF",
                stroke_width=6.5,
                fill="none",
                stroke_linecap="round",
                stroke_linejoin="round",
            )
        )
        self.canvas.append(
            draw.Path(
                path,
                stroke=color,
                stroke_width=2.8,
                fill="none",
                stroke_linecap="round",
                stroke_linejoin="round",
            )
        )

    def _dot(self, x: float, y: float, color: str) -> None:
        self.canvas.append(draw.Circle(x, y, 3.6, fill=color, stroke="#FFFFFF", stroke_width=1))

    def _module_pin_xy(self, module: Device, pin: str) -> tuple[float, float, int]:
        column, offset = stepstick_seat(module, pin)
        row = self.module_row[module.name] + offset
        return self.geo.x[column], self.geo.y(row), row

    def _classify(
        self, connection: Connection
    ) -> tuple[str, Device | None, str, Device | None, str]:
        if connection.board_pin:
            target = self.devices[connection.device_name or ""]
            return (
                "board",
                None,
                str(connection.board_pin),
                target,
                connection.device_pin_name or "",
            )
        source = self.devices[connection.source_device or ""]
        target = self.devices[connection.device_name or ""]
        return (
            "device",
            source,
            connection.source_pin or "",
            target,
            connection.device_pin_name or "",
        )

    def _draw_wires(self) -> None:
        geo, p = self.geo, self.geo.pitch
        bundles: dict[str, list[tuple[Connection, float, float, float, str]]] = {}
        feeds: list[tuple[Connection, float, float, str]] = []
        motor_leads: dict[str, list[tuple[str, float, float, str]]] = {}
        supply_feeds: list[tuple[Device, str, str, str]] = []
        capacitor_legs: dict[str, dict[str, str]] = {}
        ties: list[tuple[str, str, str]] = []
        stubs: list[tuple[Device, str, str, str]] = []

        for connection in self.diagram.connections:
            kind, source, source_pin, target, target_pin = self._classify(connection)
            color = connection.color or "#1A1A1A"
            if kind == "board":
                px, py = self._header_xy(int(source_pin))
                if _role(target) == "module":
                    _x, _y, row = self._module_pin_xy(target, target_pin)
                    land = (
                        geo.y(self.module_row[target.name] + 7) + 2.5 * p
                        if target_pin == "IOGND"
                        else geo.y(row)
                    )
                    bundles.setdefault(target.name, []).append((connection, px, py, land, color))
                elif _role(target) == "rail":
                    feeds.append((connection, px, py, color))
                else:
                    raise ValueError(
                        f"Breadboard layout cannot wire board pin {source_pin} to {target.name}"
                    )
                continue
            pair = {_role(source): (source, source_pin), _role(target): (target, target_pin)}
            if "module" in pair and "rail" in pair:
                stubs.append((pair["module"][0], pair["module"][1], pair["rail"][1], color))
            elif "module" in pair and "motor" in pair:
                module, module_pin = pair["module"]
                motor, motor_pin = pair["motor"]
                _x, y, _row = self._module_pin_xy(module, module_pin)
                motor_leads.setdefault(motor.name, []).append((motor_pin, y, geo.x["j"], color))
            elif "supply" in pair and "rail" in pair:
                supply_feeds.append((pair["supply"][0], pair["supply"][1], pair["rail"][1], color))
            elif "capacitor" in pair and "rail" in pair:
                capacitor_legs.setdefault(pair["capacitor"][0].name, {})[pair["capacitor"][1]] = (
                    pair["rail"][1]
                )
            elif _role(source) == "rail" and _role(target) == "rail":
                ties.append((source_pin, target_pin, color))
            else:
                raise ValueError(
                    f"Breadboard layout cannot wire {source.name}.{source_pin} to {target.name}.{target_pin}"
                )

        self._draw_feeds(feeds)
        for module in self.modules:
            if module.name in bundles:
                self._draw_bundle(module, bundles[module.name])
        for module, module_pin, rail, color in stubs:
            self._draw_stub(module, module_pin, rail, color)
        for name, leads in motor_leads.items():
            self._draw_motor(self.devices[name], [(pin, y) for pin, y, _x, _c in leads])
            for _pin, y, x, color in leads:
                self._wire(_rounded([(x, y), (self.motor_x, y)]), color)
                self._dot(x, y, color)
        supply_top = None
        if supply_feeds:
            supply_top, minus_x, plus_x = self._draw_supply(supply_feeds[0][0])
            bottom = geo.y(geo.rows - 1)
            for _supply, pin, rail, color in supply_feeds:
                start_x = minus_x if pin.startswith("-") else plus_x
                rail_x = geo.x[rail]
                self._wire(
                    _rounded(
                        [
                            (start_x, supply_top),
                            (start_x, bottom + 42),
                            (rail_x, bottom + 42),
                            (rail_x, bottom),
                        ]
                    ),
                    color,
                )
                self._dot(rail_x, bottom, color)
        uses_motor_ground = any(rail == "MGND" for *_rest, rail, _color in stubs) or any(
            rail == "MGND" for *_rest, rail, _color in supply_feeds
        )
        if ties or uses_motor_ground:
            self._draw_tie("GND", "MGND", "#1A1A1A")
        for name, legs in capacitor_legs.items():
            minus_rail = legs.get("-")
            plus_rail = legs.get("+")
            if not minus_rail or not plus_rail:
                raise ValueError(f"{name} needs both legs on rails")
            if minus_rail == plus_rail:
                raise ValueError(f"{name} has both legs on {minus_rail}")
            self._draw_capacitor(self.devices[name], minus_rail, plus_rail, geo.rows - 3)

    def _draw_feeds(self, feeds: list[tuple[Connection, float, float, str]]) -> None:
        """Header pins that land on the left rails, from above, nested so they do not cross."""
        geo = self.geo
        feeds = sorted(feeds, key=lambda item: item[2])
        count = len(feeds)
        for index, (connection, px, py, color) in enumerate(feeds):
            rail = connection.device_pin_name or ""
            if rail not in ("GND", "+3V3"):
                raise ValueError(f"Header pins land on the left rails (GND, +3V3), not {rail}")
            rail_x = geo.x[rail]
            apex = geo.y(0) - 20 - 18 * (count - 1 - index)
            lead, sx, sy = self._fan_start(px, py, apex)
            path = (
                f"{lead} C {sx + 30:.1f} {sy:.1f}, {rail_x - 90:.1f} {apex:.1f}, {rail_x - 12:.1f} {apex:.1f} "
                f"Q {rail_x:.1f} {apex:.1f} {rail_x:.1f} {apex + 12:.1f} L {rail_x:.1f} {geo.y(0):.1f}"
            )
            self._wire(path, color)
            self._dot(rail_x, geo.y(0), color)

    def _fan_start(
        self, px: float, py: float, toward_y: float, over: bool = False
    ) -> tuple[str, float, float]:
        """Leave a header pin. Returns the path so far and the point the curve starts from.

        A left-column pin steps diagonally between the pads and clears the right
        column before curving. ``over`` sends it above the right-column pin of its
        row, used when that pin belongs to the same bundle and takes the next lane.
        """
        if px < self.header_right - 4:
            step = 14.0
            dy = -step if over or toward_y < py else step if toward_y > py else 0.0
            clear_x = self.header_right + 12
            path = (
                f"M {px:.1f} {py:.1f} L {px + step:.1f} {py + dy:.1f} L {clear_x:.1f} {py + dy:.1f}"
            )
            return path, clear_x, py + dy
        return f"M {px:.1f} {py:.1f}", px, py

    def _draw_bundle(
        self, module: Device, wires: list[tuple[Connection, float, float, float, str]]
    ) -> None:
        """One ribbon from the header to the module, in header order.

        The ribbon stays flat (no wire crosses another) as long as the pins
        land in the same top-to-bottom order they leave the header. A wire
        whose pin is above an earlier wire's pin (EN, the top pin, after
        STEP and DIR) is a hopper: it lands below everything that came
        before it and climbs the left edge of the board to its row, so the
        only crossing is that one visible hop.
        """
        geo, p = self.geo, self.geo.pitch
        wires = sorted(wires, key=lambda item: (round(item[2]), item[1]))
        center = sum(item[2] for item in wires) / len(wires)
        k = 0.45 * (self.x_ribbon_end - self.x_fan)
        routed: list[tuple[Connection, float, float, float, str, float | None]] = []
        floor = None
        hops = 0
        for connection, px, py, land, color in wires:
            hop_x = None
            if floor is not None and land < floor - 1:
                hops += 1
                hop_x = self.x_hop - (hops - 1) * RIBBON_SPACING
                land = floor + 0.9 * p
            floor = land if floor is None else max(floor, land)
            routed.append((connection, px, py, land, color, hop_x))
        for index, (connection, px, py, land, color, hop_x) in enumerate(routed):
            lane = center + (index - (len(routed) - 1) / 2) * RIBBON_SPACING
            shares_row = any(abs(other[2] - py) < 1 and other[1] > px for other in wires)
            lead, sx, sy = self._fan_start(px, py, lane, over=shares_row)
            head = (
                f"{lead} C {sx + 18:.1f} {sy:.1f}, {self.x_fan - 30:.1f} {lane:.1f}, {self.x_fan:.1f} {lane:.1f} "
                f"C {self.x_fan + k:.1f} {lane:.1f}, {self.x_ribbon_end - k:.1f} {land:.1f}, {self.x_ribbon_end:.1f} {land:.1f}"
            )
            pin = connection.device_pin_name or ""
            if pin == "IOGND":
                # Bottom-right pin: run under the module and up into its row.
                end_x, end_y, _row = self._module_pin_xy(module, pin)
                end_x = geo.x["i"]
                tail = _rounded([(self.x_ribbon_end, land), (end_x, land), (end_x, end_y)])
            else:
                end_x, end_y, _row = self._module_pin_xy(module, pin)
                end_x = geo.x["a"]
                if hop_x is None:
                    tail = _rounded([(self.x_ribbon_end, land), (end_x, end_y)])
                else:
                    tail = _rounded(
                        [(self.x_ribbon_end, land), (hop_x, land), (hop_x, end_y), (end_x, end_y)]
                    )
            self._wire(head + " " + tail.replace("M", "L", 1), color)
            self._dot(end_x, end_y, color)

    def _draw_stub(self, module: Device, pin: str, rail: str, color: str) -> None:
        geo, p = self.geo, self.geo.pitch
        top = self.module_row[module.name]
        _x, y, _row = self._module_pin_xy(module, pin)
        if pin in ("MS1", "MS2"):
            if rail != "+3V3":
                raise ValueError(f"{module.name}.{pin} should tie to the 3.3 V rail")
            points = [(geo.x["+3V3"], y), (geo.x["a"], y)]
            end = points[-1]
        elif pin == "VIO":
            if rail != "+3V3":
                raise ValueError(f"{module.name}.VIO should tie to the 3.3 V rail")
            # VIO is the second pin from the bottom on the right. The lane runs
            # under the module from the 3.3 V rail and climbs between holes g
            # and h, clear of the GND stub leaving column j on the bottom row.
            lane_y = geo.y(top + 7) + 1.5 * p
            lane_x = geo.x["g"] + 0.5 * p
            points = [(geo.x["+3V3"], lane_y), (lane_x, lane_y), (lane_x, y), (geo.x["g"], y)]
            end = points[-1]
        elif pin in ("VM", "VMGND", "IOGND"):
            if pin != "VM" and rail != "MGND":
                raise ValueError(
                    f"{module.name}.{pin} should tie to the right-hand ground rail (MGND)"
                )
            if pin == "VM" and rail != "+24V":
                raise ValueError(f"{module.name}.VM should tie to the +24V rail")
            points = [(geo.x["j"], y), (geo.x[rail], y)]
            end = points[0]
        else:
            raise ValueError(f"Breadboard layout has no rail stub for {module.name}.{pin}")
        self._wire(_rounded(points), color)
        self._dot(points[0][0], points[0][1], color)
        self._dot(end[0], end[1], color)
        self._dot(points[-1][0], points[-1][1], color)

    def _draw_tie(self, source_pin: str, target_pin: str, color: str) -> None:
        geo, p = self.geo, self.geo.pitch
        pins = {source_pin, target_pin}
        if pins != {"GND", "MGND"}:
            raise ValueError(f"Rail tie must join GND and MGND, not {sorted(pins)}")
        bottom = geo.y(geo.rows - 1)
        riser = geo.x["MGND"] - 0.55 * p
        points = [
            (geo.x["GND"], bottom),
            (geo.x["GND"], bottom + 22),
            (riser, bottom + 22),
            (riser, geo.y(geo.rows - 2)),
            (geo.x["MGND"], geo.y(geo.rows - 2)),
        ]
        self._wire(_rounded(points), color)
        self._dot(*points[0], color)
        self._dot(*points[-1], color)

    # Labels ----------------------------------------------------------------

    def _pin_text(self, connection: Connection) -> str:
        target = self.devices[connection.device_name or ""]
        pin = connection.device_pin_name or ""
        if _role(target) == "rail":
            return {"GND": "GND bond", "+3V3": "3V3"}.get(pin, pin)
        short = target.name.split()[-1]
        return f"{ {'IOGND': 'GND'}.get(pin, pin) } {short}".strip()

    def _draw_header_labels(self) -> None:
        labels: dict[int, str] = {}
        colors: dict[int, str] = {}
        for connection in self.diagram.connections:
            if connection.board_pin:
                labels[connection.board_pin] = (
                    f"{connection.board_pin} {self._pin_text(connection)}"
                )
                colors[connection.board_pin] = connection.color or "#1A1A1A"
        for pin in (2, 4):
            if pin not in labels:
                labels[pin] = f"{pin} 5V open"
                colors[pin] = GRAY
        rows: dict[int, list[int]] = {}
        for pin in sorted(labels):
            rows.setdefault((pin - 1) // 2, []).append(pin)
        edge = self.header_left - 14
        for pins in rows.values():
            x = edge
            for pin in sorted(pins, reverse=True):
                _px, py = self._header_xy(pin)
                self.canvas.append(
                    draw.Text(
                        labels[pin],
                        11.5,
                        x,
                        py + 4,
                        text_anchor="end",
                        font_family=FONT,
                        font_weight="bold",
                        fill=colors[pin],
                        stroke="#FFFFFF",
                        stroke_width=3.5,
                        paint_order="stroke",
                    )
                )
                x -= len(labels[pin]) * LABEL_CHAR_WIDTH + 14

    def _draw_key(self, height: float) -> None:
        items = (
            ("#E2B000", "STEP"),
            ("#1F9D55", "DIR"),
            ("#7C3AED", "EN"),
            ("#1A1A1A", "GND"),
            ("#F08C00", "3.3 V"),
            ("#D31212", "+24 V"),
        )
        x, y = 24.0, height - 30
        for color, name in items:
            self.canvas.append(
                draw.Line(x, y, x + 22, y, stroke=color, stroke_width=4, stroke_linecap="round")
            )
            self.canvas.append(draw.Text(name, 12, x + 28, y + 4, font_family=FONT, fill="#1A1A1A"))
            x += 40 + len(name) * 8


def module_row_offset(device: Device, pin_name: str) -> int:
    """Row of a stepstick pin, counted from the module's first row."""
    return stepstick_seat(device, pin_name)[1]
