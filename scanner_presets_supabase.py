from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


class PresetStoreSupabase:
    """Misma interfaz que PresetStoreJSON: listar() / guardar() / eliminar()."""

    def __init__(self, client, tabla: str = "scanner_presets",
                 user_id: Optional[str] = None):
        self.sb = client
        self.tabla = tabla
        self.user_id = (user_id or "global")

    def listar(self) -> dict:
        try:
            r = (self.sb.table(self.tabla)
                 .select("nombre,datos")
                 .eq("user_id", self.user_id)
                 .order("nombre")
                 .execute())
            return {x["nombre"]: x["datos"] for x in (r.data or [])}
        except Exception:
            return {}

    def guardar(self, nombre: str, datos: dict) -> None:
        (self.sb.table(self.tabla)
         .upsert({"user_id": self.user_id, "nombre": nombre, "datos": datos,
                  "updated_at": datetime.now(timezone.utc).isoformat()},
                 on_conflict="user_id,nombre")
         .execute())

    def eliminar(self, nombre: str) -> None:
        (self.sb.table(self.tabla)
         .delete()
         .eq("user_id", self.user_id)
         .eq("nombre", nombre)
         .execute())
