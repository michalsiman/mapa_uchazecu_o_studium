# Projekt: Mapa uchazečů o studium
# Autor: Michal Šiman (OK1SIM)
# Github: https://github.com/michalsiman/mapa_uchazecu_o_studium
# Verze: 1.0
# 
import configparser
import csv
import hashlib
import html
import json
import re
import socket
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from folium import DivIcon, Element, Icon, Map, Marker, Popup
from folium.plugins import MarkerCluster
from geopy.distance import geodesic
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from PySide6.QtCore import QUrl, QThread, QObject, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOAD_DIR = STORAGE_DIR / "uploads"
CACHE_FILE = STORAGE_DIR / "geocache.json"
FILES_FILE = STORAGE_DIR / "files.json"
POINTS_CACHE_FILE = STORAGE_DIR / "points_cache.json"
FAILED_LOCATIONS_FILE = STORAGE_DIR / "failed_locations.json"
MAP_META_FILE = STORAGE_DIR / "map_meta.json"
CONFIG_FILE = BASE_DIR / "config.ini"
MAP_FILE = STORAGE_DIR / "map.html"
REPORTS_DIR = STORAGE_DIR / "reports"
UPDATES_DIR = STORAGE_DIR / "updates"
APP_VERSION = "1.0"
APP_YEAR = "2026"
APP_GITHUB_URL = "https://github.com/michalsiman/mapa_uchazecu_o_studium"


