"""Pictorial solderless-breadboard layout.

``layout: breadboard`` draws the real board artwork, a breadboard, and
plug-in modules seated on the holes, with jumper wires between pins.
Schematic layout is unchanged.

A 16-pin stepstick is seated the way a Pololu/BIGTREETECH module plugs in:
eight pins on row ``b`` and eight on row ``f`` (0.6 inch apart), straddling
the center trench. Wires land on row ``a`` or row ``j`` of the same column,
which is the same breadboard net as the pin.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import drawsvg as draw

from .model import Connection, Device, Diagram

# BIGTREETECH TMC2209 V1.3 silkscreen, both columns top to bottom.
STEPSTICK_LEFT = ("EN", "MS1", "MS2", "RX", "TX", "CLK", "STEP", "DIR")
STEPSTICK_RIGHT = ("VM", "VMGND", "A2", "A1", "B1", "B2", "VIO", "IOGND")
STEPSTICK_PINS = STEPSTICK_LEFT + STEPSTICK_RIGHT

PI_SCALE = 2.35
PITCH = 22
COLUMNS = 30
RAIL_GAP = 26
TRENCH = 28

YELLOW = "#E2B000"
GREEN = "#1F9D55"
VIOLET = "#7C3AED"
BLACK = "#1A1A1A"
ORANGE = "#F08C00"
RED = "#D31212"


class BreadboardGeometry:
    """Hole coordinates for one 30-column breadboard."""

    def __init__(self, origin_x: float, origin_y: float) -> None:
        self.origin_x = origin_x
        self.origin_y = origin_y
        self.pitch = PITCH
        self.columns = COLUMNS

    def col_x(self, column: int) -> float:
        return self.origin_x + (column - 0.5) * self.pitch

    def row_y(self, row: str) -> float:
        pitch = self.pitch
        if row in ("+24", "GND"):
            return self.origin_y + (0 if row == "+24" else 1) * pitch
        body_top = self.origin_y + 2 * pitch + RAIL_GAP
        upper = {"a": 0, "b": 1, "c": 2, "d": 3, "e": 4}
        if row in upper:
            return body_top + upper[row] * pitch
        lower_top = body_top + 5 * pitch + TRENCH
        lower = {"f": 0, "g": 1, "h": 2, "i": 3, "j": 4}
        if row in lower:
            return lower_top + lower[row] * pitch
        if row == "+3V3":
            return lower_top + 5 * pitch + RAIL_GAP
        raise KeyError(row)

    @property
    def width(self) -> float:
        return self.columns * self.pitch

    @property
    def height(self) -> float:
        return self.row_y("+3V3") + self.pitch - self.origin_y

    @property
    def lead_x(self) -> float:
        """A hole just left of column 1, for the supply drop onto the rails."""
        return self.origin_x - self.pitch


def stepstick_column(device: Device, pin_name: str) -> tuple[int, str, str]:
    """Return ``(column, pin_row, wire_row)`` for a stepstick pin.

    ``pin_row`` is where the header pin sits. ``wire_row`` is the hole a
    jumper uses, on the same five-hole net, outside the module body.
    """
    seat = device.placement or {}
    start = seat.get("column")
    if not isinstance(start, int):
        raise ValueError(f"{device.name} needs breadboard.column for layout: breadboard")
    if pin_name in STEPSTICK_LEFT:
        index = STEPSTICK_LEFT.index(pin_name)
        return start + index, "b", "a"
    if pin_name in STEPSTICK_RIGHT:
        index = STEPSTICK_RIGHT.index(pin_name)
        return start + index, "f", "j"
    raise ValueError(f"{device.name} has no stepstick pin {pin_name}")


class BreadboardRenderer:
    """Render a diagram as a pictorial breadboard."""

    def render(self, diagram: Diagram, output_path: str | Path) -> None:
        geo, pi_origin = self._place(diagram)
        width = geo.origin_x + geo.width + 260
        height = max(
            pi_origin[1] + diagram.board.height * PI_SCALE,
            geo.origin_y + geo.height,
            geo.origin_y + 3 * 112,
        ) + 78
        canvas = draw.Drawing(width, height, origin=(0, 0))
        canvas.append(draw.Rectangle(0, 0, width, height, fill="#FFFFFF"))

        self._draw_title(canvas, diagram, width)
        self._draw_pi(canvas, diagram, pi_origin)
        self._draw_breadboard(canvas, geo)
        self._draw_modules(canvas, diagram, geo)
        self._draw_supply(canvas, diagram, geo)
        self._draw_motors(canvas, diagram, geo)
        self._draw_open_pins(canvas, diagram, pi_origin)
        self._draw_wires(canvas, diagram, geo, pi_origin)
        self._draw_key(canvas, width, height)

        output_path = Path(output_path)
        canvas.save_svg(str(output_path))

    def _place(self, diagram: Diagram) -> tuple[BreadboardGeometry, tuple[float, float]]:
        pi_origin = (24.0, 78.0)
        board_right = pi_origin[0] + diagram.board.width * PI_SCALE
        geo = BreadboardGeometry(board_right + 120.0, 168.0)
        return geo, pi_origin

    def _draw_title(self, canvas: draw.Drawing, diagram: Diagram, width: float) -> None:
        if not diagram.show_title:
            return
        canvas.append(
            draw.Text(
                diagram.title,
                22,
                width / 2,
                36,
                text_anchor="middle",
                font_family="Arial, sans-serif",
                font_weight="bold",
                fill="#1A1A1A",
            )
        )

    def _draw_pi(self, canvas: draw.Drawing, diagram: Diagram, origin: tuple[float, float]) -> None:
        from .render_svg import SVGRenderer

        asset = diagram.board.svg_asset_path
        if not asset or not Path(asset).exists():
            raise ValueError(f"Board {diagram.board.name} has no SVG asset for a pictorial layout")
        root = ET.parse(asset).getroot()
        group = draw.Group(transform=f"translate({origin[0]}, {origin[1]}) scale({PI_SCALE})")
        SVGRenderer()._inline_svg_elements(group, root, canvas, show_board_name=False)
        canvas.append(group)

    def _header_xy(self, diagram: Diagram, origin: tuple[float, float], pin_number: int) -> tuple[float, float]:
        pin = next((item for item in diagram.board.pins if item.number == pin_number), None)
        if pin is None or pin.position is None:
            raise ValueError(f"Board pin {pin_number} has no position")
        return (
            origin[0] + pin.position.x * PI_SCALE,
            origin[1] + pin.position.y * PI_SCALE,
        )

    def _draw_breadboard(self, canvas: draw.Drawing, geo: BreadboardGeometry) -> None:
        left = geo.origin_x - geo.pitch
        top = geo.origin_y - 8
        width = geo.width + geo.pitch * 1.6
        height = geo.height + 8
        canvas.append(draw.Rectangle(left, top, width, height, rx=10, fill="#F6F3EC", stroke="#D9D3C5", stroke_width=1.5))
        # Power-rail stripes.
        for row, color in (("+24", RED), ("GND", "#2C4A6E"), ("+3V3", ORANGE)):
            y = geo.row_y(row)
            canvas.append(draw.Line(left + 8, y, left + width - 8, y, stroke=color, stroke_width=3, stroke_opacity=0.55))
        for column in range(0, geo.columns + 1):
            x = geo.lead_x if column == 0 else geo.col_x(column)
            if column == 0 or 1 <= column <= geo.columns:
                for row in ("+24", "GND", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "+3V3"):
                    if column == 0 and row not in ("+24", "GND"):
                        continue
                    canvas.append(draw.Circle(x, geo.row_y(row), 3.1, fill="#C8C2B6", stroke="#8E887C", stroke_width=0.6))
        # Center trench.
        trench_y = (geo.row_y("e") + geo.row_y("f")) / 2
        canvas.append(
            draw.Rectangle(
                geo.origin_x + 4,
                trench_y - 7,
                geo.width - 8,
                14,
                rx=4,
                fill="#E7E1D6",
            )
        )
        canvas.append(
            draw.Text(
                "+24 V",
                11,
                left + width + 4,
                geo.row_y("+24") + 4,
                font_family="Arial, sans-serif",
                fill=RED,
            )
        )
        canvas.append(
            draw.Text(
                "GND",
                11,
                left + width + 4,
                geo.row_y("GND") + 4,
                font_family="Arial, sans-serif",
                fill="#2C4A6E",
            )
        )
        canvas.append(
            draw.Text(
                "3.3 V",
                11,
                left + width + 4,
                geo.row_y("+3V3") + 4,
                font_family="Arial, sans-serif",
                fill=ORANGE,
            )
        )

    def _modules(self, diagram: Diagram) -> list[Device]:
        found = []
        for device in diagram.devices:
            role = (device.placement or {}).get("role", "module")
            if device.type_id == "tmc2209" or role == "module" and device.type_id == "tmc2209":
                found.append(device)
        return found

    def _by_role(self, diagram: Diagram, role: str) -> list[Device]:
        return [device for device in diagram.devices if (device.placement or {}).get("role") == role]

    def _draw_modules(self, canvas: draw.Drawing, diagram: Diagram, geo: BreadboardGeometry) -> None:
        for device in self._modules(diagram):
            start = (device.placement or {}).get("column")
            if not isinstance(start, int):
                raise ValueError(f"{device.name} needs breadboard.column")
            x = geo.col_x(start) - geo.pitch * 0.42
            y = geo.row_y("b") - geo.pitch * 0.42
            width = geo.pitch * 7 + geo.pitch * 0.84
            height = geo.row_y("f") - geo.row_y("b") + geo.pitch * 0.84
            canvas.append(draw.Rectangle(x, y, width, height, rx=3, fill="#2B241C", stroke="#1A140F", stroke_width=1))
            canvas.append(
                draw.Text(
                    device.name,
                    12,
                    x + width / 2,
                    (geo.row_y("e") + geo.row_y("f")) / 2 + 4,
                    text_anchor="middle",
                    font_family="Arial, sans-serif",
                    font_weight="bold",
                    fill="#F4EFE4",
                )
            )
            for pin_name in STEPSTICK_PINS:
                column, pin_row, _wire_row = stepstick_column(device, pin_name)
                canvas.append(draw.Circle(geo.col_x(column), geo.row_y(pin_row), 3.4, fill="#E6C36A", stroke="#8A6A22", stroke_width=0.6))
            self._draw_pin_legend(canvas, geo, device, start)

    def _draw_pin_legend(self, canvas: draw.Drawing, geo: BreadboardGeometry, device: Device, start: int) -> None:
        for index, pin_name in enumerate(STEPSTICK_LEFT):
            canvas.append(
                draw.Text(
                    pin_name,
                    8,
                    geo.col_x(start + index),
                    geo.row_y("b") + 16,
                    text_anchor="middle",
                    font_family="Arial, sans-serif",
                    fill="#F4EFE4",
                )
            )
        right_labels = {"VMGND": "GND", "IOGND": "GND"}
        for index, pin_name in enumerate(STEPSTICK_RIGHT):
            canvas.append(
                draw.Text(
                    right_labels.get(pin_name, pin_name),
                    8,
                    geo.col_x(start + index),
                    geo.row_y("f") - 8,
                    text_anchor="middle",
                    font_family="Arial, sans-serif",
                    fill="#F4EFE4",
                )
            )

    def _draw_supply(self, canvas: draw.Drawing, diagram: Diagram, geo: BreadboardGeometry) -> None:
        supplies = self._by_role(diagram, "supply")
        capacitors = self._by_role(diagram, "capacitor")
        if supplies:
            supply = supplies[0]
            x = geo.lead_x - 8
            y = geo.origin_y - 96
            canvas.append(draw.Rectangle(x, y, 150, 58, rx=4, fill="#F4F6F8", stroke="#5C6770", stroke_width=1.5))
            canvas.append(draw.Text(supply.name, 13, x + 75, y + 20, text_anchor="middle", font_family="Arial, sans-serif", font_weight="bold", fill="#1A1A1A"))
            canvas.append(draw.Text("+V 24 V", 11, x + 40, y + 44, text_anchor="middle", font_family="Arial, sans-serif", fill=RED))
            canvas.append(draw.Text("-V GND", 11, x + 112, y + 44, text_anchor="middle", font_family="Arial, sans-serif", fill=BLACK))
        if capacitors:
            capacitor = capacitors[0]
            cx = geo.col_x(COLUMNS)
            cy = geo.origin_y - 48
            canvas.append(draw.Rectangle(cx - 16, cy - 22, 32, 40, rx=8, fill="#5B7C99", stroke="#24384A", stroke_width=1))
            canvas.append(draw.Rectangle(cx + 4, cy - 22, 12, 40, fill="#E8EEF4"))
            canvas.append(draw.Text("+", 12, cx - 8, cy + 4, text_anchor="middle", font_family="Arial, sans-serif", fill="#FFFFFF", font_weight="bold"))
            canvas.append(draw.Text(capacitor.name, 11, cx + 28, cy + 4, font_family="Arial, sans-serif", fill="#1A1A1A"))

    def _draw_motors(self, canvas: draw.Drawing, diagram: Diagram, geo: BreadboardGeometry) -> None:
        motors = self._by_role(diagram, "motor")
        for index, motor in enumerate(motors):
            x = geo.origin_x + geo.width + 56
            y = geo.origin_y + index * 112
            canvas.append(draw.Rectangle(x, y, 78, 78, rx=4, fill="#4A4E54", stroke="#2A2D31", stroke_width=1.5))
            canvas.append(draw.Circle(x + 39, y + 34, 16, fill="#C5A46E", stroke="#6E5A38", stroke_width=2))
            canvas.append(draw.Circle(x + 39, y + 34, 5, fill="#2A2D31"))
            canvas.append(draw.Text(motor.name, 12, x + 39, y + 70, text_anchor="middle", font_family="Arial, sans-serif", font_weight="bold", fill="#F4F6F8"))
            lead_x = x + 96
            for lead_index, pin_name in enumerate(("A1", "A2", "B1", "B2")):
                ly = y + 8 + lead_index * 18
                canvas.append(draw.Circle(lead_x, ly, 4, fill="#F4F1EA", stroke="#333333", stroke_width=1))
                canvas.append(draw.Text(pin_name, 11, lead_x + 10, ly + 4, font_family="Arial, sans-serif", fill="#1A1A1A"))

    def _motor_lead_xy(self, diagram: Diagram, motor: Device, pin_name: str, geo: BreadboardGeometry) -> tuple[float, float]:
        motors = self._by_role(diagram, "motor")
        index = motors.index(motor)
        y = geo.origin_y + index * 112
        lead_index = ("A1", "A2", "B1", "B2").index(pin_name)
        return geo.origin_x + geo.width + 56 + 96, y + 8 + lead_index * 18

    def _draw_open_pins(self, canvas: draw.Drawing, diagram: Diagram, origin: tuple[float, float]) -> None:
        used = {connection.board_pin for connection in diagram.connections if connection.board_pin}
        for pin_number in (2, 4):
            if pin_number in used:
                continue
            x, y = self._header_xy(diagram, origin, pin_number)
            self._anchored_label(canvas, "5V open", x + 14, y + 4, "#5C6570", "start")

    def _draw_wires(
        self,
        canvas: draw.Drawing,
        diagram: Diagram,
        geo: BreadboardGeometry,
        origin: tuple[float, float],
    ) -> None:
        devices = {device.name: device for device in diagram.devices}
        for connection in diagram.connections:
            color = connection.color or BLACK
            start = self._endpoint(diagram, devices, geo, origin, connection, source=True)
            end = self._endpoint(diagram, devices, geo, origin, connection, source=False, other=start)
            # Re-resolve the source now that the destination column is known (rail drops).
            start = self._endpoint(diagram, devices, geo, origin, connection, source=True, other=end)
            self._route(canvas, geo, start, end, color, connection)

    def _endpoint(
        self,
        diagram: Diagram,
        devices: dict[str, Device],
        geo: BreadboardGeometry,
        origin: tuple[float, float],
        connection: Connection,
        *,
        source: bool,
        other: dict | None = None,
    ) -> dict:
        if source and connection.board_pin:
            x, y = self._header_xy(diagram, origin, connection.board_pin)
            return {"kind": "header", "x": x, "y": y, "pin": connection.board_pin}
        if source and connection.source_device:
            return self._device_point(diagram, devices[connection.source_device], connection.source_pin or "", geo, other)
        if not source:
            return self._device_point(diagram, devices[connection.device_name or ""], connection.device_pin_name or "", geo, other)
        raise ValueError(f"Connection has no source: {connection}")

    def _device_point(
        self,
        diagram: Diagram,
        device: Device,
        pin_name: str,
        geo: BreadboardGeometry,
        other: dict | None,
    ) -> dict:
        role = (device.placement or {}).get("role", "module")
        if device.type_id == "tmc2209" or role == "module" and device.type_id == "tmc2209":
            column, _pin_row, wire_row = stepstick_column(device, pin_name)
            return {
                "kind": "hole",
                "x": geo.col_x(column),
                "y": geo.row_y(wire_row),
                "column": column,
                "row": wire_row,
                "pin": pin_name,
                "device": device,
            }
        if role == "rail":
            row = {"+24V": "+24", "GND": "GND", "+3V3": "+3V3"}[pin_name]
            if other and other.get("kind") == "hole" and isinstance(other.get("column"), int):
                column = other["column"]
            elif other and other.get("kind") == "capacitor":
                column = COLUMNS
            elif other and other.get("kind") == "header":
                column = 1
            else:
                column = 0
            x = geo.lead_x if column == 0 else geo.col_x(column)
            return {"kind": "rail", "x": x, "y": geo.row_y(row), "column": column, "row": row, "pin": pin_name}
        if role == "supply":
            x = geo.lead_x - 8
            y = geo.origin_y - 96
            if pin_name == "+V":
                return {"kind": "supply", "x": x + 40, "y": y + 58, "pin": pin_name}
            return {"kind": "supply", "x": x + 112, "y": y + 58, "pin": pin_name}
        if role == "capacitor":
            cx = geo.col_x(COLUMNS)
            cy = geo.origin_y - 8
            if pin_name == "+":
                return {"kind": "capacitor", "x": cx - 6, "y": cy, "column": 1, "pin": pin_name}
            return {"kind": "capacitor", "x": cx + 8, "y": cy, "column": 1, "pin": pin_name}
        if role == "motor":
            x, y = self._motor_lead_xy(diagram, device, pin_name, geo)
            return {"kind": "motor", "x": x, "y": y, "pin": pin_name}
        raise ValueError(f"No breadboard placement for {device.name} pin {pin_name}")

    def _route(self, canvas: draw.Drawing, geo: BreadboardGeometry, start: dict, end: dict, color: str, connection: Connection) -> None:
        if start["kind"] == "header":
            self._bezier(canvas, start["x"], start["y"], end["x"], end["y"], color)
            label = self._header_label(connection)
            if label and connection.board_pin:
                # Odd pins are the left header column, even pins the right column.
                # Keep each label on its own side so a pair on one row does not collide.
                if connection.board_pin % 2 == 1:
                    self._anchored_label(canvas, label, start["x"] - 12, start["y"] + 4, color, "end")
                else:
                    self._anchored_label(canvas, label, start["x"] + 14, start["y"] + 4, color, "start")
            self._dot(canvas, end["x"], end["y"], color)
            return
        if {start["kind"], end["kind"]} <= {"hole", "rail", "supply", "capacitor"}:
            self._jumper(canvas, geo, start, end, color)
            return
        self._bezier(canvas, start["x"], start["y"], end["x"], end["y"], color)
        self._dot(canvas, start["x"], start["y"], color)
        self._dot(canvas, end["x"], end["y"], color)

    def _header_label(self, connection: Connection) -> str:
        pin = connection.board_pin
        target = connection.device_pin_name or ""
        if pin is None:
            return ""
        return f"{pin} {target}"

    def _jumper(self, canvas: draw.Drawing, geo: BreadboardGeometry, start: dict, end: dict, color: str) -> None:
        hole = end if end.get("kind") == "hole" else start if start.get("kind") == "hole" else None
        crosses = hole is not None and self._crosses_module(hole)
        same_x = abs(start["x"] - end["x"]) < 2
        if hole is None or (same_x and not crosses):
            canvas.append(draw.Line(start["x"], start["y"], end["x"], end["y"], stroke=color, stroke_width=2.6, stroke_linecap="round"))
            return
        if crosses:
            device = hole["device"]
            start_col = (device.placement or {}).get("column")
            pin = hole.get("pin")
            lane = 0
            if pin in STEPSTICK_RIGHT:
                lane = STEPSTICK_RIGHT.index(pin)
            elif pin in STEPSTICK_LEFT:
                lane = STEPSTICK_LEFT.index(pin)
            if pin in ("MS1", "MS2"):
                gutter = geo.col_x(start_col + 7) + geo.pitch * 0.55 + lane * 4
            else:
                gutter = geo.col_x(start_col) - geo.pitch * 0.55 - lane * 4
            path = f"M {start['x']} {start['y']} L {gutter} {start['y']} L {gutter} {end['y']} L {end['x']} {end['y']}"
            canvas.append(draw.Path(path, stroke=color, stroke_width=2.4, fill="none", stroke_linejoin="round", stroke_linecap="round"))
            return
        self._bezier(canvas, start["x"], start["y"], end["x"], end["y"], color)

    def _crosses_module(self, hole: dict) -> bool:
        row = hole.get("row")
        return row in ("a", "j") and hole.get("pin") in ("VM", "VMGND", "MS1", "MS2")

    def _bezier(self, canvas: draw.Drawing, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
        bend = max(36.0, abs(x2 - x1) * 0.35)
        direction = 1 if x2 >= x1 else -1
        path = f"M {x1} {y1} C {x1 + bend * direction} {y1}, {x2 - bend * direction} {y2}, {x2} {y2}"
        canvas.append(draw.Path(path, stroke=color, stroke_width=2.5, fill="none", stroke_linecap="round"))

    def _dot(self, canvas: draw.Drawing, x: float, y: float, color: str) -> None:
        canvas.append(draw.Circle(x, y, 3.3, fill=color))

    def _anchored_label(
        self, canvas: draw.Drawing, text: str, x: float, y: float, color: str, anchor: str
    ) -> None:
        canvas.append(
            draw.Text(
                text,
                11,
                x,
                y,
                text_anchor=anchor,
                font_family="Arial, sans-serif",
                font_weight="bold",
                fill=color,
                stroke="#FFFFFF",
                stroke_width=3,
                paint_order="stroke",
            )
        )

    def _draw_key(self, canvas: draw.Drawing, width: float, height: float) -> None:
        items = (
            (YELLOW, "STEP"),
            (GREEN, "DIR"),
            (VIOLET, "EN"),
            (BLACK, "GND"),
            (ORANGE, "3.3 V"),
            (RED, "+24 V"),
        )
        x = 24
        y = height - 28
        for color, name in items:
            canvas.append(draw.Line(x, y, x + 22, y, stroke=color, stroke_width=4, stroke_linecap="round"))
            canvas.append(draw.Text(name, 12, x + 28, y + 4, font_family="Arial, sans-serif", fill="#1A1A1A"))
            x += 28 + 12 + len(name) * 8


def module_column(device: Device, pin_name: str) -> int:
    """Public helper so tests can check a pin's breadboard column."""
    column, _pin_row, _wire_row = stepstick_column(device, pin_name)
    return column
