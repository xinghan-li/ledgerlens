"""
Deprecated re-export shim. All helpers now live directly in workflow_processor_vision.py.
This file is kept only to avoid import errors in any tooling that references it;
do not add new logic here.
"""
from .workflow_processor_vision import (
    PROJECT_ROOT,
    OUTPUT_ROOT,
    INPUT_ROOT,
    TimelineRecorder,
    _fail_output_payload,
    get_date_folder_name,
    generate_receipt_id,
    get_output_paths_for_receipt,
    _get_duration_from_timeline,
    _save_image_for_manual_review,
    _save_output,
)

__all__ = [
    "PROJECT_ROOT",
    "OUTPUT_ROOT",
    "INPUT_ROOT",
    "TimelineRecorder",
    "_fail_output_payload",
    "get_date_folder_name",
    "generate_receipt_id",
    "get_output_paths_for_receipt",
    "_get_duration_from_timeline",
    "_save_image_for_manual_review",
    "_save_output",
]
