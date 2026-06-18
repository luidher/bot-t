"""
db_manager.py — Motor de persistencia SQLite para el Modo Autopilot DB.

Tabla: respuestas
  id                INTEGER PRIMARY KEY AUTOINCREMENT
  hash_pregunta     TEXT UNIQUE NOT NULL   (SHA-256 del texto normalizado)
  texto_pregunta    TEXT NOT NULL
  opcion_correcta   TEXT NOT NULL          (texto visible de la opción)
  selector_correcto TEXT DEFAULT ''        (data-op u otro selector único de la opción)
  fecha_guardado    DATETIME DEFAULT CURRENT_TIMESTAMP

Índice: idx_hash ON respuestas(hash_pregunta)
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

# Ruta por defecto de la base de datos
DEFAULT_DB_PATH = Path("autopilot_respuestas.db")

# Tamaño del buffer antes de hacer un flush masivo
BUFFER_SIZE = 100


class DBManager:
    """Gestor de base de datos SQLite para el Autopilot DB."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._buffer: list[tuple[str, str, str, str]] = []  # (hash, pregunta, opcion, selector)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Inicialización
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Devuelve la conexión activa (abre una nueva si no existe)."""
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
        return self._conn

    def _init_db(self) -> None:
        """Crea la tabla e índice si no existen. Migra columnas nuevas si la BD ya existe."""
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS respuestas (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                hash_pregunta     TEXT    UNIQUE NOT NULL,
                texto_pregunta    TEXT    NOT NULL,
                opcion_correcta   TEXT    NOT NULL,
                selector_correcto TEXT    DEFAULT '',
                fecha_guardado    DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_hash
            ON respuestas(hash_pregunta)
        """)
        conn.commit()

        # Migración: agregar columna selector_correcto si no existe (BD antigua)
        try:
            cur = conn.execute("PRAGMA table_info(respuestas)")
            cols = [row[1] for row in cur.fetchall()]
            if "selector_correcto" not in cols:
                conn.execute("ALTER TABLE respuestas ADD COLUMN selector_correcto TEXT DEFAULT ''")
                conn.commit()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Funciones auxiliares públicas
    # ------------------------------------------------------------------

    @staticmethod
    def calcular_hash(texto: str) -> str:
        """
        Normaliza el texto (minúsculas, espacios múltiples → uno) y devuelve
        su SHA-256 en formato hexadecimal.
        """
        texto_normalizado = re.sub(r"\s+", " ", texto.lower().strip())
        return hashlib.sha256(texto_normalizado.encode("utf-8")).hexdigest()

    def consultar_db(self, hash_pregunta: str) -> Optional[dict]:
        """
        Busca el hash en la BD.
        Retorna un dict {'texto': str, 'selector': str} si existe, o None si no.
        """
        conn = self._connect()
        cur = conn.execute(
            "SELECT opcion_correcta, selector_correcto FROM respuestas WHERE hash_pregunta = ?",
            (hash_pregunta,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"texto": row[0], "selector": row[1] or ""}

    def consultar_por_selector(self, selector: str) -> Optional[dict]:
        """
        Busca por data-op/selector único en la BD.
        Retorna un dict {'texto': str, 'selector': str, 'hash': str} o None.
        """
        if not selector:
            return None
        conn = self._connect()
        cur = conn.execute(
            "SELECT opcion_correcta, selector_correcto, hash_pregunta FROM respuestas WHERE selector_correcto = ?",
            (selector,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"texto": row[0], "selector": row[1], "hash": row[2]}

    def guardar_en_db(
        self,
        hash_pregunta: str,
        texto_pregunta: str,
        opcion_correcta: str,
        selector_correcto: str = "",
        inmediato: bool = False,
    ) -> None:
        """
        Agrega al buffer en memoria. Si el buffer supera BUFFER_SIZE o
        se pide inserción inmediata, hace flush masivo.
        """
        self._buffer.append((hash_pregunta, texto_pregunta, opcion_correcta, selector_correcto))
        if inmediato or len(self._buffer) >= BUFFER_SIZE:
            self.flush_buffer()

    def flush_buffer(self) -> int:
        """
        Vuelca todos los registros del buffer a la BD usando INSERT OR REPLACE
        en una sola transacción. Devuelve el número de registros escritos.
        """
        if not self._buffer:
            return 0

        conn = self._connect()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO respuestas
                    (hash_pregunta, texto_pregunta, opcion_correcta, selector_correcto)
                VALUES (?, ?, ?, ?)
                """,
                self._buffer,
            )
            conn.commit()
            written = len(self._buffer)
            self._buffer.clear()
            return written
        except Exception as exc:
            print(f"[DB ERROR] Error en flush_buffer: {exc}")
            return 0

    # ------------------------------------------------------------------
    # Estadísticas
    # ------------------------------------------------------------------

    def contar_registros(self) -> int:
        """Devuelve el número total de filas en la tabla respuestas."""
        conn = self._connect()
        cur = conn.execute("SELECT COUNT(*) FROM respuestas")
        row = cur.fetchone()
        return row[0] if row else 0

    def obtener_ultimos(self, n: int = 5) -> list[dict]:
        """Devuelve los últimos N registros guardados (más recientes primero)."""
        conn = self._connect()
        cur = conn.execute(
            """
            SELECT texto_pregunta, opcion_correcta, selector_correcto, fecha_guardado
            FROM respuestas
            ORDER BY id DESC
            LIMIT ?
            """,
            (n,),
        )
        cols = ["pregunta", "opcion", "selector", "fecha"]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Vacía el buffer pendiente y cierra la conexión."""
        self.flush_buffer()
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "DBManager":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
