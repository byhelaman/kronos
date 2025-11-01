# schedule_service.py
import uuid
from typing import List, Dict, Any, Set, Tuple
from config import Schedule # Importamos el namedtuple

def _get_business_key(row_data: Dict[str, Any]) -> Tuple:
    """
    Crea una tupla (llave única) a partir de los 10 campos de datos
    para la detección de duplicados.
    """
    return (
        row_data.get("date"),
        row_data.get("shift"),
        row_data.get("area"),
        row_data.get("start_time"),
        row_data.get("end_time"),
        row_data.get("code"),
        row_data.get("instructor"),
        row_data.get("group"),
        row_data.get("minutes"),
        row_data.get("units"),
    )

def get_empty_schedule_data() -> Dict[str, List]:
    """Retorna la estructura de datos vacía para un nuevo schedule."""
    return {"processed_files": [], "all_rows": []}

def filter_active_rows(all_rows: List[Dict]) -> List[Dict]:
    """Filtra y devuelve solo las filas con estado 'active'."""
    return [row for row in all_rows if row.get("status") == "active"]

def get_deleted_rows_count(all_rows: List[Dict]) -> int:
    """Calcula el número de filas marcadas como 'deleted'."""
    active_count = len(filter_active_rows(all_rows))
    return len(all_rows) - active_count

def merge_new_schedules(
    current_rows: List[Dict], new_schedules: List[Schedule]
) -> List[Dict]:
    """
    Fusiona una lista de nuevos schedules parseados con la lista
    existente de filas, manejando duplicados y reactivaciones.
    Devuelve una NUEVA lista de 'all_rows'.
    """
    # Copiamos para evitar mutaciones inesperadas
    all_rows = [row.copy() for row in current_rows]
    
    rows_by_key: Dict[Tuple, Dict] = {
        _get_business_key(row["data"]): row for row in all_rows
    }
    
    new_entries = []

    for schedule in new_schedules:
        # inner_data = schedule._asdict() # Convertir namedtuple a dict

        inner_data = {
            "date": getattr(schedule, 'date', ''),
            "shift": getattr(schedule, 'shift', ''),
            "area": getattr(schedule, 'area', ''),
            "start_time": getattr(schedule, 'start_time', ''),
            "end_time": getattr(schedule, 'end_time', ''),
            "code": getattr(schedule, 'code', ''),
            "instructor": getattr(schedule, 'instructor', ''),
            "group": getattr(schedule, 'group', ''),
            "minutes": getattr(schedule, 'minutes', 0),
            "units": getattr(schedule, 'units', 0),
        }

        # inner_data = {
        #     "date": schedule.date,
        #     "shift": schedule.shift,
        #     "area": schedule.area,
        #     "start_time": schedule.start_time,
        #     "end_time": schedule.end_time,
        #     "code": schedule.code,
        #     "instructor": schedule.instructor,
        #     "group": schedule.group,
        #     "minutes": schedule.minutes,
        #     "units": schedule.units,
        # }

        row_tuple = _get_business_key(inner_data)
        existing_row = rows_by_key.get(row_tuple)

        if existing_row:
            if existing_row.get("status") == "deleted":
                existing_row["status"] = "active"
        else:
            new_row_entry = {
                "id": str(uuid.uuid4()),
                "status": "active",
                "data": inner_data,
            }
            new_entries.append(new_row_entry)
            rows_by_key[row_tuple] = new_row_entry

    all_rows.extend(new_entries)
    return all_rows

def delete_rows_by_id(
    current_rows: List[Dict], ids_to_delete: Set[str]
) -> Tuple[List[Dict], int]:
    """
    Marca filas como 'deleted' basado en un set de IDs.
    Devuelve una NUEVA lista de 'all_rows' y el contador de filas borradas.
    """
    all_rows = [row.copy() for row in current_rows]
    deleted_count = 0
    for row in all_rows:
        if row.get("id") in ids_to_delete and row.get("status") == "active":
            row["status"] = "deleted"
            deleted_count += 1
    return all_rows, deleted_count

def restore_deleted_rows(current_rows: List[Dict]) -> Tuple[List[Dict], int]:
    """
    Restaura filas 'deleted' si no crean un duplicado activo.
    Devuelve una NUEVA lista de 'all_rows' y el contador de filas restauradas.
    """
    all_rows = [row.copy() for row in current_rows]
    
    active_rows_set: Set[Tuple] = {
        _get_business_key(row["data"]) for row in all_rows if row["status"] == "active"
    }

    restored_count = 0
    for row in all_rows:
        if row.get("status") == "deleted":
            row_tuple = _get_business_key(row["data"])
            if row_tuple not in active_rows_set:
                row["status"] = "active"
                restored_count += 1
                active_rows_set.add(row_tuple)

    return all_rows, restored_count