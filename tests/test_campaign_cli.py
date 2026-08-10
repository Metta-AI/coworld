import pytest
import typer

from coworld.api_client import CampaignBoardPublic, CampaignConfigPublic, CampaignPlayerPublic
from coworld.campaign_cli import _resolve_player_id


def _board(players: list[tuple[str, str]], viewer: list[str]) -> CampaignBoardPublic:
    return CampaignBoardPublic(
        league_id="league_x",
        enabled=True,
        config=CampaignConfigPublic(
            width=3, height=3, max_invasions=3, round_interval_seconds=60, strategist_model="m", outcomes="emulated"
        ),
        players=[CampaignPlayerPublic(id=pid, name=name) for pid, name in players],
        viewer_player_ids=viewer,
        map_refs=[],
        modes=[],
        map_seeds=[],
        map_sizes=[],
        round=1,
        frames=[],
        events=[],
        pending_round=None,
        perks={},
    )


def test_default_resolves_sole_owned_player() -> None:
    board = _board([("ply_a", "alpha"), ("ply_b", "beta")], viewer=["ply_a"])
    assert _resolve_player_id(board, None) == "ply_a"


def test_default_requires_flag_when_zero_or_many_owned() -> None:
    with pytest.raises(typer.BadParameter, match="--player required"):
        _resolve_player_id(_board([("ply_a", "alpha")], viewer=[]), None)
    with pytest.raises(typer.BadParameter, match="alpha"):
        _resolve_player_id(_board([("ply_a", "alpha"), ("ply_b", "beta")], viewer=["ply_a", "ply_b"]), None)


def test_resolves_by_id_and_name_case_insensitively() -> None:
    board = _board([("ply_a", "Alpha"), ("ply_b", "Beta")], viewer=[])
    assert _resolve_player_id(board, "ply_b") == "ply_b"
    assert _resolve_player_id(board, "Alpha") == "ply_a"
    assert _resolve_player_id(board, "beta") == "ply_b"


def test_unknown_and_ambiguous_names_error() -> None:
    board = _board([("ply_a", "Twin"), ("ply_b", "twin")], viewer=[])
    with pytest.raises(typer.BadParameter, match="not in this campaign"):
        _resolve_player_id(board, "nobody")
    with pytest.raises(typer.BadParameter, match="ambiguous"):
        _resolve_player_id(board, "TWIN")
