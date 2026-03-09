"""
Shared helpers for receipt workflow pipelines (vision and legacy-deprecated).

Used by workflow_processor_vision and by deprecated workflow_processor_legacy_ocr_llm.
"""
from typing import Dict, Any, Optional, List
import logging
import re
from datetime import datetime, timezone
import json
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output paths (project root)
# ---------------------------------------------------------------------------
# backend/app/core/workflow_common.py -> backend/app/core -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_ROOT = PROJECT_ROOT / "output"
INPUT_ROOT = PROJECT_ROOT / "input"

OUTPUT_ROOT.mkdir(exist_ok=True)
INPUT_ROOT.mkdir(exist_ok=True)


def _fail_output_payload(error_message: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Standard JSON output_payload when a stage fails."""
    return {"error": error_message, "reason": reason or error_message}


class TimelineRecorder:
    """Record timeline of processing workflow."""

    def __init__(self, receipt_id: str):
        self.receipt_id = receipt_id
        self.timeline: List[Dict[str, Any]] = []
        self._start_times: Dict[str, datetime] = {}

    def start(self, step: str):
        now = datetime.now(timezone.utc)
        self._start_times[step] = now
        self.timeline.append({
            "step": f"{step}_start",
            "timestamp": now.isoformat(),
            "duration_ms": None
        })

    def end(self, step: str):
        now = datetime.now(timezone.utc)
        start_time = self._start_times.get(step)
        duration_ms = None
        if start_time:
            duration = (now - start_time).total_seconds() * 1000
            duration_ms = round(duration, 2)
        self.timeline.append({
            "step": f"{step}_end",
            "timestamp": now.isoformat(),
            "duration_ms": duration_ms
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "timeline": self.timeline
        }


def generate_receipt_id(filename: Optional[str] = None) -> str:
    """Generate receipt ID (format: seq_mmyydd_hhmm_filename)."""
    now = datetime.now(timezone.utc)
    seq = now.strftime("%H%M%S") + str(now.microsecond)[-2:]
    date_time = now.strftime("%m%d%y_%H%M")
    if filename:
        clean_name = Path(filename).stem
        clean_name = re.sub(r'[^\w\-_]', '_', clean_name)
        clean_name = clean_name[:20]
        if clean_name:
            return f"{seq}_{date_time}_{clean_name}"
    return f"{seq}_{date_time}"


def get_date_folder_name(receipt_id: Optional[str] = None) -> str:
    """Get date folder name in format YYYYMMDD from receipt_id or current date."""
    if receipt_id:
        match = re.search(r'_(\d{2})(\d{2})(\d{2})_', receipt_id)
        if match:
            month, day, year_2digit = match.group(1), match.group(2), match.group(3)
            return f"20{year_2digit}{month}{day}"
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _get_duration_from_timeline(timeline: "TimelineRecorder", step_name: str) -> Optional[int]:
    """Get duration in milliseconds for a step from timeline."""
    for entry in timeline.timeline:
        if entry.get("step") == f"{step_name}_end":
            return entry.get("duration_ms")
    return None


def get_output_paths_for_receipt(receipt_id: str, date_folder: Optional[str] = None) -> Dict[str, Path]:
    """Get all output paths for a receipt (date_dir, json_file, timeline_dir, etc.)."""
    if date_folder is None:
        date_folder = get_date_folder_name(receipt_id)
    date_dir = OUTPUT_ROOT / date_folder
    return {
        "date_dir": date_dir,
        "json_file": date_dir / f"{receipt_id}_output.json",
        "timeline_dir": date_dir / "timeline",
        "timeline_file": date_dir / "timeline" / f"{receipt_id}_timeline.json",
        "csv_file": date_dir / f"{date_folder}.csv",
        "debug_dir": date_dir / "debug-001",
        "error_dir": date_dir / "error-001"
    }


def _save_image_for_manual_review(
    receipt_id: str,
    image_bytes: bytes,
    filename: str
) -> Optional[str]:
    """Save image for manual review; return relative path from project root or None."""
    try:
        paths = get_output_paths_for_receipt(receipt_id)
        paths["error_dir"].mkdir(parents=True, exist_ok=True)
        file_ext = Path(filename).suffix.lower() if filename else ".jpg"
        if file_ext not in [".jpg", ".jpeg", ".png"]:
            file_ext = ".jpg"
        image_file = paths["error_dir"] / f"{receipt_id}_original{file_ext}"
        image_file.write_bytes(image_bytes)
        rel = image_file.relative_to(PROJECT_ROOT)
        logger.info("Saved image for manual review: %s", rel)
        return str(rel)
    except Exception as e:
        logger.error("Failed to save image for manual review: %s", e)
        return None


async def _save_output(
    receipt_id: str,
    llm_result: Dict[str, Any],
    timeline: TimelineRecorder,
    ocr_data: Optional[Dict[str, Any]] = None,
    user_id: str = "dummy"
):
    """Save final output JSON in output/YYYYMMDD/{receipt_id}_output.json."""
    paths = get_output_paths_for_receipt(receipt_id)
    paths["date_dir"].mkdir(parents=True, exist_ok=True)
    paths["timeline_dir"].mkdir(parents=True, exist_ok=True)
    output_data = {
        "receipt_id": receipt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": llm_result
    }
    paths["json_file"].parent.mkdir(parents=True, exist_ok=True)
    with open(paths["json_file"], "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    logger.info("Saved output JSON: %s", paths["json_file"])
