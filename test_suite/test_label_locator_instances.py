import numpy as np

from sister_sto.components.label_locator import LabelLocator


class FakeReader:
    def __init__(self, primary, secondary=None):
        self.primary = primary
        self.secondary = secondary or []
        self.calls = []

    def readtext(self, _image, **kwargs):
        self.calls.append(kwargs)
        return self.primary if kwargs.get("paragraph") else self.secondary


def box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def test_instances_retain_duplicates_and_legacy_uses_largest():
    reader = FakeReader(
        [
            (box(125, 30, 250, 45), "Shield"),
            (box(25, 10, 75, 20), "Shield"),
            (box(250, 50, 400, 65), "Fore Weapon extra"),
            (box(375, 70, 500, 85), "prefix Aft Weapon"),
        ]
    )
    locator = LabelLocator(reader=reader)
    image = np.zeros((100, 500, 3), dtype=np.uint8)

    instances = locator.locate_label_instances(image)

    assert [item.instance_id for item in instances] == [
        "label-0001",
        "label-0002",
        "label-0003",
        "label-0004",
    ]
    assert [item.canonical_label for item in instances].count("Shield") == 2
    assert [item.match_method for item in instances] == [
        "exact",
        "exact",
        "prefix",
        "suffix",
    ]
    legacy = locator.instances_to_label_dict(instances)
    assert legacy["Shield"]["top_left"] == [100, 30]
    assert legacy["Shield"]["bottom_right"] == [200, 45]
    assert reader.calls == [{"paragraph": True, "height_ths": 0.0}]


def test_filter_records_fuzzy_match_method():
    locator = LabelLocator(reader=FakeReader([]))
    image = np.zeros((100, 500), dtype=np.uint8)

    instances = locator.filter_recognized_text_instances(
        {(1, 2, 100, 20): "Fore Weapom"}, image
    )

    assert len(instances) == 1
    assert instances[0].canonical_label == "Fore Weapon"
    assert instances[0].match_method == "fuzzy"


def test_composite_label_reocr_retains_split_instances():
    reader = FakeReader(
        [(box(0, 5, 500, 25), "Shield Deflector Impulse Warp")],
        [
            (box(0, 0, 80, 20), "Shield", 0.99),
            (box(90, 0, 190, 20), "Deflector", 0.99),
            (box(200, 0, 280, 20), "Impulse", 0.99),
            (box(290, 0, 350, 20), "Warp", 0.99),
        ],
    )
    locator = LabelLocator(reader=reader)
    image = np.zeros((40, 500, 3), dtype=np.uint8)

    instances = locator.locate_label_instances(image)

    assert [item.canonical_label for item in instances] == [
        "Shield",
        "Deflector",
        "Impulse",
        "Warp",
    ]
    assert {item.match_method for item in instances} == {"re-ocr"}
    assert len(reader.calls) == 2
    assert reader.calls[0]["paragraph"] is True
    assert reader.calls[1]["paragraph"] is False


def test_locate_labels_accepts_no_progress_callback():
    locator = LabelLocator(reader=FakeReader([(box(0, 0, 125, 10), "Kit")]))
    image = np.zeros((20, 120, 3), dtype=np.uint8)

    labels = locator.locate_labels(image)

    assert labels["Kit"]["bottom_right"] == [100, 10]
