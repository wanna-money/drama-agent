def test_character_view_has_face():
    from drama_agent.db.enums import CharacterView

    assert CharacterView.FACE.value == "face"


def test_look_model_has_face_key_column():
    from drama_agent.db.models import Look

    assert "face_key" in Look.__table__.columns
