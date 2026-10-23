# SPDX-License-Identifier: MIT
# Copyright (c) 2024-2026 RAEN Digital Tools SL - PyNET Platform

import clr
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from Autodesk.Revit.DB import *
from Autodesk.Revit.DB.Structure import StructuralType
from System.Windows.Forms import *
from System.Drawing import *
from System import Decimal

try:
    Application.EnableVisualStyles()
except Exception:
    pass

doc = __revit__.ActiveUIDocument.Document  #type:ignore

DEFAULT_TYPE = "Fijo : 0915 x 1220mm"
DEFAULT_SILL = 0.90      # m
DEFAULT_SPACING = 2.50   # m between window axes
DEFAULT_EDGE = 0.50      # m min distance from window to wall end
TOP_MARGIN = 0.10        # m min distance from window head to wall top
EXCLUDE_TYPE_TEXT = "TRASDOSADO"  # linings parallel to a facade wall


def to_ft(m):
    return UnitUtils.ConvertToInternalUnits(m, UnitTypeId.Meters)


def to_m(ft):
    return UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Meters)


def symbol_label(s):
    return f"{s.FamilyName} : {Element.Name.__get__(s)}"


def symbol_size(s):
    w = s.get_Parameter(BuiltInParameter.WINDOW_WIDTH) or s.get_Parameter(BuiltInParameter.FAMILY_WIDTH_PARAM)
    h = s.get_Parameter(BuiltInParameter.WINDOW_HEIGHT) or s.get_Parameter(BuiltInParameter.FAMILY_HEIGHT_PARAM)
    return (w.AsDouble() if w else 0.0), (h.AsDouble() if h else 0.0)


def facade_walls(doc):
    walls = []
    for w in FilteredElementCollector(doc).OfClass(Wall).ToElements():
        wt = doc.GetElement(w.GetTypeId())
        if wt is None or wt.Kind != WallKind.Basic or wt.Function != WallFunction.Exterior:
            continue
        if EXCLUDE_TYPE_TEXT and EXCLUDE_TYPE_TEXT.lower() in wt.Name.lower():
            continue
        if not isinstance(w.Location, LocationCurve) or not isinstance(w.Location.Curve, Line):
            continue
        walls.append(w)
    return walls


def walls_with_windows(doc):
    hosts = set()
    for fi in FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType().ToElements():
        if fi.Host is not None:
            hosts.add(fi.Host.Id.Value)
    return hosts


class _WarningSwallower(IFailuresPreprocessor):
    __namespace__ = "RaenWindowsCreate_" + uuid.uuid4().hex[:8]

    def PreprocessFailures(self, fa):
        for f in list(fa.GetFailureMessages()):
            if f.GetSeverity() == FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                # never let Revit "resolve" errors by deleting elements
                return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


class WindowsCreateForm(Form):
    def __init__(self, symbols, levels, default_levels):
        super().__init__()
        self.confirmed = False
        self.symbols = symbols
        self.levels = levels
        self._build_ui(default_levels)

    def _add_label(self, text, y):
        lbl = Label()
        lbl.Parent = self
        lbl.Text = text
        lbl.Location = Point(20, y)
        lbl.Width = 220
        lbl.Height = 22

    def _add_number(self, value, y):
        nud = NumericUpDown()
        nud.Parent = self
        nud.DecimalPlaces = 2
        # NumericUpDown takes System.Decimal; pythonnet won't convert a Python float
        nud.Increment = Decimal(0.05)
        nud.Minimum = Decimal(0)
        nud.Maximum = Decimal(50)
        nud.Value = Decimal(value)
        nud.Location = Point(250, y)
        nud.Width = 150
        return nud

    def _build_ui(self, default_levels):
        self.Text = "PyNET - Generar ventanas"
        self.Width = 440
        self.Height = 520
        self.FormBorderStyle = FormBorderStyle.FixedDialog
        self.MaximizeBox = False
        self.CenterToScreen()
        self.TopMost = True

        self._add_label("Tipo de ventana:", 15)
        self.cb_type = ComboBox()
        self.cb_type.Parent = self
        self.cb_type.Location = Point(20, 40)
        self.cb_type.Width = 380
        self.cb_type.DropDownStyle = ComboBoxStyle.DropDownList
        for s in self.symbols:
            self.cb_type.Items.Add(symbol_label(s))
        labels = [symbol_label(s) for s in self.symbols]
        self.cb_type.SelectedIndex = labels.index(DEFAULT_TYPE) if DEFAULT_TYPE in labels else 0

        self._add_label("Altura de alféizar (m):", 80)
        self.nud_sill = self._add_number(DEFAULT_SILL, 78)
        self._add_label("Separación entre ejes (m):", 112)
        self.nud_spacing = self._add_number(DEFAULT_SPACING, 110)
        self._add_label("Distancia mínima a extremos (m):", 144)
        self.nud_edge = self._add_number(DEFAULT_EDGE, 142)

        self._add_label("Plantas:", 180)
        self.clb_levels = CheckedListBox()
        self.clb_levels.Parent = self
        self.clb_levels.Location = Point(20, 205)
        self.clb_levels.Width = 380
        self.clb_levels.Height = 200
        self.clb_levels.CheckOnClick = True
        for lv in self.levels:
            self.clb_levels.Items.Add(lv.Name, lv.Id.Value in default_levels)

        btn_ok = Button()
        btn_ok.Parent = self
        btn_ok.Text = "Generar"
        btn_ok.Location = Point(210, 425)
        btn_ok.Width = 90
        btn_ok.Click += self._on_ok

        btn_cancel = Button()
        btn_cancel.Parent = self
        btn_cancel.Text = "Cancelar"
        btn_cancel.Location = Point(310, 425)
        btn_cancel.Width = 90
        btn_cancel.Click += self._on_cancel

    def _on_ok(self, sender, args):
        self.confirmed = True
        self.Close()

    def _on_cancel(self, sender, args):
        self.Close()

    def options(self):
        return {
            "symbol": self.symbols[self.cb_type.SelectedIndex],
            "sill": Decimal.ToDouble(self.nud_sill.Value),
            "spacing": Decimal.ToDouble(self.nud_spacing.Value),
            "edge": Decimal.ToDouble(self.nud_edge.Value),
            "level_ids": set(self.levels[i].Id.Value for i in self.clb_levels.CheckedIndices),
        }


