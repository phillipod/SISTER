"""Export silver label annotations from SISTER's current OCR teacher."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import cv2
import numpy as np

from sister_sto.components.label_locator import LabelInstance, LabelLocator
from sister_sto.components.layout_classifier import LayoutClassifier
from sister_sto.utils.image import load_image, resize_to_max_fullhd

from .schema import (
    SCHEMA_VERSION,
    atomic_write_bytes,
    atomic_write_json,
    fingerprint,
    git_revision,
    map_bbox_to_source,
    package_version,
    pixel_sha256,
    sha256_bytes,
    utc_now,
)


logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".img"}
BUILD_METADATA = {
    "PC Ship Build": ("pc", "space"),
    "PC Ground Build": ("pc", "ground"),
    "Console Ship Build": ("console", "space"),
    "Console Ground Build": ("console", "ground"),
    "SETS Ship Build": (None, "space"),
    "SETS Ground Build": (None, "ground"),
    "Personal Ground Traits": (None, "ground"),
    "Ground Reputation": (None, "ground"),
    "Active Ground Reputation": (None, "ground"),
    "Personal Space Traits": (None, "space"),
    "Space Reputation": (None, "space"),
    "Active Space Reputation": (None, "space"),
    "Starship Traits": (None, "space"),
}


@dataclass(frozen=True)
class AnnotationOptions:
    output_dir: Path
    platform: str
    domain: str
    gpu: bool = False
    resize_fullhd: bool = True
    force: bool = False

    def __post_init__(self) -> None:
        if self.platform not in {"pc", "console"}:
            raise ValueError("platform must be 'pc' or 'console'")
        if self.domain not in {"space", "ground"}:
            raise ValueError("domain must be 'space' or 'ground'")


@dataclass(frozen=True)
class DiscoveredImage:
    path: Path
    source_path: str


def _is_supported_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def discover_images(
    inputs: Sequence[Path], output_dir: Optional[Path] = None
) -> Tuple[List[DiscoveredImage], List[Dict[str, str]]]:
    """Resolve input files and recursive directories in deterministic order."""
    discovered: Dict[Path, DiscoveredImage] = {}
    failures: List[Dict[str, str]] = []
    resolved_output = output_dir.resolve() if output_dir is not None else None
    multiple_inputs = len(inputs) > 1

    for supplied in inputs:
        path = supplied.expanduser().resolve()
        if not path.exists():
            failures.append(
                {"source_path": str(supplied), "error": "Input does not exist"}
            )
            continue

        candidates: Iterable[Path]
        if path.is_dir():
            candidates = path.rglob("*")
        elif path.is_file():
            candidates = (path,)
        else:
            failures.append(
                {"source_path": str(supplied), "error": "Unsupported input type"}
            )
            continue

        supported_count = 0
        for candidate in candidates:
            candidate = candidate.resolve()
            if resolved_output and _is_within(candidate, resolved_output):
                continue
            if not _is_supported_image(candidate):
                continue
            supported_count += 1
            if path.is_dir():
                relative = candidate.relative_to(path).as_posix()
                display = f"{path.name}/{relative}" if multiple_inputs else relative
            else:
                display = candidate.name
            discovered.setdefault(
                candidate, DiscoveredImage(path=candidate, source_path=display)
            )

        if supported_count == 0:
            if path.is_file():
                error = f"Unsupported image extension: {path.suffix or '(none)'}"
            else:
                error = "No supported images found"
            failures.append({"source_path": str(supplied), "error": error})

    ordered = sorted(
        discovered.values(),
        key=lambda item: (item.source_path.casefold(), item.path.as_posix()),
    )
    return ordered, failures


class TeacherAnnotationExporter:
    """Run the label teacher once per source and build a portable corpus."""

    def __init__(
        self,
        options: AnnotationOptions,
        locator: Optional[LabelLocator] = None,
        classifier: Optional[LayoutClassifier] = None,
    ) -> None:
        self.options = options
        self.output_dir = options.output_dir.expanduser().resolve()
        self.locator = locator if locator is not None else LabelLocator(gpu=options.gpu)
        self.classifier = classifier if classifier is not None else LayoutClassifier()
        self.teacher = self._teacher_identity()

    def _teacher_identity(self) -> Dict[str, Any]:
        settings = {
            "gpu": self.options.gpu,
            "height_ths": 0.0,
            "languages": ["en"],
            "paragraph": True,
            "reocr_paragraph": False,
            "resize_fullhd": self.options.resize_fullhd,
            "scale_x": self.locator.scale_x,
            "width_ths": 0.0,
        }
        try:
            easyocr_version = metadata.version("easyocr")
        except metadata.PackageNotFoundError:
            easyocr_version = "unknown"

        implementation_files = [
            Path(__file__),
            Path(__file__).resolve().parents[1] / "components" / "label_locator.py",
            Path(__file__).resolve().parents[1] / "components" / "layout_classifier.py",
        ]
        implementation_hash = sha256_bytes(
            b"".join(path.read_bytes() for path in implementation_files)
        )
        identity = {
            "name": "sister-easyocr-label-teacher",
            "package_version": package_version(),
            "easyocr_version": easyocr_version,
            "implementation_sha256": implementation_hash,
            "settings": settings,
        }
        identity["fingerprint"] = f"sha256:{fingerprint(identity)}"
        revision = git_revision()
        if revision:
            identity["git_revision"] = revision
        return identity

    def export(self, inputs: Sequence[Path]) -> Dict[str, Any]:
        started_at = utc_now()
        images, failures = discover_images(inputs, output_dir=self.output_dir)
        aliases: Dict[str, set[str]] = defaultdict(set)
        processed = 0
        skipped = 0
        annotation_results: List[Dict[str, Any]] = []

        for image in images:
            try:
                result = self._export_image(image)
                aliases[result["source_sha256"]].add(image.source_path)
                annotation_results.append(result)
                if result["status"] == "skipped":
                    skipped += 1
                else:
                    processed += 1
            except Exception as exc:  # Continue through a batch by design.
                logger.error("Could not annotate %s: %s", image.path, exc)
                logger.debug("Annotation failure traceback", exc_info=True)
                failures.append(
                    {
                        "source_path": image.source_path,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

        corpus = self._write_corpus_index(
            aliases=aliases,
            failures=failures,
            started_at=started_at,
            discovered_count=len(images),
            processed=processed,
            skipped=skipped,
        )
        return {
            "discovered": len(images),
            "processed": processed,
            "skipped": skipped,
            "failed": len(failures),
            "failures": failures,
            "annotations": annotation_results,
            "corpus": corpus,
        }

    def _annotation_fingerprint(self, source_sha256: str) -> str:
        return fingerprint(
            {
                "domain": self.options.domain,
                "platform": self.options.platform,
                "source_sha256": source_sha256,
                "teacher_fingerprint": self.teacher["fingerprint"],
            }
        )

    def _export_image(self, image: DiscoveredImage) -> Dict[str, Any]:
        source_bytes = image.path.read_bytes()
        source_sha256 = sha256_bytes(source_bytes)
        annotation_fingerprint = self._annotation_fingerprint(source_sha256)
        annotation_relpath = (
            Path("annotations") / source_sha256 / (f"{annotation_fingerprint}.json")
        )
        annotation_path = self.output_dir / annotation_relpath

        if annotation_path.exists() and not self.options.force:
            existing = self._load_existing_annotation(
                annotation_path, source_sha256, annotation_fingerprint
            )
            if existing is not None:
                return {
                    "status": "skipped",
                    "annotation_id": existing["annotation_id"],
                    "annotation_path": annotation_relpath.as_posix(),
                    "source_sha256": source_sha256,
                    "instance_count": len(existing.get("instances", [])),
                }

        original = load_image(source_bytes, resize_fullhd=False)
        if original is None or original.size == 0:
            raise ValueError("Image could not be decoded")
        processed_image = (
            resize_to_max_fullhd(original) if self.options.resize_fullhd else original
        )
        original_height, original_width = original.shape[:2]
        processed_height, processed_width = processed_image.shape[:2]

        source_relpath = self._store_source(
            source_bytes, source_sha256, image.path.suffix.lower()
        )

        teacher_started = time.perf_counter()
        instances = self.locator.locate_label_instances(processed_image)
        teacher_duration_ms = round((time.perf_counter() - teacher_started) * 1000, 3)
        label_positions = self.locator.instances_to_label_dict(instances)
        classification_scores = self.classifier.classify(label_positions)
        classification, warnings = self._classification_diagnostics(
            classification_scores
        )

        crop_directory = (
            self.output_dir / "crops" / source_sha256 / annotation_fingerprint
        )
        serialized_instances = []
        source_boxes: List[Tuple[LabelInstance, Tuple[int, int, int, int]]] = []
        for instance in instances:
            source_bbox = map_bbox_to_source(
                instance.bbox_xyxy,
                processed_width,
                processed_height,
                original_width,
                original_height,
            )
            x1, y1, x2, y2 = source_bbox
            crop_relpath = (
                Path("crops")
                / source_sha256
                / annotation_fingerprint
                / f"{instance.instance_id}.png"
            )
            crop_path: Optional[str] = None
            if x2 > x1 and y2 > y1:
                self._write_png(
                    crop_directory / crop_relpath.name, original[y1:y2, x1:x2]
                )
                crop_path = crop_relpath.as_posix()
            else:
                warnings.append(f"Empty source-space crop for {instance.instance_id}")

            serialized_instances.append(
                {
                    "instance_id": instance.instance_id,
                    "label": instance.canonical_label,
                    "recognized_text": instance.recognized_text,
                    "match_method": instance.match_method,
                    "bbox_processed_xyxy": list(instance.bbox_xyxy),
                    "bbox_source_xyxy": list(source_bbox),
                    "crop_path": crop_path,
                    "review_status": "automatic",
                }
            )
            source_boxes.append((instance, source_bbox))

        overlay_relpath = (
            Path("overlays") / source_sha256 / f"{annotation_fingerprint}.png"
        )
        self._write_overlay(self.output_dir / overlay_relpath, original, source_boxes)

        annotation_id = f"sha256:{annotation_fingerprint}"
        annotation = {
            "schema_version": SCHEMA_VERSION,
            "annotation_id": annotation_id,
            "created_at": utc_now(),
            "review_status": "automatic",
            "source": {
                "path": image.source_path,
                "sha256": source_sha256,
                "byte_size": len(source_bytes),
                "stored_path": source_relpath.as_posix(),
                "dimensions": {
                    "width": original_width,
                    "height": original_height,
                },
            },
            "processed": {
                "pixel_sha256": pixel_sha256(processed_image),
                "dimensions": {
                    "width": processed_width,
                    "height": processed_height,
                },
                "resize": {
                    "enabled": self.options.resize_fullhd,
                    "applied": (processed_width, processed_height)
                    != (original_width, original_height),
                    "scale_x": processed_width / original_width,
                    "scale_y": processed_height / original_height,
                },
            },
            "metadata": {
                "platform": self.options.platform,
                "domain": self.options.domain,
            },
            "teacher": {**self.teacher, "duration_ms": teacher_duration_ms},
            "classification": classification,
            "warnings": sorted(set(warnings)),
            "overlay_path": overlay_relpath.as_posix(),
            "instances": serialized_instances,
        }
        atomic_write_json(annotation_path, annotation)
        return {
            "status": "processed",
            "annotation_id": annotation_id,
            "annotation_path": annotation_relpath.as_posix(),
            "source_sha256": source_sha256,
            "instance_count": len(serialized_instances),
        }

    def _load_existing_annotation(
        self, path: Path, source_sha256: str, annotation_fingerprint: str
    ) -> Optional[Mapping[str, Any]]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError):
            logger.warning("Rewriting corrupt annotation: %s", path)
            return None

        expected_id = f"sha256:{annotation_fingerprint}"
        if (
            value.get("schema_version") != SCHEMA_VERSION
            or value.get("annotation_id") != expected_id
            or value.get("source", {}).get("sha256") != source_sha256
            or value.get("teacher", {}).get("fingerprint")
            != self.teacher["fingerprint"]
            or value.get("metadata", {}).get("platform") != self.options.platform
            or value.get("metadata", {}).get("domain") != self.options.domain
        ):
            logger.warning("Rewriting incompatible annotation: %s", path)
            return None
        artifact_paths = [
            value.get("source", {}).get("stored_path"),
            value.get("overlay_path"),
            *(
                instance.get("crop_path")
                for instance in value.get("instances", [])
                if instance.get("crop_path")
            ),
        ]
        if any(
            not relative or not (self.output_dir / relative).is_file()
            for relative in artifact_paths
        ):
            logger.warning("Rewriting incomplete annotation: %s", path)
            return None
        return value

    def _store_source(
        self, source_bytes: bytes, source_sha256: str, extension: str
    ) -> Path:
        image_directory = self.output_dir / "images"
        existing = sorted(image_directory.glob(f"{source_sha256}.*"))
        if existing:
            path = existing[0]
            if sha256_bytes(path.read_bytes()) != source_sha256:
                logger.warning("Repairing stored source hash mismatch: %s", path)
                atomic_write_bytes(path, source_bytes)
            return path.relative_to(self.output_dir)

        safe_extension = extension if extension in SUPPORTED_EXTENSIONS else ".img"
        relative = Path("images") / f"{source_sha256}{safe_extension}"
        atomic_write_bytes(self.output_dir / relative, source_bytes)
        return relative

    @staticmethod
    def _write_png(path: Path, image: np.ndarray) -> None:
        success, encoded = cv2.imencode(".png", image)
        if not success:
            raise ValueError(f"Could not encode PNG: {path}")
        atomic_write_bytes(path, encoded.tobytes())

    def _write_overlay(
        self,
        path: Path,
        original: np.ndarray,
        boxes: Sequence[Tuple[LabelInstance, Tuple[int, int, int, int]]],
    ) -> None:
        overlay = original.copy()
        for instance, (x1, y1, x2, y2) in boxes:
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), 2)
            caption = f"{instance.instance_id} {instance.canonical_label}"
            cv2.putText(
                overlay,
                caption,
                (x1, max(12, y1 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 0),
                1,
                cv2.LINE_AA,
            )
        self._write_png(path, overlay)

    def _classification_diagnostics(
        self, scores: Mapping[str, Mapping[str, Any]]
    ) -> Tuple[Dict[str, Any], List[str]]:
        warnings = []
        winner = None
        inferred_platform = None
        inferred_domain = None
        if scores:
            winner = max(
                scores,
                key=lambda name: scores[name].get("score", 0),
            )
            inferred_platform, inferred_domain = BUILD_METADATA.get(
                winner, (None, None)
            )
            if inferred_platform and inferred_platform != self.options.platform:
                warnings.append(
                    f"Teacher inferred platform {inferred_platform}, "
                    f"but batch metadata is {self.options.platform}"
                )
            if inferred_domain and inferred_domain != self.options.domain:
                warnings.append(
                    f"Teacher inferred domain {inferred_domain}, "
                    f"but batch metadata is {self.options.domain}"
                )
        else:
            warnings.append("Layout classifier produced no positive scores")

        return (
            {
                "scores": {name: dict(value) for name, value in sorted(scores.items())},
                "winner": winner,
                "inferred_platform": inferred_platform,
                "inferred_domain": inferred_domain,
                "metadata_matches": (
                    None
                    if winner is None
                    else (inferred_platform in {None, self.options.platform})
                    and (inferred_domain in {None, self.options.domain})
                ),
            },
            warnings,
        )

    def _write_corpus_index(
        self,
        aliases: Mapping[str, set[str]],
        failures: Sequence[Mapping[str, str]],
        started_at: str,
        discovered_count: int,
        processed: int,
        skipped: int,
    ) -> Dict[str, Any]:
        annotations = []
        sources: Dict[str, Dict[str, Any]] = {}
        label_counts: Counter[str] = Counter()
        platform_counts: Counter[str] = Counter()
        domain_counts: Counter[str] = Counter()
        platform_domain_counts: Counter[str] = Counter()
        invalid_annotations = []
        persisted_aliases: Dict[str, set[str]] = defaultdict(set)
        existing_index_path = self.output_dir / "corpus.json"
        if existing_index_path.exists():
            try:
                with existing_index_path.open("r", encoding="utf-8") as handle:
                    existing_index = json.load(handle)
                for source in existing_index.get("sources", []):
                    persisted_aliases[source["sha256"]].update(
                        source.get("aliases", [])
                    )
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                logger.warning(
                    "Rebuilding corrupt corpus index: %s", existing_index_path
                )

        annotation_root = self.output_dir / "annotations"
        for path in sorted(annotation_root.glob("*/*.json")):
            try:
                with path.open("r", encoding="utf-8") as handle:
                    annotation = json.load(handle)
                source = annotation["source"]
                source_sha256 = source["sha256"]
                metadata_value = annotation["metadata"]
                instances = annotation.get("instances", [])
            except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
                invalid_annotations.append(
                    {
                        "path": path.relative_to(self.output_dir).as_posix(),
                        "error": str(exc),
                    }
                )
                continue

            source_entry = sources.setdefault(
                source_sha256,
                {
                    "sha256": source_sha256,
                    "stored_path": source["stored_path"],
                    "aliases": set(),
                    "annotation_ids": [],
                },
            )
            source_entry["aliases"].add(source["path"])
            source_entry["aliases"].update(persisted_aliases[source_sha256])
            source_entry["aliases"].update(aliases.get(source_sha256, set()))
            source_entry["annotation_ids"].append(annotation["annotation_id"])

            platform = metadata_value["platform"]
            domain = metadata_value["domain"]
            platform_counts[platform] += 1
            domain_counts[domain] += 1
            platform_domain_counts[f"{platform}/{domain}"] += 1
            for instance in instances:
                label_counts[instance["label"]] += 1

            annotations.append(
                {
                    "annotation_id": annotation["annotation_id"],
                    "path": path.relative_to(self.output_dir).as_posix(),
                    "source_sha256": source_sha256,
                    "platform": platform,
                    "domain": domain,
                    "review_status": annotation.get("review_status", "automatic"),
                    "instance_count": len(instances),
                    "warning_count": len(annotation.get("warnings", [])),
                }
            )

        serialized_sources = []
        for source_sha256, value in sorted(sources.items()):
            serialized_sources.append(
                {
                    "sha256": source_sha256,
                    "stored_path": value["stored_path"],
                    "aliases": sorted(
                        value["aliases"], key=lambda alias: (alias.casefold(), alias)
                    ),
                    "annotation_ids": sorted(value["annotation_ids"]),
                }
            )

        corpus = {
            "schema_version": SCHEMA_VERSION,
            "updated_at": utc_now(),
            "sources": serialized_sources,
            "annotations": sorted(
                annotations,
                key=lambda item: (item["source_sha256"], item["annotation_id"]),
            ),
            "coverage": {
                "source_count": len(serialized_sources),
                "annotation_count": len(annotations),
                "instance_count": sum(label_counts.values()),
                "by_label": dict(sorted(label_counts.items())),
                "by_platform": dict(sorted(platform_counts.items())),
                "by_domain": dict(sorted(domain_counts.items())),
                "by_platform_domain": dict(sorted(platform_domain_counts.items())),
            },
            "invalid_annotations": invalid_annotations,
            "last_run": {
                "started_at": started_at,
                "completed_at": utc_now(),
                "discovered": discovered_count,
                "processed": processed,
                "skipped": skipped,
                "failed": len(failures),
                "failures": list(failures),
            },
        }
        atomic_write_json(self.output_dir / "corpus.json", corpus)
        return corpus
