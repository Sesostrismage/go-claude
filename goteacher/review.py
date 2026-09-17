"""Swing ledger: which moves changed the game, according to KataGo.

analysis_history[k] is KataGo's analysis of the position after the first k
moves, so move i (game.moves[i]) took the game from position i to position
i + 1. Comparing what KataGo expected from its best move at position i with
what actually happened at position i + 1 gives the cost of the move.

Nothing here is stored: everything is derived from analysis_history on
demand, so undo (which truncates the history) keeps the ledger consistent for
free, and re-analysing a position at more visits automatically sharpens every
swing that touches it.
"""

from .config import MISTAKE_CONFIRM_VISITS, MISTAKE_POINTS_BY_SIZE, MISTAKE_WINRATE


def mistake_points(size):
    """Point loss that counts as a big mistake on this board size."""
    return MISTAKE_POINTS_BY_SIZE.get(size, max(MISTAKE_POINTS_BY_SIZE.values()))


def is_big(swing, size):
    return swing["loss"] >= mistake_points(size) or swing["wr_drop"] >= MISTAKE_WINRATE


def move_swing(game, i):
    """What game.moves[i] cost the side that played it, or None if the
    analyses on either side of it are missing.

    'loss' is in points, versus KataGo's best candidate before the move (the
    same yardstick the coach quotes as "cost vs best move"). 'wr_drop' is the
    change in the mover's winrate between the two positions, i.e. what the
    winrate graph shows. Both are positive when the move hurt the mover.
    """
    if i < 0 or i >= len(game.moves) or i + 1 >= len(game.analysis_history):
        return None
    before, after = game.analysis_history[i], game.analysis_history[i + 1]
    infos = before.get("moveInfos")
    if not infos or "rootInfo" not in before or "rootInfo" not in after:
        return None
    color, gtp = game.moves[i]
    sign = 1 if color == "B" else -1  # KataGo numbers are Black-positive
    best = infos[0]
    wr_before = before["rootInfo"].get("winrate", 0.5)
    wr_after = after["rootInfo"].get("winrate", 0.5)
    visits = min(
        before["rootInfo"].get("visits", 0), after["rootInfo"].get("visits", 0)
    )
    player_letter = "B" if game.player_color == "black" else "W"
    swing = {
        "index": i,
        "move_no": i + 1,
        "k": i + 1,  # analysis/position index just after the move
        "color": color,
        "gtp": gtp,
        "by_player": color == player_letter,
        "loss": sign * (best["scoreLead"] - after["rootInfo"]["scoreLead"]),
        "wr_drop": sign * (wr_before - wr_after),
        "wr_before": wr_before,
        "wr_after": wr_after,
        "best_move": best["move"],
        "best_pv": (best.get("pv") or [])[:6],
        "confirmed": visits >= MISTAKE_CONFIRM_VISITS,
    }
    swing["big"] = is_big(swing, game.size)
    return swing


def all_swings(game):
    return [s for s in (move_swing(game, i) for i in range(len(game.moves))) if s]


def key_moments(game, n_player=3, n_opponent=2):
    """The biggest confirmed-or-not mistakes by each side, in chronological
    order: up to n_player by the player and n_opponent by the opponent, ranked
    by points lost. Only swings above the big-mistake threshold qualify."""
    big = [s for s in all_swings(game) if s["big"]]
    by_loss = sorted(big, key=lambda s: -s["loss"])
    chosen = [s for s in by_loss if s["by_player"]][:n_player]
    chosen += [s for s in by_loss if not s["by_player"]][:n_opponent]
    return sorted(chosen, key=lambda s: s["index"])


def unconfirmed_positions(game, swings):
    """Analysis indices around the given swings that were searched with fewer
    visits than a confirmation needs."""
    ks = set()
    for s in swings:
        for k in (s["index"], s["index"] + 1):
            visits = game.analysis_history[k].get("rootInfo", {}).get("visits", 0)
            if visits < MISTAKE_CONFIRM_VISITS:
                ks.add(k)
    return ks
