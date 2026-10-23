# SPDX-License-Identifier: MIT
# Copyright (c) 2024-2026 RAEN Digital Tools SL - PyNET Platform

import clr

clr.AddReference("System.Windows.Forms")

from System.Windows.Forms import MessageBox, MessageBoxButtons, MessageBoxIcon, DialogResult

# The host injects the Presto COM application (Presto.App.18) as __presto__
try:
    app = __presto__
except NameError:
    raise Exception("__presto__ not found: run this script from PyNET for Presto (Complementos > PyNET).")

# ---------------------------------------------------------------------------
# Set the price of every partida (Nat 5) of the active obra to 0, after a
# YesNo confirmation that names the obra. Partidas with a breakdown get their
# price from their children on recalculation: they are reported, and their
# price is read back after Recalculate.
#
# Verified on Presto 26.01. One undo step (Ctrl+Z in Presto). Changes are NOT
# saved: save the obra in Presto.
# ---------------------------------------------------------------------------
PRICE_FIELD = "Conceptos.Pres"
FILTER = "Conceptos.Nat!=219 && Conceptos.Nat!=170"
LOOP_SLOT = 1
LOOKUP_SLOT = 9
NAT_PARTIDA = 5
NEW_PRICE = 0.0

project = app.Project()
if not project:
    raise Exception("No obra open in Presto.")

codes = []
app.SetElement(LOOP_SLOT, "Conceptos", "Conceptos.Código", '"*"', "Conceptos.Nat == " + str(NAT_PARTIDA))
while app.GetElement(LOOP_SLOT) == 0:
    codes.append(app.GetFieldStr("Conceptos.Código"))

if not codes:
    MessageBox.Show("The obra has no partidas.", "Reset prices", MessageBoxButtons.OK, MessageBoxIcon.Information)
else:
    answer = MessageBox.Show(
        "Set the price of " + str(len(codes)) + " partidas to 0 in:\n" + project + "\n\nContinue?",
        "Reset prices", MessageBoxButtons.YesNo, MessageBoxIcon.Warning)
    if answer == DialogResult.Yes:
        app.BeginRedo()
        try:
            for code in codes:
                if app.FindEqual("Conceptos", "Conceptos.Código", code) == 0:
                    app.SetField(PRICE_FIELD, NEW_PRICE)
                    app.UpdateRecord("Conceptos")
        finally:
            app.EndRedo()
        app.Recalculate(1)
        app.UpdateScreen()

        # read back: partidas with a breakdown keep the price of their children
        not_reset = []
        for code in codes:
            app.FindEqual("Conceptos", "Conceptos.Código", code)
            price = app.GetFieldNum(PRICE_FIELD) or 0.0
            if abs(price - NEW_PRICE) > 1e-9:
                app.SetElement(LOOKUP_SLOT, "Relaciones", "Relaciones.CodSup", '"' + code + '"', FILTER)
                reason = "breakdown" if app.GetElement(LOOKUP_SLOT) == 0 else "not changed"
                not_reset.append(code + " = " + str(price) + " (" + reason + ")")

        for code in codes:
            print(code)
        msg = str(len(codes) - len(not_reset)) + " of " + str(len(codes)) + " partidas set to 0."
        if not_reset:
            msg += "\n\nNot reset:\n" + "\n".join(not_reset)
        msg += "\n\nThe obra is NOT saved: save it in Presto."
        print(msg)
        MessageBox.Show(msg, "Reset prices", MessageBoxButtons.OK,
                        MessageBoxIcon.Warning if not_reset else MessageBoxIcon.Information)
