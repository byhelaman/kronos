import os
from typing import List
import pandas as pd

from models.schedule_model import Schedule
from .text_utils import (
    extract_parenthesized_schedule,
    extract_keyword_from_text,
    filter_special_tags,
    extract_duration_or_keyword,
    format_time_periods,
    determine_shift_by_time,
)


def parse_excel_file(file_path: str, engine: str) -> List[Schedule]:
    MAX_SHEETS_TO_PROCESS = 100
    MAX_ROWS_PER_SHEET = 1000
    DATA_START_INDEX = 6

    schedules: List[Schedule] = []
    with pd.ExcelFile(file_path, engine=engine) as xls:

        sheet_names_to_process = xls.sheet_names[:MAX_SHEETS_TO_PROCESS]
        for sheet_name in sheet_names_to_process:
            df = pd.read_excel(xls, sheet_name)
            if df.empty:
                continue

            # Extrae metadatos a nivel de hoja.
            try:
                schedule_date = df.iat[0, 14]
                location = df.iat[0, 21]
                area_name = extract_keyword_from_text(location) or ""
                instructor_name = df.iat[4, 0]
                instructor_code = df.iat[3, 0]
            except Exception:
                # Omite las hojas que no se ajustan al diseño esperado.
                continue

            try:
                GROUP_NAME_COL_INDEX = 17

                all_group_counts = (
                    df.iloc[DATA_START_INDEX:][df.columns[GROUP_NAME_COL_INDEX]]
                    .value_counts()
                    .to_dict()
                )
            except Exception:
                all_group_counts = {}

            end_row_index = DATA_START_INDEX + MAX_ROWS_PER_SHEET
            for _, row in df.iloc[DATA_START_INDEX:end_row_index].iterrows():

                start_time = row.iloc[0]
                end_time = row.iloc[3]

                group_name = (
                    row.iloc[GROUP_NAME_COL_INDEX]
                    if len(row) > GROUP_NAME_COL_INDEX
                    else None
                )
                raw_block = row.iloc[19] if len(row) > 19 else None

                if pd.notna(raw_block):
                    block_filtered = filter_special_tags(str(raw_block))
                else:
                    block_filtered = None

                program_name = row.iloc[25] if len(row) > 25 else None

                if not all(
                    pd.notnull(value) and str(value).strip() != ""
                    for value in (start_time, end_time)
                ):
                    continue

                if not (pd.notna(group_name) and str(group_name).strip()):
                    if block_filtered and str(block_filtered).strip():
                        group_name = block_filtered
                    else:
                        continue  # ni grupo ni bloque válidos → saltar fila

                duration = extract_duration_or_keyword(str(program_name)) or ""
                unit_count = all_group_counts.get(group_name, 0)

                shift = determine_shift_by_time(
                    extract_parenthesized_schedule(str(start_time))
                )

                program_keyword = extract_keyword_from_text(str(program_name))
                area_value = (
                    f"{area_name}/{program_keyword}"
                    if program_keyword == "KIDS" and area_name
                    else area_name
                )
                try:
                    date_str = schedule_date.strftime("%d/%m/%Y")
                except Exception:
                    date_str = str(schedule_date)

                schedule = Schedule(
                    date=date_str,
                    shift=shift,
                    area=area_value,
                    start_time=format_time_periods(
                        extract_parenthesized_schedule(str(start_time))
                    ),
                    end_time=format_time_periods(
                        extract_parenthesized_schedule(str(end_time))
                    ),
                    code=str(instructor_code),
                    instructor=str(instructor_name),
                    group=str(group_name),
                    minutes=str(duration),
                    units=unit_count,
                )
                schedules.append(schedule)
    return schedules


__all__ = ["parse_excel_file"]
