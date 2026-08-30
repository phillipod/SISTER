import json
from pathlib import Path

import cv2
import numpy as np

from sister_sto.annotations.exporter import (
    AnnotationOptions,
    TeacherAnnotationExporter,
    discover_images,
)
from sister_sto.annotations.schema import clamp_bbox, map_bbox_to_source
from sister_sto.components.label_locator import LabelInstance, LabelLocator


class FakeLocator:
    scale_x = 1.25

    def __init__(self):
        self.calls = 0

    def locate_label_instances(self, _image):
        self.calls += 1
        return [
            LabelInstance(
                canonical_label="Shield",
                recognized_text="Shield",
                bbox_xyxy=(5, 5, 20, 15),
                match_method="exact",
                instance_id="label-0001",
            ),
            LabelInstance(
                canonical_label="Shield",
                recognized_text="Shield",
                bbox_xyxy=(25, 5, 38, 15),
                match_method="exact",
                instance_id="label-0002",
            ),
        ]

    def instances_to_label_dict(self, instances):
        return LabelLocator.instances_to_label_dict(instances)


class FakeClassifier:
    def __init__(self, result=None):
        self.result = result or {"PC Ship Build": {"score": 10, "is_required": False}}
        self.calls = 0

    def classify(self, _labels):
        self.calls += 1
        return self.result


def write_image(path: Path, value=0):
    image = np.full((20, 40, 3), value, dtype=np.uint8)
    success, encoded = cv2.imencode(path.suffix, image)
    assert success
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded.tobytes())


def read_annotation(corpus: Path):
    annotation_path = next((corpus / "annotations").glob("*/*.json"))
    return annotation_path, json.loads(annotation_path.read_text(encoding="utf-8"))


def test_coordinate_mapping_scales_and_clamps():
    assert clamp_bbox((-5, 4, 120, 90), 100, 80) == (0, 4, 100, 80)
    assert map_bbox_to_source((10, 5, 50, 25), 100, 50, 200, 100) == (
        20,
        10,
        100,
        50,
    )


def test_discovery_is_recursive_case_insensitive_and_stable(tmp_path):
    write_image(tmp_path / "z.PNG")
    write_image(tmp_path / "nested" / "A.png")
    (tmp_path / "ignored.txt").write_text("not an image", encoding="utf-8")

    images, failures = discover_images([tmp_path])

    assert failures == []
    assert [item.source_path for item in images] == ["nested/A.png", "z.PNG"]


def test_empty_directory_is_reported_as_a_discovery_failure(tmp_path):
    images, failures = discover_images([tmp_path])

    assert images == []
    assert failures[0]["error"] == "No supported images found"


def test_export_deduplicates_sources_and_resumes_exact_variant(tmp_path):
    inputs = tmp_path / "inputs"
    first = inputs / "one.png"
    second = inputs / "two.png"
    write_image(first)
    second.write_bytes(first.read_bytes())
    corpus = tmp_path / "corpus"
    locator = FakeLocator()
    classifier = FakeClassifier()
    exporter = TeacherAnnotationExporter(
        AnnotationOptions(corpus, "pc", "space"),
        locator=locator,
        classifier=classifier,
    )

    first_summary = exporter.export([inputs])
    second_summary = exporter.export([inputs])

    assert first_summary["processed"] == 1
    assert first_summary["skipped"] == 1
    assert second_summary["processed"] == 0
    assert second_summary["skipped"] == 2
    assert locator.calls == 1
    assert classifier.calls == 1
    assert len(list((corpus / "images").iterdir())) == 1
    assert next((corpus / "images").iterdir()).read_bytes() == first.read_bytes()
    assert len(list((corpus / "annotations").glob("*/*.json"))) == 1
    index = json.loads((corpus / "corpus.json").read_text(encoding="utf-8"))
    assert index["sources"][0]["aliases"] == ["one.png", "two.png"]
    assert index["coverage"]["instance_count"] == 2
    assert index["coverage"]["by_label"] == {"Shield": 2}

    (inputs / "two.png").unlink()
    exporter.export([inputs])
    persisted_index = json.loads((corpus / "corpus.json").read_text(encoding="utf-8"))
    assert persisted_index["sources"][0]["aliases"] == ["one.png", "two.png"]


def test_export_writes_original_crops_overlay_and_diagnostics(tmp_path):
    source = tmp_path / "source.png"
    write_image(source, value=127)
    corpus = tmp_path / "corpus"
    classifier = FakeClassifier(
        {"PC Ground Build": {"score": 50, "is_required": False}}
    )
    exporter = TeacherAnnotationExporter(
        AnnotationOptions(corpus, "pc", "space", resize_fullhd=False),
        locator=FakeLocator(),
        classifier=classifier,
    )

    summary = exporter.export([source])
    _, annotation = read_annotation(corpus)

    assert summary["failed"] == 0
    assert annotation["metadata"] == {"domain": "space", "platform": "pc"}
    assert annotation["classification"]["winner"] == "PC Ground Build"
    assert annotation["classification"]["metadata_matches"] is False
    assert any("inferred domain ground" in item for item in annotation["warnings"])
    assert annotation["processed"]["resize"]["enabled"] is False
    assert annotation["instances"][0]["bbox_source_xyxy"] == [5, 5, 20, 15]
    for instance in annotation["instances"]:
        assert (corpus / instance["crop_path"]).is_file()
    assert (corpus / annotation["overlay_path"]).is_file()


def test_force_rewrites_and_corrupt_annotation_is_recovered(tmp_path):
    source = tmp_path / "source.png"
    write_image(source)
    corpus = tmp_path / "corpus"
    locator = FakeLocator()
    exporter = TeacherAnnotationExporter(
        AnnotationOptions(corpus, "pc", "space"), locator, FakeClassifier()
    )
    exporter.export([source])
    annotation_path, _ = read_annotation(corpus)
    annotation_path.write_text("not json", encoding="utf-8")

    recovered = exporter.export([source])
    force_locator = FakeLocator()
    forced = TeacherAnnotationExporter(
        AnnotationOptions(corpus, "pc", "space", force=True),
        force_locator,
        FakeClassifier(),
    ).export([source])

    assert recovered["processed"] == 1
    assert forced["processed"] == 1
    assert locator.calls == 2
    assert force_locator.calls == 1
    read_annotation(corpus)


def test_missing_artifact_reprocesses_exact_annotation(tmp_path):
    source = tmp_path / "source.png"
    write_image(source)
    corpus = tmp_path / "corpus"
    locator = FakeLocator()
    exporter = TeacherAnnotationExporter(
        AnnotationOptions(corpus, "pc", "space"), locator, FakeClassifier()
    )
    exporter.export([source])
    _, annotation = read_annotation(corpus)
    (corpus / annotation["overlay_path"]).unlink()

    summary = exporter.export([source])

    assert summary["processed"] == 1
    assert locator.calls == 2
    assert (corpus / annotation["overlay_path"]).is_file()


def test_export_continues_after_per_image_failure(tmp_path):
    valid = tmp_path / "valid.png"
    invalid = tmp_path / "invalid.png"
    write_image(valid)
    invalid.write_bytes(b"not an image")
    exporter = TeacherAnnotationExporter(
        AnnotationOptions(tmp_path / "corpus", "pc", "space"),
        FakeLocator(),
        FakeClassifier(),
    )

    summary = exporter.export([invalid, valid])

    assert summary["processed"] == 1
    assert summary["failed"] == 1
    assert summary["failures"][0]["source_path"] == "invalid.png"
