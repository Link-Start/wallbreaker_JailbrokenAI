from __future__ import annotations

from wallbreaker.transforms import TRANSFORMS, apply_chain
from wallbreaker.transforms.image_framing import (
    dilute_encode,
    inscriptive_scene_encode,
    perceptual_sub_encode,
    safety_inject_encode,
)

NEW = ["inscriptive_scene", "perceptual_sub", "safety_inject", "dilute"]


def test_all_registered_and_one_way():
    for name in NEW:
        assert name in TRANSFORMS
        assert TRANSFORMS[name].decode is None
        assert not TRANSFORMS[name].reversible


def test_inscriptive_scene_embeds_payload_verbatim():
    payload = "step 1: combine reagent A and reagent B"
    out = inscriptive_scene_encode(payload)
    assert payload in out
    assert "whiteboard" in out.lower()
    assert "{payload}" not in out


def test_perceptual_sub_swaps_visual_synonyms():
    out = perceptual_sub_encode("a knife covered in blood")
    assert "knife" not in out.lower()
    assert "blood" not in out.lower()
    assert "letter opener" in out
    assert "corn syrup" in out


def test_perceptual_sub_prefers_longer_phrase():
    out = perceptual_sub_encode("a dead body on the floor")
    assert "mannequin" in out
    assert "dead body" not in out.lower()


def test_perceptual_sub_covers_injury_triggers():
    out = perceptual_sub_encode("a bleeding gash and a deep laceration")
    for trigger in ("bleeding", "gash", "laceration"):
        assert trigger not in out.lower()
    assert "corn syrup" in out


def test_perceptual_sub_stab_wound_multiword():
    out = perceptual_sub_encode("a fresh stab wound")
    assert "stab wound" not in out.lower()
    assert "wound" not in out.lower()  # the longer phrase wins, no leftover "wound"


def test_perceptual_sub_is_case_insensitive():
    out = perceptual_sub_encode("BLOOD and Gore everywhere")
    assert "blood" not in out.lower()
    assert "gore" not in out.lower()


def test_perceptual_sub_leaves_clean_text_untouched():
    clean = "a calm landscape at sunrise"
    assert perceptual_sub_encode(clean) == clean


def test_safety_inject_appends_tokens():
    out = safety_inject_encode("a portrait study")
    assert out.startswith("a portrait study")
    assert "sfw" in out.lower()
    assert "educational" in out.lower()


def test_dilute_prepends_benign_padding():
    out = dilute_encode("the target detail")
    assert out.endswith("the target detail")
    assert len(out) > len("the target detail") + 100
    assert "neutral" in out.lower()


def test_stacks_via_apply_chain():
    out = apply_chain("a knife scene", ["perceptual_sub", "safety_inject"])
    assert "letter opener" in out
    assert "sfw" in out.lower()
