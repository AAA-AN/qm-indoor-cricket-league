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


def _read_named_table(
    wb,
    sheet_name: str,
    table_name: str,
    *,
    drop_empty_columns: bool = True,
) -> pd.DataFrame:
    """
    Read an Excel Table (ListObject) by name and return a DataFrame.
    Uses the table ref so it stays correct even if the table range moves.

    drop_empty_columns:
      - True  -> drop columns that are entirely empty (all None/NaN)
      - False -> keep columns even if entirely empty (important for fixtures schema)
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
    ref = table.ref  # e.g. "B2:T32"
    cells = ws[ref]

    data: List[List[object]] = []
    for row in cells:
        data.append([c.value for c in row])

    if not data or len(data) < 2:
        raise ValueError(f"Table '{table_name}' appears to be empty.")

    headers = [str(h).strip() if h is not None else "" for h in data[0]]
    rows = data[1:]

    df = pd.DataFrame(rows, columns=headers)

    # Always drop columns with blank header names (these are never useful)
    blank_header_cols = [c for c in df.columns if str(c).strip() == ""]
    if blank_header_cols:
        df = df.drop(columns=blank_header_cols)

    # Only drop fully empty columns if requested
    if drop_empty_columns:
        df = df.dropna(axis=1, how="all")

    return df


def load_league_workbook_from_bytes(xlsm_bytes: bytes) -> ExcelLoadResult:
    """
    Load the league workbook from bytes and return key tables.
    data_only=True reads cached formula results saved by Excel.
    """
    bio = BytesIO(xlsm_bytes)
    wb = load_workbook(bio, data_only=True)

    # REQUIRED: fixtures table
    # Keep empty columns so schema is stable even before any results are entered.
    fixture_results = _read_named_table(
        wb,
        sheet_name="Fixture_Results",
        table_name="Fixture_Results_Table",
        drop_empty_columns=False,
    )

    # Optional tables
    players = None
    teams = None
    league_data = None

    try:
        players = _read_named_table(wb, sheet_name="Players", table_name="Player_Data", drop_empty_columns=True)
    except Exception:
        players = None

    try:
        teams = _read_named_table(wb, sheet_name="Teams", table_name="Teams_Table", drop_empty_columns=True)
    except Exception:
        teams = None

    try:
        league_data = _read_named_table(
            wb, sheet_name="League_Data", table_name="League_Data_Stats", drop_empty_columns=True
        )
    except Exception:
        league_data = None

    return ExcelLoadResult(
        fixture_results=fixture_results,
        players=players,
        teams=teams,
        league_data=league_data,
    )
