from agent_runner.ascii_anim import ANIMATIONS, random_animation


def test_animation_library_is_populated() -> None:
    assert len(ANIMATIONS) >= 10
    assert any(animation.name == "baseball" for animation in ANIMATIONS)


def test_each_animation_has_multiple_frames() -> None:
    for animation in ANIMATIONS:
        assert len(animation.frames) >= 4
        assert all(frame.strip() for frame in animation.frames)


def test_random_animation_returns_known_animation() -> None:
    animation = random_animation()
    assert animation in ANIMATIONS
