import ast
import re
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.cell import range_boundaries


class FormulaError(ValueError):
    pass


class FormulaEngine:
    def __init__(self, sheet):
        self.sheet = sheet

    def cell(self, coordinate, stack=()):
        if coordinate in stack:
            raise FormulaError("Circular formula")
        value = self.sheet[coordinate].value
        if isinstance(value, str) and value.startswith("="):
            return self.expression(value[1:], (*stack, coordinate))
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        raise FormulaError(f"Non-numeric reference: {coordinate}")

    def expression(self, value, stack):
        match = re.fullmatch(r"SUM\(([A-Z]+\d+):([A-Z]+\d+)\)", value)
        if match:
            left, top, right, bottom = range_boundaries(":".join(match.groups()))
            if (right - left + 1) * (bottom - top + 1) > 1000:
                raise FormulaError("Range too large")
            return sum(
                (
                    self.cell(cell.coordinate, stack)
                    for row in self.sheet.iter_rows(
                        min_row=top, max_row=bottom, min_col=left, max_col=right
                    )
                    for cell in row
                ),
                Decimal(0),
            )
        match = re.fullmatch(r"IF\(([A-Z]+\d+)>=(\d+),(\d+),(\d+)\)", value)
        if match:
            ref, threshold, yes, no = match.groups()
            return Decimal(yes if self.cell(ref, stack) >= Decimal(threshold) else no)
        try:
            node = ast.parse(value, mode="eval").body
        except SyntaxError as exc:
            raise FormulaError("Unsupported formula syntax") from exc
        return self.node(node, stack)

    def node(self, node, stack):
        if isinstance(node, ast.Name) and re.fullmatch(r"[A-Z]+\d+", node.id):
            return self.cell(node.id, stack)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        if isinstance(node, ast.BinOp):
            left, right = self.node(node.left, stack), self.node(node.right, stack)
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
        raise FormulaError("Unsupported formula; review required")


def convert(path):
    path = Path(path)
    if path.suffix == ".xlsx":
        workbook = load_workbook(path, data_only=False, read_only=False)
        if workbook.active.max_row > 1000 or workbook.active.max_column > 20:
            raise FormulaError("Workbook exceeds local conversion budget")
        engine = FormulaEngine(workbook.active)
        for row in (2, 3, 4):
            units, cents = engine.cell(f"B{row}"), engine.cell(f"C{row}")
            if (
                units <= 0
                or cents <= 0
                or units != units.to_integral_value()
                or cents != cents.to_integral_value()
            ):
                raise FormulaError("BOM quantities and cents must be positive integers")
        total = engine.cell("D5")
        if total != engine.cell("D6") or total != total.to_integral_value():
            raise FormulaError("BOM formula and claimed total disagree")
        lines = [
            "| Component | Units | Unit Cost Cents | Extended Cost Cents |",
            "| --- | --- | --- | --- |",
        ]
        for row in workbook.active.iter_rows(min_row=2, max_row=4):
            lines.append(
                "| "
                + " | ".join(
                    str(engine.cell(cell.coordinate)) if cell.column > 1 else str(cell.value)
                    for cell in row
                )
                + " |"
            )
        lines.append(f"Total unit cost: {total} cents.")
        return {
            "lane": "server",
            "text": "\n".join(lines),
            "unit_cost_cents": int(total),
            "formula_engine": "restricted-local-v1",
        }
    if path.suffix not in {".md", ".txt", ".json", ".csv"}:
        raise ValueError("Unsupported document format")
    return {"lane": "local", "text": path.read_text(encoding="utf-8")}