class WindowsCreateScript:
    @staticmethod
    def Generate(doc, symbol, sill, spacing, edge, level_ids):
        win_w, win_h = symbol_size(symbol)
        sill_ft, spacing_ft, edge_ft = to_ft(sill), to_ft(spacing), to_ft(edge)
        top_margin_ft = to_ft(TOP_MARGIN)
        hosted = walls_with_windows(doc)

        plan = []
        skipped = {"con ventanas": 0, "corto": 0, "bajo": 0}
        for w in facade_walls(doc):
            if w.LevelId.Value not in level_ids:
                continue
            if w.Id.Value in hosted:
                skipped["con ventanas"] += 1
                continue
            height = w.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM).AsDouble()
            if sill_ft + win_h > height - top_margin_ft:
                skipped["bajo"] += 1
                continue
            curve = w.Location.Curve
            usable = curve.Length - 2 * edge_ft
            if usable < win_w:
                skipped["corto"] += 1
                continue
            count = max(1, int((usable - win_w) / spacing_ft) + 1) if spacing_ft > 0 else 1
            level = doc.GetElement(w.LevelId)
            base_offset = w.get_Parameter(BuiltInParameter.WALL_BASE_OFFSET).AsDouble()
            for i in range(count):
                param = (edge_ft + usable * (i + 0.5) / count) / curve.Length
                p = curve.Evaluate(param, True)
                plan.append((w, level, XYZ(p.X, p.Y, level.Elevation + base_offset)))

        t = Transaction(doc, "Generar ventanas")
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(_WarningSwallower())
        t.SetFailureHandlingOptions(opts)
        t.Start()
        created, errors = 0, []
        try:
            if not symbol.IsActive:
                symbol.Activate()
                doc.Regenerate()
            for w, level, pt in plan:
                try:
                    fi = doc.Create.NewFamilyInstance(pt, symbol, w, level, StructuralType.NonStructural)
                    sp = fi.get_Parameter(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM)
                    if sp and not sp.IsReadOnly:
                        sp.Set(sill_ft)
                    created += 1
                except Exception as e:
                    errors.append((w.Id.Value, str(e)))
            status = t.Commit()
        except:
            t.RollBack()
            raise
        return {"status": str(status), "created": created if status == TransactionStatus.Committed else 0,
                "walls": len(set(w.Id.Value for w, _, _ in plan)), "skipped": skipped, "errors": errors}

    @staticmethod
    def Run(doc):
        symbols = sorted(FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Windows)
                         .WhereElementIsElementType().ToElements(), key=symbol_label)
        if not symbols:
            print("No hay tipos de ventana cargados en el modelo.")
            return None

        wall_level_ids = set(w.LevelId.Value for w in facade_walls(doc))
        levels = sorted([lv for lv in FilteredElementCollector(doc).OfClass(Level).ToElements()
                         if lv.Id.Value in wall_level_ids], key=lambda lv: lv.Elevation)
        default_levels = set(lv.Id.Value for lv in levels if lv.Elevation >= -1e-6)

        form = WindowsCreateForm(symbols, levels, default_levels)
        form.ShowDialog()
        if not form.confirmed:
            print("Cancelado.")
            return None
        o = form.options()
        if not o["level_ids"]:
            print("No se ha seleccionado ninguna planta.")
            return None

        r = WindowsCreateScript.Generate(doc, o["symbol"], o["sill"], o["spacing"], o["edge"], o["level_ids"])
        print(f"Tipo: {symbol_label(o['symbol'])}")
        print(f"Ventanas creadas: {r['created']} en {r['walls']} muros ({r['status']})")
        print(f"Muros omitidos: {r['skipped']}")
        if r["errors"]:
            print(f"Errores: {len(r['errors'])} -> {r['errors'][:10]}")
        return r


WindowsCreateScript.Run(doc)
