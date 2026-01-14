from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional, List

import pandas as pd
from openpyxl import load_workbook


@dataclass(frozen=True)
class ExcelLoadResult:
    fixture_results: pd.DataFrame
    players: Optional[pd.DataFrame] = None
    teams: Optional[pd.DataFrame] = None
    league_data: Optional[pd.DataFrame] = None


def _read_named_table(wb, sheet_name: str, table_name: str) -> pd.DataFrame:
    """
    Read an Excel Table (ListObject) by name and return a DataFrame.
    Uses the table ref so it stays correct even if the table range moves.
    """
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"Sheet '{sheet_name}' not found in workbook.")

    ws = wb[sheet_name]
    if table_name not in ws.tables:
        available = ", ".join(sorted(ws.tables.keys())) if ws.tables else "(none)"
        raise ValueError(
            f"Table '{table_name}' not found on sheet '{sheet_name}'. Tables found: {available}"
        )

    table = ws.tables[table_name]
    ref = table.ref  # e.g. "B2:R32"
    cells = ws[ref]

    data: List[List[object]] = []
    for row in cells:
        data.append([c.value for c in row])

    if not data or len(data) < 2:
        raise ValueError(f"Table '{table_name}' appears to be empty.")

    headers = [str(h).strip() if h is not None else "" for h in data[0]]
    rows = data[1:]

    df = pd.DataFrame(rows, columns=headers)
    df = df.dropna(axis=1, how="all")  # drop fully empty columns
    return df


def load_league_workbook_from_bytes(xlsm_bytes: bytes) -> ExcelLoadResult:
    """
    Load the league workbook from bytes and return key tables.
    data_only=True reads cached formula results saved by Excel.
    """
    bio = BytesIO(xlsm_bytes)
    wb = load_workbook(bio, data_only=True)

    fixture_results = _read_named_table(
        wb, sheet_name="Fixture_Results", table_name="Fixture_Results_Table"
    )

    # Optional tables (only if they exist)
    players = None
    teams = None

    try:
        players = _read_named_table(wb, sheet_name="Players", table_name="Player_Data")
    except Exception:
        players = None

    try:
        teams = _read_named_table(wb, sheet_name="Teams", table_name="Teams_Table")
    except Exception:
        teams = None

    league_data = None
    if "League_Data" in wb.sheetnames:
        ws = wb["League_Data"]
        values = list(ws.values)
        if values and len(values) >= 2:
            headers = [str(h).strip() if h is not None else "" for h in values[0]]
            rows = values[1:]
            league_data = pd.DataFrame(rows, columns=headers).dropna(axis=1, how="all")

    return ExcelLoadResult(
        fixture_results=fixture_results,
        players=players,
        teams=teams,
        league_data=league_data,
    )
