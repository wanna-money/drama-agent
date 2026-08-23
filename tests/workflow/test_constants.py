from drama_agent.workflow.constants import (
    ShotType, CameraMovement, ReferenceRole,
    MAX_SHOT_DURATION, DEFAULT_SHOT_DURATION, SHOT_TYPE_DESC,
)


def test_shot_type_values():
    assert {t.value for t in ShotType} == {"ELS", "LS", "MS", "CU", "ECU"}


def test_camera_movement_values():
    assert {c.value for c in CameraMovement} == {
        "static", "pan", "tilt", "dolly", "zoom", "tracking", "crane"}


def test_reference_role_values():
    assert {r.value for r in ReferenceRole} == {
        "first_frame", "last_frame", "subject_reference",
        "reference_image", "reference_video", "reference_audio"}


def test_duration_constants():
    assert MAX_SHOT_DURATION == 10
    assert DEFAULT_SHOT_DURATION == 5
    assert DEFAULT_SHOT_DURATION <= MAX_SHOT_DURATION


def test_shot_type_desc_covers_all_types():
    for t in ShotType:
        assert t.value in SHOT_TYPE_DESC and SHOT_TYPE_DESC[t.value]
