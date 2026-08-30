"""Command-line entry point for teacher annotation export."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Optional, Sequence

from .exporter import AnnotationOptions, TeacherAnnotationExporter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sister-annotate",
        description=(
            "Export English label annotations from screenshots using SISTER's "
            "current OCR label locator as the teacher."
        ),
    )
    parser.add_argument(
        "inputs",
        metavar="INPUT",
        nargs="+",
        type=Path,
        help="Image file or directory to scan recursively",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        metavar="CORPUS",
        help="Portable annotation corpus directory",
    )
    parser.add_argument("--platform", required=True, choices=("pc", "console"))
    parser.add_argument("--domain", required=True, choices=("space", "ground"))
    parser.add_argument(
        "--gpu", action="store_true", help="Use EasyOCR GPU acceleration"
    )
    parser.add_argument(
        "--no-resize",
        action="store_true",
        help="Run the teacher at the source image resolution",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rewrite an existing exact annotation variant",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="WARNING",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    )
    options = AnnotationOptions(
        output_dir=args.output_dir,
        platform=args.platform,
        domain=args.domain,
        gpu=args.gpu,
        resize_fullhd=not args.no_resize,
        force=args.force,
    )
    try:
        exporter = TeacherAnnotationExporter(options)
    except Exception as exc:
        logging.getLogger(__name__).error(
            "Could not initialize the annotation teacher: %s", exc
        )
        logging.getLogger(__name__).debug(
            "Teacher initialization traceback", exc_info=True
        )
        print(f"[failed] teacher initialization: {exc}")
        return 1
    summary = exporter.export(args.inputs)

    for result in summary["annotations"]:
        print(
            f"[{result['status']}] {result['annotation_path']} "
            f"({result['instance_count']} labels)"
        )
    for failure in summary["failures"]:
        print(
            f"[failed] {failure['source_path']}: {failure['error']}",
        )
    print(
        "Annotation export complete: "
        f"{summary['processed']} processed, "
        f"{summary['skipped']} skipped, "
        f"{summary['failed']} failed."
    )
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