class DataStorage:
    def __init__(self) -> None:
        self.storage_dir = STORAGE_DIR
        self.upload_dir = UPLOAD_DIR
        self.cache_file = CACHE_FILE
        self.files_file = FILES_FILE
        self.map_meta_file = MAP_META_FILE
        self.config_file = CONFIG_FILE
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self._load_file_index()
        self._load_cache()
        self._load_points_cache()
        self._load_failed_locations_cache()
        self._load_map_meta()
        self._load_config()
        self.geolocator = Nominatim(user_agent="uchazeci-map-app")
        self.geocode = RateLimiter(self.geolocator.geocode, min_delay_seconds=1, error_wait_seconds=2.0)

    def _load_file_index(self) -> None:
        if self.files_file.exists():
            try:
                self.file_index = json.loads(self.files_file.read_text(encoding="utf-8"))
            except Exception:
                self.file_index = []
        else:
            self.file_index = []

    def _save_file_index(self) -> None:
        self.files_file.write_text(json.dumps(self.file_index, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_existing_upload_paths(self) -> list[Path]:
        paths: list[Path] = []
        for name in list(self.file_index):
            path = self.upload_dir / name
            if path.exists():
                paths.append(path)
        return paths

    def _load_cache(self) -> None:
        if self.cache_file.exists():
            try:
                self.location_cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            except Exception:
                self.location_cache = {}
        else:
            self.location_cache = {}

    def _load_map_meta(self) -> None:
        if self.map_meta_file.exists():
            try:
                self.map_meta = json.loads(self.map_meta_file.read_text(encoding="utf-8"))
            except Exception:
                self.map_meta = {}
        else:
            self.map_meta = {}

    def _load_points_cache(self) -> None:
        if POINTS_CACHE_FILE.exists():
            try:
                self.points_cache = json.loads(POINTS_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.points_cache = {}
        else:
            self.points_cache = {}

    def _load_failed_locations_cache(self) -> None:
        if FAILED_LOCATIONS_FILE.exists():
            try:
                self.failed_locations_cache = json.loads(FAILED_LOCATIONS_FILE.read_text(encoding="utf-8"))
            except Exception:
                self.failed_locations_cache = {}
        else:
            self.failed_locations_cache = {}

    def _save_points_cache(self) -> None:
        POINTS_CACHE_FILE.write_text(json.dumps(self.points_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_failed_locations_cache(self) -> None:
        FAILED_LOCATIONS_FILE.write_text(
            json.dumps(self.failed_locations_cache, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_config(self) -> None:
        self.config = configparser.ConfigParser()
        if not self.config_file.exists():
            self.config["map"] = {
                "home_school_address": "",
                "home_school_label": "Moje škola",
            }
            with self.config_file.open("w", encoding="utf-8") as f:
                self.config.write(f)
        else:
            self.config.read(self.config_file, encoding="utf-8")
        self.home_school_address = self.config.get("map", "home_school_address", fallback=None)
        self.home_school_label = self.config.get("map", "home_school_label", fallback="Moje škola")

    def _save_cache(self) -> None:
        self.cache_file.write_text(json.dumps(self.location_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_points_cache(self) -> None:
        POINTS_CACHE_FILE.write_text(json.dumps(self.points_cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_map_meta(self) -> None:
        self.map_meta_file.write_text(json.dumps(self.map_meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_postal_code(self, text: str) -> str:
        digits_only = re.sub(r"\D", "", text or "")
        if len(digits_only) >= 5:
            return digits_only[:5]
        return digits_only

    def _location_cache_key(self, address: str, psc: str) -> str:
        normalized_psc = self._normalize_postal_code(psc) or self._extract_postal_code(address)
        psc_part = normalized_psc if normalized_psc else str(psc or "").strip()
        return f"{str(address or '').strip()}|{psc_part}".strip().lower()

    def has_cached_location(self, address: str, psc: str) -> bool:
        key = self._location_cache_key(address, psc)
        return key in self.location_cache

    def _location_matches_postal_code(self, location: Any, requested_psc: str) -> bool:
        if not requested_psc:
            return True

        raw = getattr(location, "raw", None)
        if not isinstance(raw, dict):
            return True

        postcode_candidates: list[str] = []
        address_part = raw.get("address")
        if isinstance(address_part, dict):
            postcode = address_part.get("postcode")
            if postcode:
                postcode_candidates.append(str(postcode))

        display_name = raw.get("display_name")
        if isinstance(display_name, str):
            postcode_candidates.extend(re.findall(r"\b\d{3}\s?\d{2}\b", display_name))

        if not postcode_candidates:
            return True

        normalized_candidates = {
            self._normalize_postal_code(candidate)
            for candidate in postcode_candidates
            if self._normalize_postal_code(candidate)
        }
        return requested_psc in normalized_candidates

    def _file_hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def get_cached_points(self, path: Path) -> list[dict[str, Any]] | None:
        file_hash = self._file_hash(path)
        points = self.points_cache.get(file_hash)
        if points is None:
            return None
        return points

    def set_cached_points(self, path: Path, points: list[dict[str, Any]]) -> None:
        file_hash = self._file_hash(path)
        self.points_cache[file_hash] = points
        self._save_points_cache()

    def get_failed_locations(self, path: Path) -> list[dict[str, Any]]:
        entries = self.failed_locations_cache.get(path.name, [])
        return entries if isinstance(entries, list) else []

    def set_failed_locations(self, path: Path, failed_locations: list[dict[str, Any]]) -> None:
        self.failed_locations_cache[path.name] = failed_locations
        self._save_failed_locations_cache()

    def get_all_failed_locations(self) -> list[dict[str, Any]]:
        combined: list[dict[str, Any]] = []
        for name in list(self.file_index):
            path = self.upload_dir / name
            if not path.exists():
                continue
            entries = self.failed_locations_cache.get(name, [])
            if isinstance(entries, list):
                combined.extend(entries)
        return combined

    def has_retryable_failed_locations(self, path: Path) -> bool:
        for entry in self.get_failed_locations(path):
            if self._resolve_home_school_alias_location(
                str(entry.get("address", "") or ""),
                str(entry.get("psc", "") or ""),
            ) is not None:
                return True
        return False

    def has_incomplete_cached_points(self, path: Path) -> bool:
        try:
            records = self.parse_csv(path)
        except Exception:
            return False

        cached_points = self.get_cached_points(path) or []
        cached_ids = {self._point_identity(point) for point in cached_points}
        failed_ids = {self._failed_identity(entry) for entry in self.get_failed_locations(path)}

        for record in records:
            if self._record_identity(record) in cached_ids:
                continue
            if self._failed_identity(record) in failed_ids:
                continue
            return True
        return False

    def has_home_alias_coordinate_mismatch(self, path: Path) -> bool:
        home_location = self.lookup_query(self.home_school_address) if self.home_school_address else None
        if home_location is None:
            return False

        cached_points = self.get_cached_points(path) or []
        point_by_identity = {self._point_identity(point): point for point in cached_points}

        try:
            records = self.parse_csv(path)
        except Exception:
            return False

        for record in records:
            alias_location = self._resolve_home_school_alias_location(
                str(record.get("address", "") or ""),
                str(record.get("psc", "") or ""),
            )
            if alias_location is None:
                continue
            point = point_by_identity.get(self._record_identity(record))
            if point is None:
                return True
            lat = float(point.get("lat", 0.0) or 0.0)
            lng = float(point.get("lng", 0.0) or 0.0)
            if abs(lat - float(home_location[0])) > 1e-7 or abs(lng - float(home_location[1])) > 1e-7:
                return True

        return False

    def should_refresh_points_cache(self, path: Path) -> bool:
        return (
            self.has_incomplete_cached_points(path)
            or self.has_retryable_failed_locations(path)
            or self.has_home_alias_coordinate_mismatch(path)
        )

    def _normalize_name(self, path: Path) -> str:
        candidate = path.name
        counter = 1
        while (self.upload_dir / candidate).exists():
            candidate = f"{path.stem}_{counter}{path.suffix}"
            counter += 1
        return candidate

    def add_uploaded_file(self, source: Path) -> Path:
        target_name = self._normalize_name(source)
        target = self.upload_dir / target_name
        with source.open("rb") as src, target.open("wb") as dst:
            dst.write(src.read())
        if target_name not in self.file_index:
            self.file_index.append(target_name)
            self._save_file_index()
        return target

    def list_files(self) -> list[dict[str, str]]:
        return [self.file_info(name) for name in self.file_index if (self.upload_dir / name).exists()]

    def file_info(self, name: str) -> dict[str, str]:
        path = self.upload_dir / name
        if path.exists():
            return {"name": name, "size": self._format_size(path.stat().st_size)}
        return {"name": name, "size": "soubor nenalezen"}

    def delete_file(self, name: str) -> None:
        path = self.upload_dir / name
        if path.exists():
            self._clear_file_related_cache(path)
            path.unlink()
        if name in self.file_index:
            self.file_index.remove(name)
            self._save_file_index()

    def _clear_file_related_cache(self, path: Path) -> None:
        records: list[dict[str, Any]] = []
        try:
            records = self.parse_csv(path)
        except Exception:
            records = []

        try:
            file_hash = self._file_hash(path)
        except Exception:
            file_hash = None

        points_cache_changed = False
        if file_hash is not None and file_hash in self.points_cache:
            self.points_cache.pop(file_hash, None)
            points_cache_changed = True

        location_cache_changed = False
        for record in records:
            key = self._location_cache_key(
                str(record.get('address', '') or ''),
                str(record.get('psc', '') or ''),
            )
            if key and key in self.location_cache:
                self.location_cache.pop(key, None)
                location_cache_changed = True

        if points_cache_changed:
            self._save_points_cache()
        if location_cache_changed:
            self._save_cache()
        if path.name in self.failed_locations_cache:
            self.failed_locations_cache.pop(path.name, None)
            self._save_failed_locations_cache()

    def _format_size(self, size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} kB"
        return f"{size / 1024 / 1024:.1f} MB"

    def compute_data_signature(self) -> str:
        file_info = []
        for name in sorted(self.file_index):
            path = self.upload_dir / name
            if not path.exists():
                continue
            stat = path.stat()
            file_info.append({
                "name": name,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
        return json.dumps(file_info, ensure_ascii=False, sort_keys=True)

    def compute_file_signature(self, path: Path) -> str:
        stat = path.stat()
        file_info = {
            "name": path.name,
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
        }
        return json.dumps(file_info, ensure_ascii=False, sort_keys=True)

    def _normalize_selected_filter_values(self, selected_values: list[str] | None) -> list[str] | None:
        if selected_values is None:
            return None
        return sorted(selected_values)

    def _extract_postal_code(self, text: str) -> str:
        match = re.search(r"\b(\d{3}\s?\d{2})\b", text or "")
        return self._normalize_postal_code(match.group(1)) if match else ""

    def _normalize_text_for_match(self, text: str) -> str:
        lowered = (text or "").strip().lower()
        normalized = unicodedata.normalize("NFKD", lowered)
        without_diacritics = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", without_diacritics).strip()

    def _street_name_without_number(self, address: str) -> str:
        normalized_address = self._normalize_text_for_match(address)
        return re.sub(r"\s+\d+[a-zA-Z]?$", "", normalized_address).strip()

    def _address_street_candidates(self, address: str) -> set[str]:
        parts = [part.strip() for part in (address or "").split(",") if part.strip()]
        candidates: set[str] = set()
        postal_pattern = re.compile(r"^\d{3}\s?\d{2}(\s+.+)?$")

        for part in parts:
            if not re.search(r"\d", part):
                continue
            if postal_pattern.match(part):
                continue
            street = self._street_name_without_number(part)
            if street:
                candidates.add(street)

        if not candidates and parts:
            fallback_street = self._street_name_without_number(parts[0])
            if fallback_street:
                candidates.add(fallback_street)

        return candidates

    def _resolve_home_school_alias_location(self, address: str, psc: str) -> tuple[float, float] | None:
        if not self.home_school_address:
            return None

        requested_candidates = self._address_street_candidates(address)
        home_candidates = self._address_street_candidates(self.home_school_address)
        if not requested_candidates or not home_candidates:
            return None
        if requested_candidates.isdisjoint(home_candidates):
            return None

        requested_psc = self._extract_postal_code(psc) or self._extract_postal_code(address)
        home_psc = self._extract_postal_code(self.home_school_address)
        if not requested_psc or not home_psc or requested_psc != home_psc:
            return None

        return self.lookup_query(self.home_school_address)

    def _record_identity(self, record: dict[str, Any]) -> tuple[str, str, int, str, str, str, str, str]:
        return (
            str(record.get("address", "") or "").strip(),
            str(record.get("psc", "") or "").strip(),
            int(record.get("count", 0) or 0),
            str(record.get("kod_oboru", "") or "").strip(),
            str(record.get("obor_nazev", "") or "").strip(),
            str(record.get("priorita", "") or "").strip(),
            str(record.get("uchazec_jmeno", "") or "").strip(),
            str(record.get("uchazec_prijmeni", "") or "").strip(),
        )

    def _point_identity(self, point: dict[str, Any]) -> tuple[str, str, int, str, str, str, str, str]:
        return self._record_identity(point)

    def _failed_identity(self, record: dict[str, Any]) -> tuple[str, str, int, str, str]:
        return (
            str(record.get("address", "") or "").strip(),
            str(record.get("psc", "") or "").strip(),
            int(record.get("count", 0) or 0),
            str(record.get("uchazec_jmeno", "") or "").strip(),
            str(record.get("uchazec_prijmeni", "") or "").strip(),
        )

    def _build_point_from_record(self, record: dict[str, Any], location: tuple[float, float]) -> dict[str, Any]:
        return {
            "address": record["address"],
            "psc": record["psc"],
            "count": record["count"],
            "kod_oboru": record.get("kod_oboru", ""),
            "obor_nazev": record.get("obor_nazev", ""),
            "priorita": record.get("priorita", ""),
            "uchazec_jmeno": record.get("uchazec_jmeno", ""),
            "uchazec_prijmeni": record.get("uchazec_prijmeni", ""),
            "lat": location[0],
            "lng": location[1],
        }

    def _build_failed_location_entry(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "address": record["address"],
            "psc": record["psc"],
            "count": int(record.get("count", 0) or 0),
            "uchazec_jmeno": record.get("uchazec_jmeno", ""),
            "uchazec_prijmeni": record.get("uchazec_prijmeni", ""),
        }

    def refresh_cached_points_from_records(
        self,
        path: Path,
        records: list[dict[str, Any]],
        progress_callback: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        refreshed_points: list[dict[str, Any]] = []
        failed_locations: list[dict[str, Any]] = []
        total = len(records)

        for index, record in enumerate(records, start=1):
            if progress_callback is not None:
                cached_location = self.has_cached_location(record["address"], record["psc"])
                progress_stage = "cached" if cached_location else "geocoding"
                progress_callback(index, total, progress_stage)
            location = self.lookup_location(record["address"], record["psc"])
            if location is None:
                failed_locations.append(self._build_failed_location_entry(record))
                continue
            point = self._build_point_from_record(record, location)
            refreshed_points.append(point)

        self.set_failed_locations(path, failed_locations)
        self.set_cached_points(path, refreshed_points)
        return refreshed_points, failed_locations

    def is_map_current_for_file(
        self,
        path: Path,
        selected_obor_codes: list[str] | None = None,
        selected_priorities: list[str] | None = None,
    ) -> bool:
        if not MAP_FILE.exists():
            return False
        displayed_codes = self.map_meta.get("displayed_obor_codes")
        displayed_codes = self._normalize_selected_filter_values(displayed_codes)
        selected_obor_codes = self._normalize_selected_filter_values(selected_obor_codes)
        displayed_priorities = self.map_meta.get("displayed_priorities")
        displayed_priorities = self._normalize_selected_filter_values(displayed_priorities)
        selected_priorities = self._normalize_selected_filter_values(selected_priorities)
        return (
            self.map_meta.get("displayed_file") == path.name
            and self.map_meta.get("data_signature") == self.compute_file_signature(path)
            and displayed_codes == selected_obor_codes
            and displayed_priorities == selected_priorities
        )

    def record_map_current_for_file(
        self,
        path: Path,
        selected_obor_codes: list[str] | None = None,
        selected_priorities: list[str] | None = None,
    ) -> None:
        self.map_meta["displayed_file"] = path.name
        self.map_meta["data_signature"] = self.compute_file_signature(path)
        self.map_meta["displayed_obor_codes"] = self._normalize_selected_filter_values(selected_obor_codes)
        self.map_meta["displayed_priorities"] = self._normalize_selected_filter_values(selected_priorities)
        self._save_map_meta()

    def parse_csv(self, file_path: Path) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        with file_path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return records

            normalized = [cell.strip().lower() for cell in header]
            if "address" in normalized:
                address_index = normalized.index("address")
                psc_index = normalized.index("psc")
                count_index = normalized.index("count")
                kod_index = normalized.index("kod_oboru") if "kod_oboru" in normalized else None
                obor_name_index = normalized.index("obor_nazev") if "obor_nazev" in normalized else None
                priority_index = normalized.index("priorita") if "priorita" in normalized else None
                applicant_first_index = normalized.index("uchazec_jmeno") if "uchazec_jmeno" in normalized else None
                applicant_last_index = normalized.index("uchazec_prijmeni") if "uchazec_prijmeni" in normalized else None
                if obor_name_index is None and "oboro_forma" in normalized:
                    obor_name_index = normalized.index("oboro_forma")
            else:
                address_index = 0
                psc_index = 1
                count_index = 2
                kod_index = 3 if len(header) > 3 else None
                obor_name_index = 4 if len(header) > 4 else None
                priority_index = 5 if len(header) > 5 else None
                applicant_first_index = 6 if len(header) > 6 else None
                applicant_last_index = 7 if len(header) > 7 else None

            for row in reader:
                if not row:
                    continue
                if len(row) <= max(address_index, psc_index, count_index):
                    continue
                if row[address_index].lower() in ("nazev", "název", "address", "adresa"):
                    continue
                address = row[address_index].strip()
                psc = row[psc_index].strip()
                count_text = row[count_index].strip().replace(" ", "")
                try:
                    count_value = int(count_text)
                except ValueError:
                    continue
                if not address:
                    continue
                kod_oboru = row[kod_index].strip() if kod_index is not None and len(row) > kod_index else ""
                obor_nazev = row[obor_name_index].strip() if obor_name_index is not None and len(row) > obor_name_index else ""
                priorita = row[priority_index].strip() if priority_index is not None and len(row) > priority_index else ""
                uchazec_jmeno = row[applicant_first_index].strip() if applicant_first_index is not None and len(row) > applicant_first_index else ""
                uchazec_prijmeni = row[applicant_last_index].strip() if applicant_last_index is not None and len(row) > applicant_last_index else ""
                records.append({
                    "address": address,
                    "psc": psc,
                    "count": count_value,
                    "kod_oboru": kod_oboru,
                    "obor_nazev": obor_nazev,
                    "priorita": priorita,
                    "uchazec_jmeno": uchazec_jmeno,
                    "uchazec_prijmeni": uchazec_prijmeni,
                })
        return records

    def list_obor_options(self, path: Path) -> list[dict[str, Any]]:
        try:
            return self._build_obor_options(self.parse_csv(path))
        except Exception:
            return []

    def list_all_obor_options(self) -> list[dict[str, Any]]:
        all_records: list[dict[str, Any]] = []
        try:
            for filename in list(self.file_index):
                path = self.upload_dir / filename
                if not path.exists():
                    continue
                all_records.extend(self.parse_csv(path))
            return self._build_obor_options(all_records)
        except Exception:
            return []

    def list_priority_options(
        self,
        path: Path,
        selected_obor_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            records = self.parse_csv(path)
            if selected_obor_codes is not None:
                records = [record for record in records if record.get("kod_oboru", "") in selected_obor_codes]
            return self._build_priority_options(records)
        except Exception:
            return []

    def list_all_priority_options(
        self,
        selected_obor_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        all_records: list[dict[str, Any]] = []
        try:
            for filename in list(self.file_index):
                path = self.upload_dir / filename
                if not path.exists():
                    continue
                all_records.extend(self.parse_csv(path))
                if selected_obor_codes is not None:
                    all_records = [record for record in all_records if record.get("kod_oboru", "") in selected_obor_codes]
            return self._build_priority_options(all_records)
        except Exception:
            return []

    def _build_obor_options(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        obory: dict[str, dict[str, Any]] = {}
        for record in records:
            code = record.get("kod_oboru", "").strip()
            if not code:
                continue
            option = obory.setdefault(code, {"code": code, "name": "", "count": 0})
            if not option["name"] and record.get("obor_nazev"):
                option["name"] = record["obor_nazev"].strip()
            option["count"] += int(record.get("count", 0) or 0)
        return sorted(obory.values(), key=lambda item: item["code"])

    def _build_priority_options(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        priorities: dict[str, dict[str, Any]] = {}
        for record in records:
            value = str(record.get("priorita", "") or "").strip()
            option = priorities.setdefault(value, {"value": value, "count": 0})
            option["count"] += int(record.get("count", 0) or 0)

        def _sort_key(item: dict[str, Any]) -> tuple[int, int | str]:
            value = str(item.get("value", "") or "").strip()
            if value.isdigit():
                return (0, int(value))
            if not value:
                return (2, "")
            return (1, value)

        return sorted(priorities.values(), key=_sort_key)

    def lookup_location(self, address: str, psc: str) -> tuple[float, float] | None:
        requested_psc = self._normalize_postal_code(psc) or self._extract_postal_code(address)
        key = self._location_cache_key(address, requested_psc)
        alias_location = self._resolve_home_school_alias_location(address, psc)
        if alias_location is not None:
            self.location_cache[key] = alias_location
            self._save_cache()
            return alias_location

        if key in self.location_cache:
            return tuple(self.location_cache[key])

        queries: list[str] = []
        address_text = str(address or "").strip()
        if requested_psc:
            queries.append(f"{address_text}, {requested_psc}, Czech Republic")
            for street in sorted(self._address_street_candidates(address_text)):
                queries.append(f"{street}, {requested_psc}, Czech Republic")
            queries.append(f"{requested_psc}, Czech Republic")
        queries.append(f"{address_text}, Czech Republic")

        unique_queries: list[str] = []
        seen_queries: set[str] = set()
        for query in queries:
            normalized_query = query.strip().lower()
            if not normalized_query or normalized_query in seen_queries:
                continue
            seen_queries.add(normalized_query)
            unique_queries.append(query)

        location = None
        for query in unique_queries:
            try:
                location = self.geocode(query, exactly_one=True, timeout=10)
            except Exception:
                location = None
            if location is not None and self._location_matches_postal_code(location, requested_psc):
                break
            location = None

        if location is not None:
            coords = (location.latitude, location.longitude)
            self.location_cache[key] = coords
            self._save_cache()
            return coords

        return None

    def lookup_query(self, query: str) -> tuple[float, float] | None:
        key = query.strip().lower()
        if key in self.location_cache:
            return tuple(self.location_cache[key])

        full_query = query if "," in query else f"{query}, Czech Republic"
        try:
            location = self.geocode(full_query, exactly_one=True, timeout=10)
        except Exception:
            location = None

        if location is not None:
            coords = (location.latitude, location.longitude)
            self.location_cache[key] = coords
            self._save_cache()
            return coords

        return None

    def compute_farthest_school(self, points: list[dict[str, Any]]) -> tuple[dict[str, Any], float] | None:
        if not self.home_school_address:
            return None
        home_location = self.lookup_query(self.home_school_address)
        if home_location is None:
            return None

        farthest_point = None
        farthest_distance = 0.0
        for point in points:
            distance_km = geodesic(home_location, (point["lat"], point["lng"])) .km
            if distance_km > farthest_distance:
                farthest_distance = distance_km
                farthest_point = point

        return (farthest_point, farthest_distance) if farthest_point else None

    def compute_within_school_distance(self, points: list[dict[str, Any]], max_km: float = 20.0) -> tuple[int, float] | None:
        if not self.home_school_address:
            return None
        home_location = self.lookup_query(self.home_school_address)
        if home_location is None:
            return None

        total_count = sum(point["count"] for point in points)
        if total_count == 0:
            return (0, 0.0)

        within_count = sum(
            point["count"]
            for point in points
            if geodesic(home_location, (point["lat"], point["lng"])) .km <= max_km
        )
        percent = (within_count / total_count) * 100.0 if total_count else 0.0
        return (within_count, percent)

    def collect_points(self) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for filename in list(self.file_index):
            path = self.upload_dir / filename
            if not path.exists():
                continue
            cached_points = self.get_cached_points(path)
            if cached_points is not None and not self.should_refresh_points_cache(path):
                points.extend(cached_points)
                continue
            records = self.parse_csv(path)
            file_points, _ = self.refresh_cached_points_from_records(path, records)
            points.extend(file_points)
        return points

    def build_map(
        self,
        points: list[dict[str, Any]],
        source_file: Path | None = None,
        selected_obor_codes: list[str] | None = None,
        selected_priorities: list[str] | None = None,
    ) -> str:
        center = [49.8, 15.5]
        m = Map(location=center, zoom_start=7, tiles="OpenStreetMap")
        icon_create_function = """function(cluster) {
 var markers = cluster.getAllChildMarkers();
 var sum = 0;
 for (var i = 0; i < markers.length; i++) {
   sum += Number(markers[i].options.count || 1);
 }
 return L.divIcon({
   html: '<div style="background:#1f77b4;color:#fff;display:flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:21px;border:2px solid rgba(255,255,255,0.9);box-shadow:0 0 8px rgba(0,0,0,0.25);">' + sum + '</div>',
   className: 'marker-cluster marker-cluster-custom',
   iconSize: new L.Point(42, 42)
 });
}"""
        cluster = MarkerCluster(
            name="Uchazeči",
            icon_create_function=icon_create_function,
        ).add_to(m)

        bounds: list[tuple[float, float]] = []
        for point in points:
            label = f"{point['address']} ({point['psc']})\nPočet uchazečů: {point['count']}"
            popup = Popup(label.replace("\n", "<br/>"), max_width=320)
            tooltip = f"{point['address']} – {point['count']}"
            icon_html = (
                '<div style="display:flex;align-items:center;justify-content:center;'
                'width:32px;height:32px;border-radius:16px;background:#1f77b4;color:#fff;'
                'font-weight:700;font-size:0.85rem;border:2px solid #ffffff;box-shadow:0 0 4px rgba(0,0,0,0.25);">'
                f'{point["count"]}</div>'
            )
            icon = DivIcon(
                icon_size=(32, 32),
                icon_anchor=(16, 16),
                html=icon_html,
            )
            marker = Marker(
                location=(point['lat'], point['lng']),
                popup=popup,
                tooltip=tooltip,
                icon=icon,
                count=point['count'],
            )
            marker.add_to(cluster)
            bounds.append((point['lat'], point['lng']))

        if self.home_school_address:
            home_location = self.lookup_query(self.home_school_address)
            if home_location is not None:
                overlapping_points = [
                    point for point in points
                    if abs(float(point["lat"]) - float(home_location[0])) < 1e-7
                    and abs(float(point["lng"]) - float(home_location[1])) < 1e-7
                ]
                home_marker_location = home_location
                home_popup_extra = ""
                if overlapping_points:
                    home_marker_location = (home_location[0] + 0.00018, home_location[1] + 0.00018)
                    overlapping_total = sum(int(point.get("count", 0) or 0) for point in overlapping_points)
                    home_popup_extra = (
                        f"<br/><br/>Na stejné adrese je také <strong>{overlapping_total}</strong> uchazečů. "
                        "Červený bod je lehce posunutý, aby modrý bod zůstal vidět."
                    )
                home_popup = Popup(
                    f"{self.home_school_label}<br/>{self.home_school_address}{home_popup_extra}",
                    max_width=300,
                )
                home_icon = Icon(color="red", icon="home", prefix="fa")
                Marker(
                    location=home_marker_location,
                    popup=home_popup,
                    tooltip=self.home_school_label,
                    icon=home_icon,
                ).add_to(m)
                bounds.append(home_location)

        if len(bounds) > 1:
            m.fit_bounds(bounds, padding=(30, 30))
        elif len(bounds) == 1:
            m.location = bounds[0]
            m.zoom_start = 12

        m.get_root().html.add_child(Element(
            '<div style="position: absolute; bottom: 12px; left: 12px; z-index: 1000; background: rgba(255,255,255,0.9); padding: 6px 10px; border-radius: 8px; font-size: 0.85rem; color: #222; border: 1px solid #d4dbe8;">Mapa ČR s uchazeči. Přibližte pro zobrazení jednotlivých bodů.</div>'
        ))
        m.save(str(MAP_FILE))
        if source_file is not None:
            self.record_map_current_for_file(
                source_file,
                selected_obor_codes=selected_obor_codes,
                selected_priorities=selected_priorities,
            )
        html = MAP_FILE.read_text(encoding="utf-8")
        return html

    def file_count(self) -> int:
        return len([name for name in self.file_index if (self.upload_dir / name).exists()])


class MapBuilderWorker(QObject):
    finished = Signal(bool)
    progress = Signal(str)
    progress_counts = Signal(int, int)
    cache_mode = Signal(str)
    error = Signal(str)
    points_ready = Signal(object)

    def __init__(
        self,
        data: DataStorage,
        selected_path: Path | None = None,
        load_all: bool = False,
        selected_obor_codes: list[str] | None = None,
        selected_priorities: list[str] | None = None,
        force_cache_refresh: bool = False,
    ) -> None:
        super().__init__()
        self.data = data
        self.selected_path = selected_path
        self.load_all = load_all
        self.selected_obor_codes = selected_obor_codes
        self.selected_priorities = selected_priorities
        self.force_cache_refresh = force_cache_refresh
        self._cancelled = False
        self.failed_locations: list[dict[str, Any]] = []

    @Slot()
    def run(self) -> None:
        try:
            if self.data.file_count() == 0:
                self.data.build_map([])
                self.progress.emit("Vytvářím prázdnou mapu...")
                self.finished.emit(True)
                return

            points: list[dict[str, Any]] = []
            if self.load_all:
                self.progress.emit("Načítám všechna data ze všech souborů...")
                self.cache_mode.emit("refresh")
                points = self.data.collect_points()
                if self.selected_obor_codes is not None:
                    points = [point for point in points if point.get("kod_oboru", "") in self.selected_obor_codes]
                if self.selected_priorities is not None:
                    points = [point for point in points if str(point.get("priorita", "") or "").strip() in self.selected_priorities]
                self.data.build_map(
                    points,
                    selected_obor_codes=self.selected_obor_codes,
                    selected_priorities=self.selected_priorities,
                )
                self.points_ready.emit(points)
                self.finished.emit(True)
                return

            if self.selected_path is None or not self.selected_path.exists():
                self.data.build_map([])
                self.progress.emit("Vyberte platný soubor ke zobrazení.")
                self.finished.emit(True)
                return

            all_records = self.data.parse_csv(self.selected_path)
            total = len(all_records)
            if total > 0:
                self.progress_counts.emit(0, total)
            cached_points = self.data.get_cached_points(self.selected_path)
            if cached_points is not None and not self.force_cache_refresh:
                self.failed_locations = self.data.get_failed_locations(self.selected_path)
                self.cache_mode.emit("cache")
                self.progress.emit(f"Načítám uloženou cache pro {self.selected_path.name}...")
                self.progress_counts.emit(total, total)
            else:
                self.cache_mode.emit("refresh")
                def _progress_callback(current: int, maximum: int, stage: str) -> None:
                    if stage == "cached":
                        message = f"Načítám uloženou polohu {current}/{maximum} záznamů..."
                    else:
                        message = f"Geokóduji {current}/{maximum} záznamů..."
                    self.progress.emit(message)
                    self.progress_counts.emit(current, maximum)

                cached_points, self.failed_locations = self.data.refresh_cached_points_from_records(
                    self.selected_path,
                    all_records,
                    progress_callback=_progress_callback,
                )
                self.progress.emit(f"Načítám uloženou cache pro {self.selected_path.name}...")

            if cached_points is None:
                cached_points = []

            if self.selected_obor_codes is not None:
                cached_points = [point for point in cached_points if point.get("kod_oboru", "") in self.selected_obor_codes]
            if self.selected_priorities is not None:
                cached_points = [point for point in cached_points if str(point.get("priorita", "") or "").strip() in self.selected_priorities]
            points.extend(cached_points)

            if self.selected_obor_codes is not None:
                points = [point for point in points if point.get("kod_oboru", "") in self.selected_obor_codes]
            if self.selected_priorities is not None:
                points = [point for point in points if str(point.get("priorita", "") or "").strip() in self.selected_priorities]
            self.data.build_map(
                points,
                self.selected_path,
                selected_obor_codes=self.selected_obor_codes,
                selected_priorities=self.selected_priorities,
            )
            self.points_ready.emit(points)
            self.finished.emit(True)
        except Exception as exc:
            self.error.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self._cancelled = True


class MapWebPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID) -> None:  # noqa: N802
        # Some third-party scripts attempt sessionStorage on local file pages.
        # In QWebEngine this can emit a non-fatal SecurityError to stderr.
        if "sessionStorage" in message and "Access is denied for this document" in message:
            return
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.data = DataStorage()
        self.current_selected_file: str | None = None
        self._suppress_selection_refresh = False
        self.obor_filter_checkboxes: dict[str, QCheckBox] = {}
        self.priority_filter_checkboxes: dict[str, QCheckBox] = {}
        self._all_obory_total_count = 0
        self._all_priorities_total_count = 0
        self._show_all_mode = False
        self._progress_message = ""
        self._progress_current = 0
        self._progress_total = 0
        self._last_cache_mode = ""
        title_suffix = f" — {self.data.home_school_label}" if self.data.home_school_label else ""
        self.setWindowTitle(f"Mapa uchazečů o studium{title_suffix}")
        self.setMinimumSize(1200, 820)
        self._set_window_icon()
        self._init_ui()
        self._load_files()
        self.show_empty_map()

    def _set_window_icon(self) -> None:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        brush = QBrush(QColor("#1f77b4"))
        painter.setBrush(brush)
        painter.setPen(QPen(QColor("#0f4f8a"), 3))
        painter.drawEllipse(8, 8, 48, 48)

        painter.setPen(QPen(QColor("#ffffff"), 4))
        painter.drawLine(32, 16, 32, 48)
        painter.drawLine(20, 32, 44, 32)

        pen = QPen(QColor("#ffffff"), 4)
        painter.setPen(pen)
        painter.drawLine(24, 20, 40, 28)
        painter.drawLine(40, 20, 24, 28)

        painter.end()
        self.setWindowIcon(QIcon(pixmap))

    def show_empty_map(self) -> None:
        self.data.build_map([])
        self.data.map_meta = {}
        self.data._save_map_meta()
        self._show_failed_locations_message([])
        if MAP_FILE.exists():
            self.web_view.load(QUrl.fromLocalFile(str(MAP_FILE.resolve())))
        else:
            self.web_view.setHtml("<html><body><p>Prázdná mapa se nepodařilo načíst.</p></body></html>")
        self.school_info_label.setText(self._build_school_info_text())
        self.set_status("Aplikace je připravena. Importujte DiPSy soubor a stiskněte Obnovit mapu.")

    def _init_ui(self) -> None:
        main_widget = QWidget()
        self.setCentralWidget(main_widget)

        self.import_dips_button = QPushButton("Import DiPSy souboru")
        self.import_dips_button.clicked.connect(self.import_dips_file)

        self.obor_filter_toggle_button = QPushButton("Filtr oborů [+]")
        self.obor_filter_toggle_button.setCheckable(True)
        self.obor_filter_toggle_button.toggled.connect(self._toggle_obor_filter_visibility)
        self.obor_filter_section = QWidget()
        self.obor_filter_section_layout = QVBoxLayout(self.obor_filter_section)
        self.obor_filter_section_layout.setContentsMargins(0, 0, 0, 0)
        self.obor_filter_section_layout.setSpacing(4)
        self.obor_filter_all_checkbox = QCheckBox("Všechny obory")
        self.obor_filter_all_checkbox.setChecked(True)
        self.obor_filter_all_checkbox.toggled.connect(self._on_obor_filter_all_toggled)
        self.obor_filter_container = QWidget()
        self.obor_filter_layout = QVBoxLayout(self.obor_filter_container)
        self.obor_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.obor_filter_layout.setSpacing(2)
        self.obor_filter_section_layout.addWidget(self.obor_filter_all_checkbox)
        self.obor_filter_section_layout.addWidget(self.obor_filter_container)
        self.obor_filter_section.hide()

        self.priority_filter_toggle_button = QPushButton("Filtr priorit [+]")
        self.priority_filter_toggle_button.setCheckable(True)
        self.priority_filter_toggle_button.toggled.connect(self._toggle_priority_filter_visibility)
        self.priority_filter_section = QWidget()
        self.priority_filter_section_layout = QVBoxLayout(self.priority_filter_section)
        self.priority_filter_section_layout.setContentsMargins(0, 0, 0, 0)
        self.priority_filter_section_layout.setSpacing(4)
        self.priority_filter_all_checkbox = QCheckBox("Všechny priority")
        self.priority_filter_all_checkbox.setChecked(True)
        self.priority_filter_all_checkbox.toggled.connect(self._on_priority_filter_all_toggled)
        self.priority_filter_container = QWidget()
        self.priority_filter_layout = QVBoxLayout(self.priority_filter_container)
        self.priority_filter_layout.setContentsMargins(0, 0, 0, 0)
        self.priority_filter_layout.setSpacing(2)
        self.priority_filter_section_layout.addWidget(self.priority_filter_all_checkbox)
        self.priority_filter_section_layout.addWidget(self.priority_filter_container)
        self.priority_filter_section.hide()

        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.file_list.currentItemChanged.connect(self._on_current_item_changed)
        self.file_list.itemClicked.connect(self._on_file_clicked)
        self.file_list.itemActivated.connect(self._on_file_double_clicked)

        self.delete_button = QPushButton("Smazat soubor")
        self.delete_button.clicked.connect(self.delete_selected_file)

        self.show_all_button = QPushButton("Zobrazit vše")
        self.show_all_button.clicked.connect(self.show_all_files)

        self.refresh_button = QPushButton("Obnovit")
        self.refresh_button.clicked.connect(self.refresh_state)

        self.report_button = QPushButton("Generovat report")
        self.report_button.clicked.connect(self.generate_report)

        self.about_button = QPushButton("O programu")
        self.about_button.clicked.connect(self.show_about_dialog)

        self.failed_locations_toggle_button = QPushButton("Negeokódované řádky (0) [+]")
        self.failed_locations_toggle_button.setCheckable(True)
        self.failed_locations_toggle_button.setEnabled(False)
        self.failed_locations_toggle_button.toggled.connect(self._toggle_failed_locations_visibility)

        self.status_label = QLabel("Aplikace je připravena.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "color:#173c8f; background:#eef5ff; border:1px solid #c9ddff; padding:8px; border-radius:8px;"
        )

        self.failed_locations_list = QListWidget()
        self.failed_locations_list.setSelectionMode(QListWidget.NoSelection)
        self.failed_locations_list.setStyleSheet(
            "color:#333333; background:#fff7f7; border:1px solid #efd0d0; border-radius:8px;"
        )
        self.failed_locations_list.setMaximumHeight(180)
        self.failed_locations_list.hide()

        action_buttons_widget = QWidget()
        action_buttons_layout = QVBoxLayout(action_buttons_widget)
        action_buttons_layout.setContentsMargins(0, 0, 0, 0)
        action_buttons_layout.setSpacing(6)

        primary_buttons_row = QWidget()
        primary_buttons_layout = QHBoxLayout(primary_buttons_row)
        primary_buttons_layout.setContentsMargins(0, 0, 0, 0)
        primary_buttons_layout.setSpacing(6)
        primary_buttons_layout.addWidget(self.delete_button)
        primary_buttons_layout.addWidget(self.show_all_button)
        primary_buttons_layout.addWidget(self.refresh_button)

        self.report_button.setMinimumHeight(36)

        action_buttons_layout.addWidget(primary_buttons_row)
        action_buttons_layout.addWidget(self.report_button)
        action_buttons_layout.addWidget(self.about_button)

        side_layout = QVBoxLayout()
        self.school_info_label = QLabel(self._build_school_info_text())
        self.school_info_label.setWordWrap(True)
        self.school_info_label.setStyleSheet("color:#2d3e50; background:#f5f7fa; border:1px solid #dfe5ef; padding:8px; border-radius:8px; margin-bottom:10px;")
        side_layout.addWidget(self.school_info_label)
        side_layout.addWidget(self.import_dips_button)
        side_layout.addWidget(self.obor_filter_toggle_button)
        side_layout.addWidget(self.obor_filter_section)
        side_layout.addWidget(self.priority_filter_toggle_button)
        side_layout.addWidget(self.priority_filter_section)
        side_layout.addWidget(QLabel("Uložené soubory (Ctrl+klik pro více souborů):"))
        side_layout.addWidget(self.file_list)
        side_layout.addWidget(action_buttons_widget)
        side_layout.addWidget(self.failed_locations_toggle_button)
        side_layout.addWidget(self.failed_locations_list)
        side_layout.addWidget(self.status_label)
        side_layout.addStretch(1)

        footer_label = QLabel(f"Verze: {APP_VERSION} | {APP_YEAR}")
        footer_label.setWordWrap(True)
        footer_label.setStyleSheet("color:#666666; font-size:11px; margin-top:10px;")
        side_layout.addWidget(footer_label)

        side_widget = QWidget()
        side_widget.setLayout(side_layout)
        side_widget.setMaximumWidth(380)

        profile = QWebEngineProfile.defaultProfile()
        storage_path = self.data.storage_dir / "webengine_storage"
        cache_path = self.data.storage_dir / "webengine_cache"
        storage_path.mkdir(parents=True, exist_ok=True)
        cache_path.mkdir(parents=True, exist_ok=True)
        profile.setPersistentStoragePath(str(storage_path))
        profile.setCachePath(str(cache_path))
        profile.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
        profile.setHttpCacheType(QWebEngineProfile.DiskHttpCache)

        self.web_view = QWebEngineView()
        self.web_view.setPage(MapWebPage(profile, self.web_view))
        self.web_view.settings().setAttribute(QWebEngineSettings.JavascriptEnabled, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        self.web_view.settings().setAttribute(QWebEngineSettings.PluginsEnabled, True)
        self.web_view.loadFinished.connect(self._on_web_view_load_finished)

        main_layout = QHBoxLayout()
        main_layout.addWidget(side_widget)
        main_layout.addWidget(self.web_view, 1)
        main_widget.setLayout(main_layout)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _version_sort_key(self, value: str) -> tuple[int, ...]:
        normalized = value.strip().lower()
        if normalized.startswith("v"):
            normalized = normalized[1:]
        parts = [int(part) for part in re.findall(r"\d+", normalized)]
        return tuple(parts)

    def _repo_slug_from_url(self) -> str | None:
        parsed = urllib.parse.urlparse(APP_GITHUB_URL)
        path = parsed.path.strip("/")
        pieces = [item for item in path.split("/") if item]
        if len(pieces) < 2:
            return None
        return f"{pieces[0]}/{pieces[1]}"

    def _check_github_update(self) -> dict[str, Any]:
        slug = self._repo_slug_from_url()
        if not slug:
            return {
                "has_update": False,
                "status": "Kontrola aktualizace není dostupná (neplatná URL repozitáře).",
                "latest_version": None,
                "download_url": None,
                "release_url": APP_GITHUB_URL,
            }

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "mapa-uchazecu-update-check",
        }
        latest_api = f"https://api.github.com/repos/{slug}/releases/latest"
        tags_api = f"https://api.github.com/repos/{slug}/tags?per_page=1"

        latest_version: str | None = None
        download_url: str | None = None
        release_url = APP_GITHUB_URL

        try:
            req = urllib.request.Request(latest_api, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            tag_name = str(payload.get("tag_name") or "").strip()
            latest_version = tag_name.lstrip("vV") if tag_name else None
            release_url = str(payload.get("html_url") or APP_GITHUB_URL)

            assets = payload.get("assets") or []
            if assets and isinstance(assets, list):
                first_asset = assets[0] or {}
                download_url = str(first_asset.get("browser_download_url") or "").strip() or None

            if not download_url:
                zipball = str(payload.get("zipball_url") or "").strip()
                download_url = zipball or None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                try:
                    req = urllib.request.Request(tags_api, headers=headers)
                    with urllib.request.urlopen(req, timeout=10) as response:
                        tags_payload = json.loads(response.read().decode("utf-8"))
                    if isinstance(tags_payload, list) and tags_payload:
                        first_tag = tags_payload[0] or {}
                        tag_name = str(first_tag.get("name") or "").strip()
                        latest_version = tag_name.lstrip("vV") if tag_name else None
                        release_url = f"https://github.com/{slug}/tags"
                        download_url = f"https://github.com/{slug}/archive/refs/tags/{tag_name}.zip" if tag_name else None
                except Exception:
                    return {
                        "has_update": False,
                        "status": "Kontrolu aktualizace se nepodařilo dokončit.",
                        "latest_version": None,
                        "download_url": None,
                        "release_url": APP_GITHUB_URL,
                    }
            else:
                return {
                    "has_update": False,
                    "status": "Kontrolu aktualizace se nepodařilo dokončit.",
                    "latest_version": None,
                    "download_url": None,
                    "release_url": APP_GITHUB_URL,
                }
        except Exception:
            return {
                "has_update": False,
                "status": "Kontrolu aktualizace se nepodařilo dokončit.",
                "latest_version": None,
                "download_url": None,
                "release_url": APP_GITHUB_URL,
            }

        if not latest_version:
            return {
                "has_update": False,
                "status": "Verzi na GitHubu se nepodařilo zjistit.",
                "latest_version": None,
                "download_url": download_url,
                "release_url": release_url,
            }

        local_key = self._version_sort_key(APP_VERSION)
        remote_key = self._version_sort_key(latest_version)
        has_update = remote_key > local_key
        if has_update:
            status = f"Je dostupná novější verze: {latest_version}"
        else:
            status = "Používáte nejnovější verzi."

        return {
            "has_update": has_update,
            "status": status,
            "latest_version": latest_version,
            "download_url": download_url,
            "release_url": release_url,
        }

    def _download_update_file(self, url: str, latest_version: str | None) -> Path:
        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        safe_version = re.sub(r"[^0-9A-Za-z._-]", "_", (latest_version or "latest"))
        filename = f"update_{safe_version}.zip"
        target = UPDATES_DIR / filename
        request = urllib.request.Request(url, headers={"User-Agent": "mapa-uchazecu-updater"})
        with urllib.request.urlopen(request, timeout=30) as response:
            target.write_bytes(response.read())
        return target

    def show_about_dialog(self) -> None:
        update_info = self._check_github_update()
        update_status = html.escape(str(update_info.get("status") or ""))

        box = QMessageBox(self)
        box.setWindowTitle("O programu")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.RichText)
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        box.setText(
            "Tato aplikace je <strong>open source</strong>.<br/><br/>"
            "Program \"Mapa uchazečů o studium\" slouží k vizualizaci přihlášek uchazečů o studium ze systému DiPSy.<br/><br/>"
            "Aplikace byla vytvořena s pomocí AI.<br/>"
            "Podpis AI: <strong>GitHub Copilot</strong><br/><br/>"
            "Autor: <strong>Michal Šiman</strong> - <a href=\"https://www.ok1sim.cz\">www.ok1sim.cz</a><br/>"
            f"Verze: <strong>{APP_VERSION}</strong> ({APP_YEAR})<br/>"
            f"GitHub repozitář: <a href=\"{APP_GITHUB_URL}\">{APP_GITHUB_URL}</a><br/>"
            f"Aktualizace: <strong>{update_status}</strong>"
        )
        box.setStandardButtons(QMessageBox.Ok)
        update_button = None
        if update_info.get("has_update") and update_info.get("download_url"):
            update_button = box.addButton("Stáhnout aktualizaci", QMessageBox.ActionRole)
        elif update_info.get("has_update") and update_info.get("release_url"):
            update_button = box.addButton("Otevřít aktualizaci na GitHubu", QMessageBox.ActionRole)

        box.exec()

        if box.clickedButton() is not update_button:
            return

        download_url = str(update_info.get("download_url") or "").strip()
        release_url = str(update_info.get("release_url") or APP_GITHUB_URL).strip()

        if download_url:
            try:
                downloaded_file = self._download_update_file(download_url, update_info.get("latest_version"))
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(downloaded_file.resolve())))
                self.set_status(f"Aktualizace stažena: {downloaded_file.name}")
                QMessageBox.information(
                    self,
                    "Aktualizace stažena",
                    f"Soubor s aktualizací byl uložen do {downloaded_file.parent}.\n\n"
                    "Po zavření aplikace lze aktualizaci rozbalit/instalovat.",
                )
            except Exception as exc:
                QMessageBox.warning(self, "Chyba", f"Aktualizaci se nepodařilo stáhnout: {exc}")
                self.set_status("Stažení aktualizace selhalo.")
            return

        QDesktopServices.openUrl(QUrl(release_url))
        self.set_status("Otevřena stránka aktualizace na GitHubu.")

    def _toggle_failed_locations_visibility(self, checked: bool) -> None:
        self.failed_locations_list.setVisible(checked)
        base = self.failed_locations_toggle_button.text().split("(", 1)[0].strip()
        marker = "[-]" if checked else "[+]"
        if not base:
            base = "Negeokódované řádky"
        count_part = ""
        text = self.failed_locations_toggle_button.text()
        if "(" in text and ")" in text:
            count_part = text[text.find("("):text.find(")") + 1]
        self.failed_locations_toggle_button.setText(f"{base} {count_part} {marker}".replace("  ", " ").strip())

    def _toggle_obor_filter_visibility(self, checked: bool) -> None:
        self.obor_filter_section.setVisible(checked and bool(self.obor_filter_checkboxes))
        self.obor_filter_toggle_button.setText("Filtr oborů [-]" if checked else "Filtr oborů [+]")

    def _toggle_priority_filter_visibility(self, checked: bool) -> None:
        self.priority_filter_section.setVisible(checked and bool(self.priority_filter_checkboxes))
        self.priority_filter_toggle_button.setText("Filtr priorit [-]" if checked else "Filtr priorit [+]")

    def _on_file_selected(self, item) -> None:
        if item is None or " — " not in item.text():
            self.current_selected_file = None
            self._update_filter_ui()
            return
        self.current_selected_file = item.text().split(" — ")[0]
        self._update_filter_ui()

    def _selected_obor_codes_for_current_file(self) -> list[str] | None:
        if not self.obor_filter_checkboxes:
            return None
        selected_codes = [code for code, checkbox in self.obor_filter_checkboxes.items() if checkbox.isChecked()]
        if len(selected_codes) == len(self.obor_filter_checkboxes):
            return None
        return selected_codes

    def _selected_priorities_for_current_file(self) -> list[str] | None:
        if not self.priority_filter_checkboxes:
            return None
        selected_priorities = [value for value, checkbox in self.priority_filter_checkboxes.items() if checkbox.isChecked()]
        if len(selected_priorities) == len(self.priority_filter_checkboxes):
            return None
        return selected_priorities

    def _clear_filter_checkboxes(self, checkboxes: dict[str, QCheckBox], layout: QVBoxLayout) -> None:
        for key in list(checkboxes):
            checkbox = checkboxes.pop(key)
            checkbox.deleteLater()
        layout.invalidate()

    def _set_filter_all_checkbox_state(self, checkbox: QCheckBox, checked: bool, text: str) -> None:
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.setText(text)
        checkbox.blockSignals(False)

    def _update_filter_ui(self) -> None:
        self._update_obor_filter_ui()
        self._update_priority_filter_ui()

    def _update_obor_filter_ui(self) -> None:
        selected_path = self._selected_file_path()
        self._set_filter_all_checkbox_state(self.obor_filter_all_checkbox, True, "Všechny obory")
        self._all_obory_total_count = 0
        self._clear_filter_checkboxes(self.obor_filter_checkboxes, self.obor_filter_layout)

        if self._show_all_mode:
            obor_options = self.data.list_all_obor_options()
        elif selected_path is None:
            self.obor_filter_section.hide()
            self.obor_filter_toggle_button.hide()
            return
        else:
            obor_options = self.data.list_obor_options(selected_path)
        if not obor_options:
            self.obor_filter_section.hide()
            self.obor_filter_toggle_button.hide()
            return

        self.obor_filter_toggle_button.show()
        self.obor_filter_section.setVisible(self.obor_filter_toggle_button.isChecked())
        total_count = sum(int(option.get("count", 0) or 0) for option in obor_options)
        self._all_obory_total_count = total_count
        self.obor_filter_all_checkbox.setText(f"Všechny obory ({total_count})")
        for option in obor_options:
            code = option["code"]
            name = option.get("name", "")
            count = option.get("count", 0)
            label = code
            if name:
                label = f"{code} - {name}"
            label = f"{label} ({count})"
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._on_obor_filter_checkbox_toggled)
            self.obor_filter_checkboxes[code] = checkbox
            self.obor_filter_layout.addWidget(checkbox)

    def _update_priority_filter_ui(self) -> None:
        selected_path = self._selected_file_path()
        selected_obor_codes = self._selected_obor_codes_for_current_file()
        selected_priorities = self._selected_priorities_for_current_file()
        self._set_filter_all_checkbox_state(self.priority_filter_all_checkbox, True, "Všechny priority")
        self._all_priorities_total_count = 0
        self._clear_filter_checkboxes(self.priority_filter_checkboxes, self.priority_filter_layout)

        if self._show_all_mode:
            priority_options = self.data.list_all_priority_options(selected_obor_codes=selected_obor_codes)
        elif selected_path is None:
            self.priority_filter_section.hide()
            self.priority_filter_toggle_button.hide()
            return
        else:
            priority_options = self.data.list_priority_options(selected_path, selected_obor_codes=selected_obor_codes)
        if not priority_options:
            self.priority_filter_section.hide()
            self.priority_filter_toggle_button.hide()
            return

        self.priority_filter_toggle_button.show()
        self.priority_filter_section.setVisible(self.priority_filter_toggle_button.isChecked())
        total_count = sum(int(option.get("count", 0) or 0) for option in priority_options)
        self._all_priorities_total_count = total_count
        self.priority_filter_all_checkbox.setText(f"Všechny priority ({total_count})")
        for option in priority_options:
            value = str(option.get("value", "") or "").strip()
            count = int(option.get("count", 0) or 0)
            label = value if value else "Neuvedena"
            checkbox = QCheckBox(f"{label} ({count})")
            checkbox.setChecked(selected_priorities is None or value in selected_priorities)
            checkbox.toggled.connect(self._on_priority_filter_checkbox_toggled)
            self.priority_filter_checkboxes[value] = checkbox
            self.priority_filter_layout.addWidget(checkbox)

        checked_count = sum(1 for checkbox in self.priority_filter_checkboxes.values() if checkbox.isChecked())
        self._set_filter_all_checkbox_state(
            self.priority_filter_all_checkbox,
            checked_count == len(self.priority_filter_checkboxes),
            f"Všechny priority ({total_count})",
        )

    def _on_obor_filter_all_toggled(self, checked: bool) -> None:
        for checkbox in self.obor_filter_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self._update_priority_filter_ui()
        self.refresh_state()

    def _on_obor_filter_checkbox_toggled(self, checked: bool) -> None:
        if not self.obor_filter_checkboxes:
            return
        checked_count = sum(1 for checkbox in self.obor_filter_checkboxes.values() if checkbox.isChecked())
        if checked_count == len(self.obor_filter_checkboxes):
            self.obor_filter_all_checkbox.blockSignals(True)
            self.obor_filter_all_checkbox.setChecked(True)
            self.obor_filter_all_checkbox.blockSignals(False)
        else:
            self.obor_filter_all_checkbox.blockSignals(True)
            self.obor_filter_all_checkbox.setChecked(False)
            self.obor_filter_all_checkbox.blockSignals(False)
        self._update_priority_filter_ui()
        self.refresh_state()

    def _on_priority_filter_all_toggled(self, checked: bool) -> None:
        for checkbox in self.priority_filter_checkboxes.values():
            checkbox.blockSignals(True)
            checkbox.setChecked(checked)
            checkbox.blockSignals(False)
        self.refresh_state()

    def _on_priority_filter_checkbox_toggled(self, checked: bool) -> None:
        if not self.priority_filter_checkboxes:
            return
        checked_count = sum(1 for checkbox in self.priority_filter_checkboxes.values() if checkbox.isChecked())
        if checked_count == len(self.priority_filter_checkboxes):
            self.priority_filter_all_checkbox.blockSignals(True)
            self.priority_filter_all_checkbox.setChecked(True)
            self.priority_filter_all_checkbox.blockSignals(False)
        else:
            self.priority_filter_all_checkbox.blockSignals(True)
            self.priority_filter_all_checkbox.setChecked(False)
            self.priority_filter_all_checkbox.blockSignals(False)
        self.refresh_state()

    def _build_school_info_text(self) -> str:
        if self.data.home_school_label and self.data.home_school_address:
            return f"Domácí škola: <strong>{self.data.home_school_label}</strong><br/>{self.data.home_school_address}"
        if self.data.home_school_address:
            return f"Domácí škola: {self.data.home_school_address}"
        return f"Domácí škola není nastavena v {CONFIG_FILE.name}."

    def _on_current_item_changed(self, current, previous) -> None:
        if self._suppress_selection_refresh:
            return
        self._on_file_selected(current)
        if current is not None:
            self._show_all_mode = False
            self.refresh_state()

    def _on_file_clicked(self, item) -> None:
        self.file_list.setCurrentItem(item)
        self._on_file_selected(item)
        self._show_all_mode = False
        self.refresh_state()

    def _on_file_double_clicked(self, item) -> None:
        self.file_list.setCurrentItem(item)
        self._on_file_selected(item)
        self._show_all_mode = False
        self.refresh_state()

    def _selected_file_paths_for_report(self) -> list[Path]:
        paths: list[Path] = []
        seen: set[str] = set()

        for item in self.file_list.selectedItems():
            text = item.text()
            if " — " not in text:
                continue
            filename = text.split(" — ")[0]
            if filename in seen:
                continue
            path = self.data.upload_dir / filename
            if path.exists():
                paths.append(path)
                seen.add(filename)

        if paths:
            return paths
        if self._show_all_mode:
            return self.data.get_existing_upload_paths()

        selected_path = self._selected_file_path()
        if selected_path is not None:
            return [selected_path]

        if self.current_selected_file:
            fallback_path = self.data.upload_dir / self.current_selected_file
            if fallback_path.exists():
                return [fallback_path]

        return []

    def _build_report_html(self, target_path: Path, selected_paths: list[Path]) -> None:
        total_applicants = 0
        obor_counts: dict[str, int] = defaultdict(int)
        priority_counts: dict[str, int] = defaultdict(int)
        school_counts: dict[str, int] = defaultdict(int)
        school_with_psc_counts: dict[tuple[str, str], int] = defaultdict(int)
        foreign_school_applicants = 0

        def _is_foreign_school_address(address: str) -> bool:
            normalized = unicodedata.normalize("NFKD", address.lower())
            ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
            return "zahranici" in ascii_only

        for path in selected_paths:
            records = self.data.parse_csv(path)
            for record in records:
                count = int(record.get("count", 0) or 0)
                total_applicants += count

                code = str(record.get("kod_oboru", "") or "").strip()
                name = str(record.get("obor_nazev", "") or "").strip()
                if code and name:
                    obor_label = f"{code} - {name}"
                elif code:
                    obor_label = code
                elif name:
                    obor_label = name
                else:
                    obor_label = "Neuvedený obor"
                obor_counts[obor_label] += count

                priority = str(record.get("priorita", "") or "").strip()
                priority_label = priority if priority else "Neuvedena"
                priority_counts[priority_label] += count

                school = str(record.get("address", "") or "").strip()
                psc = str(record.get("psc", "") or "").strip()
                if school:
                    school_counts[school] += count
                    school_with_psc_counts[(school, psc)] += count
                    if _is_foreign_school_address(school):
                        foreign_school_applicants += count

        sorted_obory = sorted(obor_counts.items(), key=lambda item: (-item[1], item[0].lower()))

        def _priority_sort_key(item: tuple[str, int]) -> tuple[int, int | str]:
            label = item[0].strip()
            if label.isdigit():
                return (0, int(label))
            if label.lower() == "neuvedena":
                return (2, label)
            return (1, label.lower())

        sorted_priorities = sorted(priority_counts.items(), key=_priority_sort_key)
        sorted_schools = sorted(school_counts.items(), key=lambda item: (-item[1], item[0].lower()))
        top_schools_by_count = sorted_schools[:3]

        unique_school_count = len(school_counts)
        average_per_school = (total_applicants / unique_school_count) if unique_school_count else 0.0

        within_20_count = None
        within_20_percent = None
        top_distance_schools: list[tuple[str, str, float]] = []
        home_location = self.data.lookup_query(self.data.home_school_address) if self.data.home_school_address else None
        if home_location is not None:
            distance_rows: list[tuple[str, str, float, int]] = []
            for (school, psc), count in school_with_psc_counts.items():
                location = self.data.lookup_location(school, psc)
                if location is None:
                    continue
                distance_km = geodesic(home_location, location).km
                distance_rows.append((school, psc, distance_km, count))

            if distance_rows:
                within_20 = sum(row[3] for row in distance_rows if row[2] <= 20.0)
                within_20_count = within_20
                within_20_percent = (within_20 / total_applicants * 100.0) if total_applicants else 0.0
                farthest_rows = sorted(distance_rows, key=lambda row: row[2], reverse=True)[:3]
                top_distance_schools = [(row[0], row[1], row[2]) for row in farthest_rows]

        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        hostname = socket.gethostname()
        school_label = self.data.home_school_label.strip() if self.data.home_school_label else "Neuvedená škola"

        def _esc(value: Any) -> str:
            return html.escape(str(value))

        def _render_list(items: list[str]) -> str:
            if not items:
                return "<li>Bez dat</li>"
            return "".join(f"<li>{item}</li>" for item in items)

        file_items = _render_list([_esc(path.name) for path in selected_paths])
        top_school_items = _render_list([f"{_esc(school)} ({count})" for school, count in top_schools_by_count])

        if top_distance_schools:
            distance_items = _render_list(
                [
                    f"{_esc(school)} ({distance_km:.1f} km)"
                    for school, psc, distance_km in top_distance_schools
                ]
            )
        elif self.data.home_school_address:
            distance_items = "<li>Nelze určit vzdálenost pro žádnou školu</li>"
        else:
            distance_items = "<li>Domácí škola není nastavena</li>"

        obory_items = _render_list([f"{_esc(label)} ({count})" for label, count in sorted_obory])
        priority_items = _render_list([f"{_esc(label)} ({count})" for label, count in sorted_priorities])
        schools_items = _render_list([f"{_esc(school)} ({count})" for school, count in sorted_schools])

        within_20_html = ""
        if within_20_count is not None and within_20_percent is not None:
            within_20_html = (
                f"<p><strong>Uchazečů do 20 km od domácí školy:</strong> "
                f"{within_20_count} ({within_20_percent:.1f} %)</p>"
            )

        html_content = f"""<!DOCTYPE html>
<html lang=\"cs\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Report uchazečů</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; color: #1c2331; background: #f4f7fb; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; background: #ffffff; border: 1px solid #dbe4f0; border-radius: 12px; padding: 22px; }}
    h1 {{ margin: 0 0 6px; color: #173c8f; }}
    h2 {{ margin: 22px 0 8px; color: #173c8f; font-size: 1.1rem; }}
    p {{ margin: 6px 0; }}
    ul {{ margin: 8px 0 0 0; padding-left: 20px; }}
    li {{ margin: 3px 0; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>Report uchazečů o studium</h1>
    <p><strong>Škola:</strong> {_esc(school_label)}</p>
    <p><strong>Vygenerováno:</strong> {_esc(timestamp)}</p>
    <p><strong>Počítač:</strong> {_esc(hostname)}</p>

    <h2>Soubory</h2>
    <ul>{file_items}</ul>

    <h2>Souhrn</h2>
    <p><strong>Celkový počet uchazečů:</strong> {total_applicants}</p>
    <p><strong>Počet unikátních škol:</strong> {unique_school_count}</p>
    <p><strong>Průměrný počet uchazečů na školu:</strong> {average_per_school:.1f}</p>
    {within_20_html}

    <h2>Top 3 školy podle počtu uchazečů</h2>
    <ul>{top_school_items}</ul>

    <h2>Top 3 nejvzdálenější školy</h2>
    <ul>{distance_items}</ul>

    <h2>Obory (počet uchazečů)</h2>
    <ul>{obory_items}</ul>

    <h2>Priority (počet uchazečů)</h2>
    <ul>{priority_items}</ul>

    <h2>Školy (unikátní, sestupně)</h2>
    <ul>{schools_items}</ul>

    <h2>Zahraniční školy</h2>
    <p><strong>Počet uchazečů ze zahraniční školy:</strong> {foreign_school_applicants}</p>
  </div>
</body>
</html>
"""

        target_path.write_text(html_content, encoding="utf-8")

    def generate_report(self) -> None:
        selected_paths = self._selected_file_paths_for_report()
        if not selected_paths:
            self.set_status("Pro report nejprve vyberte alespoň jeden soubor.")
            return

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_report_path = REPORTS_DIR / f"report_uchazeci_{timestamp}.html"

        try:
            self._build_report_html(html_report_path, selected_paths)
        except Exception as exc:
            QMessageBox.warning(self, "Chyba", f"HTML report se nepodařilo vygenerovat: {exc}")
            self.set_status("Generování reportu selhalo.")
            return

        html_opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(html_report_path.resolve())))

        if html_opened:
            self.set_status(f"HTML report vygenerován: {html_report_path.name}")
        else:
            self.set_status(
                f"HTML report byl vygenerován, ale nepodařilo se otevřít: {html_report_path.name}"
            )

    def import_dips_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Vyberte DiPSy CSV soubor",
            str(BASE_DIR),
            "CSV soubory (*.csv);;Všechny soubory (*)",
        )
        if not file_path:
            self.set_status("Žádný DiPSy soubor nebyl vybrán.")
            return

        try:
            summary_csv, imported_count, ignored_count = self._convert_dips_csv_to_summary(Path(file_path))
            uploaded = self.data.add_uploaded_file(summary_csv)
            self.set_status(f"DiPSy soubor byl importován jako {uploaded.name}.")
            self._load_files()
            self._select_file_in_list(uploaded.name)
            self.refresh_state()
            if ignored_count > 0:
                QMessageBox.information(
                    self,
                    "Import DiPSy dokončen",
                    f"Import dokončen: importováno {imported_count} řádků, ignorováno {ignored_count} řádků se stavem 'zrusena'.",
                    QMessageBox.Ok,
                )
        except Exception as exc:
            self.set_status(f"Chyba při importu DiPSy souboru: {exc}")

    def _convert_dips_csv_to_summary(self, dips_path: Path) -> tuple[Path, int, int]:
        with dips_path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f, delimiter=";")
            try:
                header = next(reader)
            except StopIteration:
                raise ValueError("DiPSy soubor je prázdný.")

            normalized = [cell.strip().lower() for cell in header]
            school_index = normalized.index("zakladni_skola") if "zakladni_skola" in normalized else None
            middle_school_index = normalized.index("stredni_skola") if "stredni_skola" in normalized else None
            if school_index is None and middle_school_index is None:
                raise ValueError("DiPSy soubor neobsahuje sloupec zakladni_skola ani stredni_skola.")

            stav_index = normalized.index("stav") if "stav" in normalized else None
            kod_oboru_index = normalized.index("kod_oboru") if "kod_oboru" in normalized else None
            obor_name_index = normalized.index("oboro_forma") if "oboro_forma" in normalized else None
            priority_index = normalized.index("priorita") if "priorita" in normalized else None
            applicant_first_index = normalized.index("uchazec_jmeno") if "uchazec_jmeno" in normalized else None
            applicant_last_index = normalized.index("uchazec_prijmeni") if "uchazec_prijmeni" in normalized else None
            counts: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
            imported_rows = 0
            ignored_rows = 0
            for row in reader:
                stav_value = row[stav_index].strip().lower() if stav_index is not None and len(row) > stav_index else ""
                if stav_value == "zrusena":
                    ignored_rows += 1
                    continue

                school_value = ""
                if school_index is not None and len(row) > school_index:
                    school_value = row[school_index].strip()
                if not school_value and middle_school_index is not None and len(row) > middle_school_index:
                    school_value = row[middle_school_index].strip()
                if not school_value:
                    continue

                psc_match = re.search(r"\b(\d{3}\s?\d{2})\b", school_value)
                psc = psc_match.group(1).replace(" ", "") if psc_match else ""
                kod_oboru = row[kod_oboru_index].strip() if kod_oboru_index is not None and len(row) > kod_oboru_index else ""
                obor_nazev = row[obor_name_index].strip() if obor_name_index is not None and len(row) > obor_name_index else ""
                priorita = row[priority_index].strip() if priority_index is not None and len(row) > priority_index else ""
                uchazec_jmeno = row[applicant_first_index].strip() if applicant_first_index is not None and len(row) > applicant_first_index else ""
                uchazec_prijmeni = row[applicant_last_index].strip() if applicant_last_index is not None and len(row) > applicant_last_index else ""
                address = school_value
                key = (address, psc, kod_oboru, obor_nazev, priorita)
                bucket = counts.setdefault(key, {"count": 0, "uchazec_jmeno": [], "uchazec_prijmeni": []})
                bucket["count"] = int(bucket.get("count", 0) or 0) + 1
                if uchazec_jmeno and uchazec_jmeno not in bucket["uchazec_jmeno"]:
                    bucket["uchazec_jmeno"].append(uchazec_jmeno)
                if uchazec_prijmeni and uchazec_prijmeni not in bucket["uchazec_prijmeni"]:
                    bucket["uchazec_prijmeni"].append(uchazec_prijmeni)
                imported_rows += 1

        temp_dir = Path(tempfile.gettempdir())
        summary_name = f"dips_{dips_path.name}"
        temp_file_path = temp_dir / summary_name
        counter = 1
        while temp_file_path.exists():
            temp_file_path = temp_dir / f"dips_{dips_path.stem}_{counter}{dips_path.suffix}"
            counter += 1

        try:
            with temp_file_path.open("w", encoding="utf-8", newline="") as out:
                writer = csv.writer(out, delimiter=",", lineterminator="\n")
                writer.writerow(["address", "psc", "count", "kod_oboru", "obor_nazev", "priorita", "uchazec_prijmeni", "uchazec_jmeno"])
                for (address, psc, kod_oboru, obor_nazev, priorita), data in sorted(counts.items(), key=lambda item: (-int(item[1].get("count", 0) or 0), item[0][0], item[0][2], item[0][3], item[0][4])):
                    writer.writerow([
                        address,
                        psc,
                        int(data.get("count", 0) or 0),
                        kod_oboru,
                        obor_nazev,
                        priorita,
                        " | ".join(data.get("uchazec_prijmeni", [])),
                        " | ".join(data.get("uchazec_jmeno", [])),
                    ])
            return temp_file_path, imported_rows, ignored_rows
        except Exception:
            temp_file_path.unlink(missing_ok=True)
            raise

    def delete_selected_file(self) -> None:
        item = self.file_list.currentItem()
        if item is None or "Žádné nahrané soubory." in item.text():
            self.set_status("Vyberte soubor k odstranění.")
            return
        filename = item.text().split(" — ")[0]
        response = QMessageBox.question(
            self,
            "Smazat soubor",
            f"Opravdu chcete smazat soubor {filename}?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if response != QMessageBox.Yes:
            return
        self.data.delete_file(filename)
        self.set_status(f"Soubor {filename} byl smazán.")
        self._load_files()
        self.refresh_state()

    def refresh_state(self) -> None:
        self.set_status("Aktualizuji data...")
        selected_obor_codes = self._selected_obor_codes_for_current_file()
        selected_priorities = self._selected_priorities_for_current_file()
        if self._show_all_mode:
            if self.data.file_count() == 0:
                self.show_empty_map()
                self.set_status("Nejsou k dispozici žádné soubory ke zobrazení.")
                return
            self._start_map_refresh(
                load_all=True,
                selected_obor_codes=selected_obor_codes,
                selected_priorities=selected_priorities,
            )
            return

        selected_path = self._selected_file_path()
        if selected_path is None and self.current_selected_file is not None:
            selected_path = self.data.upload_dir / self.current_selected_file
            if not selected_path.exists():
                selected_path = None

        if selected_path is None:
            self.current_selected_file = None
            self.show_empty_map()
            self.set_status("Vyberte soubor, který chcete zobrazit.")
            return

        force_cache_refresh = self.data.should_refresh_points_cache(selected_path)
        if force_cache_refresh:
            self._start_map_refresh(
                selected_path,
                selected_obor_codes=selected_obor_codes,
                selected_priorities=selected_priorities,
                force_cache_refresh=True,
            )
            return

        if self.data.is_map_current_for_file(selected_path, selected_obor_codes, selected_priorities):
            self.set_status(f"Mapa je již aktuální pro soubor {selected_path.name}.")
            if MAP_FILE.exists():
                self.web_view.load(QUrl.fromLocalFile(str(MAP_FILE.resolve())))
            self._show_failed_locations_message(self.data.get_failed_locations(selected_path))
            return
        self._start_map_refresh(
            selected_path,
            selected_obor_codes=selected_obor_codes,
            selected_priorities=selected_priorities,
        )

    def show_all_files(self) -> None:
        self._show_all_mode = True
        self.current_selected_file = None
        self._suppress_selection_refresh = True
        self.file_list.clearSelection()
        self._suppress_selection_refresh = False
        self._update_filter_ui()
        self.set_status("Zpracovávám všechna data ze všech souborů...")
        self._start_map_refresh(
            load_all=True,
            selected_obor_codes=self._selected_obor_codes_for_current_file(),
            selected_priorities=self._selected_priorities_for_current_file(),
        )

    def _start_map_refresh(
        self,
        selected_path: Path | None = None,
        load_all: bool = False,
        selected_obor_codes: list[str] | None = None,
        selected_priorities: list[str] | None = None,
        force_cache_refresh: bool = False,
    ) -> None:
        if hasattr(self, 'worker_thread') and getattr(self, 'worker_thread', None) is not None:
            return

        self.progress_dialog = QProgressDialog("Zpracovávám data...", "Zrušit", 0, 0, self)
        self.progress_dialog.setWindowTitle("Načítání mapy")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setCancelButtonText("Zrušit")
        self.progress_dialog.canceled.connect(self._cancel_map_refresh)
        self.progress_dialog.show()

        self.worker_thread = QThread(self)
        self.worker = MapBuilderWorker(
            self.data,
            selected_path,
            load_all=load_all,
            selected_obor_codes=selected_obor_codes,
            selected_priorities=selected_priorities,
            force_cache_refresh=force_cache_refresh,
        )
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self._on_map_refresh_finished)
        self.worker.progress.connect(self._on_map_refresh_progress)
        self.worker.progress_counts.connect(self._on_map_refresh_progress_counts)
        self.worker.cache_mode.connect(self._on_worker_cache_mode)
        self.worker.points_ready.connect(self._on_points_ready)
        self.worker.error.connect(self._on_map_refresh_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _update_progress_dialog(self) -> None:
        if not hasattr(self, 'progress_dialog') or self.progress_dialog is None:
            return

        base_message = self._progress_message or "Zpracovávám data..."
        if self._progress_total > 0:
            current = max(0, min(self._progress_current, self._progress_total))
            percent = int((current / self._progress_total) * 100)
            self.progress_dialog.setRange(0, self._progress_total)
            self.progress_dialog.setValue(current)
            self.progress_dialog.setLabelText(f"{base_message}\n{current}/{self._progress_total} ({percent} %)" )
        else:
            self.progress_dialog.setRange(0, 0)
            self.progress_dialog.setLabelText(base_message)

    def _on_map_refresh_progress(self, message: str) -> None:
        self._progress_message = message
        self._update_progress_dialog()

    def _on_map_refresh_progress_counts(self, current: int, total: int) -> None:
        self._progress_current = current
        self._progress_total = total
        self._update_progress_dialog()

    def _on_worker_cache_mode(self, mode: str) -> None:
        self._last_cache_mode = mode

    def _on_map_refresh_finished(self, success: bool) -> None:
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
            self.progress_dialog = None
        self._progress_message = ""
        self._progress_current = 0
        self._progress_total = 0
        self.worker_thread = None
        if success:
            self._update_map()
            if self._last_cache_mode == "cache":
                self.set_status("Mapa načtena z cache (bez geokódování).")
            elif self._last_cache_mode == "refresh":
                self.set_status("Mapa přepočtena (včetně kontroly geokódování).")
            if self._show_all_mode:
                failed_locations = self.data.get_all_failed_locations()
            else:
                failed_locations = []
                if hasattr(self, 'worker'):
                    failed_locations = getattr(self.worker, 'failed_locations', []) or []
            self._show_failed_locations_message(failed_locations)
        else:
            self.set_status("Načítání bylo zrušeno.")
        self._last_cache_mode = ""

    def _on_points_ready(self, points: list[dict[str, Any]]) -> None:
        self._update_obor_filter_all_label_for_map(points)
        self._update_priority_filter_all_label_for_map(points)

    def _update_obor_filter_all_label_for_map(self, points: list[dict[str, Any]]) -> None:
        if self._all_obory_total_count <= 0:
            return
        displayed_total = sum(int(point.get("count", 0) or 0) for point in points)
        if displayed_total == self._all_obory_total_count:
            self.obor_filter_all_checkbox.setText(f"Všechny obory ({self._all_obory_total_count})")
        else:
            self.obor_filter_all_checkbox.setText(
                f"Všechny obory ({self._all_obory_total_count}, na mapě {displayed_total})"
            )

    def _update_priority_filter_all_label_for_map(self, points: list[dict[str, Any]]) -> None:
        if self._all_priorities_total_count <= 0:
            return
        displayed_total = sum(int(point.get("count", 0) or 0) for point in points)
        if displayed_total == self._all_priorities_total_count:
            self.priority_filter_all_checkbox.setText(f"Všechny priority ({self._all_priorities_total_count})")
        else:
            self.priority_filter_all_checkbox.setText(
                f"Všechny priority ({self._all_priorities_total_count}, na mapě {displayed_total})"
            )

    def _on_map_refresh_error(self, error_message: str) -> None:
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
            self.progress_dialog = None
        self.worker_thread = None
        QMessageBox.warning(self, "Chyba", f"Nastala chyba při zpracování mapy: {error_message}")
        self.set_status("Chyba při zpracování mapy.")

    def _cancel_map_refresh(self) -> None:
        if hasattr(self, 'worker'):
            self.worker.cancel()

    def _load_files(self) -> None:
        selected_name = self.current_selected_file
        if selected_name is None:
            selected_item = self.file_list.currentItem()
            if selected_item is not None and " — " in selected_item.text():
                selected_name = selected_item.text().split(" — ")[0]

        self.file_list.clear()
        files = self.data.list_files()
        if not files:
            self.file_list.addItem("Žádné nahrané soubory.")
            self._update_filter_ui()
            return
        for info in files:
            self.file_list.addItem(f"{info['name']} — {info['size']}")

        if selected_name is not None:
            self._suppress_selection_refresh = True
            self._select_file_in_list(selected_name)
            self._suppress_selection_refresh = False
        self._update_filter_ui()

    def _selected_file_path(self) -> Path | None:
        selected_item = self.file_list.currentItem()
        if selected_item is None or " — " not in selected_item.text():
            return None

        filename = selected_item.text().split(" — ")[0]
        path = self.data.upload_dir / filename
        return path if path.exists() else None

    def _select_file_in_list(self, filename: str) -> None:
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            if item is not None and item.text().startswith(f"{filename} —"):
                self.file_list.setCurrentRow(index)
                return

    def _update_map(self) -> None:
        # Mapa je vytvářena ve vlákně, takže tady jen zajišťujeme načtení výsledku.
        if MAP_FILE.exists():
            self.web_view.load(QUrl.fromLocalFile(str(MAP_FILE.resolve())))
        else:
            self.web_view.setHtml("<html><body><p>Mapa se nepodařilo načíst.</p></body></html>")
        selected_path = self._selected_file_path()
        self.web_view.update()
        self.web_view.page().setZoomFactor(1.0)
        QTimer.singleShot(100, self._trigger_web_view_redraw)
        QTimer.singleShot(250, self._trigger_web_view_redraw)
        if self._show_all_mode:
            self.set_status("Zobrazena mapa se všemi nahranými soubory.")
        elif selected_path is None:
            self.set_status("Vyberte soubor, aby se zobrazila mapa.")
        else:
            self.set_status(f"Zobrazeny uchazeči ze souboru {selected_path.name}.")
        QTimer.singleShot(500, self._trigger_web_view_redraw)

    def _on_web_view_load_finished(self, success: bool) -> None:
        if success:
            # Vynucení redrawu po načtení mapy pomůže odstranit pixelaci markerů.
            QTimer.singleShot(150, self._trigger_web_view_redraw)

    def _trigger_web_view_redraw(self) -> None:
        js = """
        (function() {
            function invalidateMap(m) {
                if (m && typeof m.invalidateSize === 'function') {
                    m.invalidateSize();
                    return true;
                }
                return false;
            }
            if (invalidateMap(window.map)) return;
            for (var key in window) {
                if (window.hasOwnProperty(key) && invalidateMap(window[key])) {
                    return;
                }
            }
            window.dispatchEvent(new Event('resize'));
        })();
        """
        self.web_view.page().runJavaScript(js)

    def _show_failed_locations_message(self, failed_locations: list[dict[str, Any]]) -> None:
        self.failed_locations_list.clear()
        aggregated: dict[str, dict[str, Any]] = {}
        for entry in failed_locations:
            address = str(entry.get("address", "")).strip()
            psc = str(entry.get("psc", "")).strip()
            key = f"{address} ({psc})" if psc else address
            if not key:
                continue
            bucket = aggregated.setdefault(key, {"rows": 0, "count": 0, "names": []})
            bucket["rows"] += 1
            bucket["count"] += int(entry.get("count", 0) or 0)
            first_name = str(entry.get("uchazec_jmeno", "")).strip()
            last_name = str(entry.get("uchazec_prijmeni", "")).strip()
            full_name = f"{last_name} {first_name}".strip()
            if full_name and full_name not in bucket["names"]:
                bucket["names"].append(full_name)

        total_addresses = len(aggregated)
        total_applicants = sum(int(item["count"]) for item in aggregated.values())
        self.failed_locations_toggle_button.setEnabled(total_addresses > 0)

        if total_addresses == 0:
            self.failed_locations_toggle_button.blockSignals(True)
            self.failed_locations_toggle_button.setChecked(False)
            self.failed_locations_toggle_button.blockSignals(False)
            self.failed_locations_list.hide()
            self.failed_locations_toggle_button.setText("Negeokódované řádky (0) [+]")
            return

        sorted_entries = sorted(
            aggregated.items(),
            key=lambda item: (-int(item[1]["count"]), item[0].lower()),
        )
        for label, info in sorted_entries:
            names_text = "; ".join(info["names"]) if info.get("names") else "bez jména"
            self.failed_locations_list.addItem(
                f"{label} — uchazečů: {info['count']}, řádků: {info['rows']}, jména: {names_text}"
            )

        expanded = self.failed_locations_toggle_button.isChecked()
        marker = "[-]" if expanded else "[+]"
        self.failed_locations_toggle_button.setText(
            f"Negeokódované řádky ({total_addresses} adres, {total_applicants} uch.) {marker}"
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(300, self._trigger_web_view_redraw)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(150, self._trigger_web_view_redraw)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
