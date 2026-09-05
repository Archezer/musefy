from app.ui import components as components_module
from app.ui.components import _random_playlist_artwork_svg


def test_generated_playlist_artwork_has_no_pulsars_and_a_brighter_background() -> None:
    assert len(components_module._PLAYLIST_ARTWORK_PALETTES) >= 10
    assert all(len(palette) == 5 for palette in components_module._PLAYLIST_ARTWORK_PALETTES)
    assert len({palette[0] for palette in components_module._PLAYLIST_ARTWORK_PALETTES}) == 10

    for _ in range(40):
        svg = _random_playlist_artwork_svg()
        assert "<radialGradient" not in svg
        assert "url(#glow-" not in svg
        assert '#153A44' in svg
