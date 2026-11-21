from src.stable_json import stabilize_floats


def test_stabilize_floats_removes_machine_precision_noise() -> None:
    left = {"score": 0.6163137829622601, "weights": [0.016702152045755703]}
    right = {"score": 0.6163137829622602, "weights": [0.016702152045755578]}

    assert stabilize_floats(left) == stabilize_floats(right)


def test_stabilize_floats_preserves_material_differences_and_non_floats() -> None:
    value = {"score": 0.6163137829622, "enabled": True, "count": 3}

    stable = stabilize_floats(value)

    assert stable == value
