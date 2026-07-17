"""The Claude-powered coach that comments on and answers questions about the game."""

import os
import sys

try:
    import anthropic
except ImportError:
    print("Missing dependency: pip install anthropic")
    sys.exit(1)

from .config import ANTHROPIC_API_KEY, COACH_MODELS, DEFAULT_COACH_MODEL, PROJECT_ROOT
from .rules import Game


class Coach:
    def __init__(self):
        key = ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            env_path = os.path.join(PROJECT_ROOT, ".env")
            if os.path.exists(env_path):
                for line in open(env_path):
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY"):
                        key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
        if not key:
            print("WARNING: no Anthropic API key found - coach features disabled.")
            print("Set the ANTHROPIC_API_KEY env var or create a .env file (see docs).")
            self.client = None
        else:
            self.client = anthropic.Anthropic(api_key=key)
        self.chat_history = []

    @staticmethod
    def _fmt_analysis(a):
        if not a:
            return "No analysis available."
        root = a.get("rootInfo", {})
        lines = [
            f"Black winrate: {root.get('winrate', 0) * 100:.1f}%, "
            f"Black score lead: {root.get('scoreLead', 0):+.1f}"
        ]
        for mi in a.get("moveInfos", [])[:4]:
            lines.append(
                f"  candidate {mi['move']}: winrate {mi['winrate']*100:.1f}%, "
                f"score lead {mi['scoreLead']:+.1f}, visits {mi['visits']}"
            )
        return "\n".join(lines)

    @staticmethod
    def _describe_position(game: Game, k):
        """Describe the position that analysis_history[k] refers to: the
        position after the first k moves of the game. Returns (description,
        color to move)."""
        user_letter = "B" if game.player_color == "black" else "W"
        if k == 0:
            desc = "the EMPTY BOARD, before any move was played"
        else:
            c, m = game.moves[k - 1]
            who = "Weppe" if c == user_letter else "the AI opponent"
            desc = f"the position just after move {k} ({c} {m}, played by {who})"
        to_move = "Black" if k % 2 == 0 else "White"  # Black plays move 1
        return desc, to_move

    def _base_context(self, game: Game, snapshots, point_loss):
        user_letter = "B" if game.player_color == "black" else "W"
        if game.moves:
            moves_str = ", ".join(
                f"{i + 1}. {c} {m} ({'Weppe' if c == user_letter else 'opponent'})"
                for i, (c, m) in enumerate(game.moves)
            )
        else:
            moves_str = "(no moves yet)"
        user_move, opp_reply = None, None
        for i in range(len(game.moves) - 1, -1, -1):
            if game.moves[i][0] == user_letter:
                user_move = f"{game.moves[i][0]} {game.moves[i][1]} (move {i+1})"
                if i + 1 < len(game.moves):
                    opp_reply = (
                        f"{game.moves[i+1][0]} {game.moves[i+1][1]} (move {i+2})"
                    )
                break
        loss_str = (
            f"{point_loss:+.1f} points vs best move"
            if point_loss is not None
            else "n/a"
        )
        perspective = (
            "Weppe is BLACK, so higher Black winrate = better for Weppe."
            if game.player_color == "black"
            else "Weppe is WHITE, so LOWER Black winrate = better for Weppe (e.g. Black winrate 30% means Weppe is clearly winning). A negative Black score lead means Weppe (White) is ahead."
        )
        sections = []
        for k, a in snapshots:
            desc, to_move = self._describe_position(game, k)
            current_note = (
                " This is the CURRENT position: these numbers are what Weppe's on-screen winrate bar and score show right now."
                if k == len(game.moves)
                else ""
            )
            sections.append(
                f"KataGo analysis of {desc}. {to_move} was to move in this position, so the candidate moves below are options for {to_move} only.{current_note}\n"
                f"{self._fmt_analysis(a)}"
            )
        analysis_block = "\n\n".join(sections) if sections else "No analysis available."
        return f"""You are a friendly, direct Go teacher coaching player "Weppe" during a live game on a {game.size}x{game.size} board. Weppe plays {game.player_color}. The opponent is an AI playing at human {game.rank.replace('rank_', '')} level. Komi {game.komi}.

Current board (the position after ALL moves listed below):
{game.ascii_board()}

Move history, in the order played, each tagged with who played it:
{moves_str}
Weppe's most recent move: {user_move or 'none yet'} (estimated cost: {loss_str})
The opponent's reply after it: {opp_reply or 'none yet'}

IMPORTANT: Moves marked "{user_letter}" are Weppe's; the other color is the AI opponent's. Never attribute the opponent's moves to Weppe or vice versa. When discussing an earlier position, remember which stones had NOT yet been played at that time - e.g. in the position before Weppe's most recent move, neither that move nor the opponent's reply was on the board.

{analysis_block}

All winrates and score leads are from BLACK's perspective. {perspective}
When citing winrates, always say which position they belong to (before your move / after your move / now). The numbers Weppe sees on screen belong to the CURRENT position only.
Ground everything you say in this analysis - do not invent evaluations. Be concise (2-4 sentences unless asked for more). Talk like a teacher at the board, not a textbook."""

    def ask(self, mode, game, snapshots, point_loss, question=None, model=None):
        """Ask the coach. snapshots is a chronological list of
        (moves_played, analysis) pairs taken from game.analysis_history."""
        if not self.client:
            return "Coach unavailable: no API key configured."
        # Only accept models offered in the UI; anything else falls back to the default.
        model = model if model in COACH_MODELS.values() else DEFAULT_COACH_MODEL
        instructions = {
            "comment": "Comment on Weppe's most recent move: was it good, questionable, or a mistake? Why? Reference what the position needed.",
            "hint": "Weppe wants a hint for the CURRENT position (it is their turn). Do NOT reveal any specific move or coordinates. Give a Socratic, directional hint - e.g. which area deserves attention, or what question to ask about the position.",
            "suggest": "Suggest the best move for Weppe in the current position (use the top KataGo candidate from the CURRENT position's analysis), give its coordinates, and explain in plain terms WHY it works and what it accomplishes.",
            "chat": f"Weppe asks: {question}",
        }
        prompt = self._base_context(game, snapshots, point_loss)
        prompt += "\n\nTask: " + instructions[mode]
        messages = self.chat_history[-6:] + [{"role": "user", "content": prompt}]
        resp = self.client.messages.create(
            model=model, max_tokens=500, messages=messages
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        # Stamp history entries with the move count so earlier answers (about
        # earlier positions) can't be mistaken for current-position advice.
        stamp = f"(asked at move {len(game.moves)}) "
        self.chat_history.append(
            {
                "role": "user",
                "content": stamp + (instructions[mode] if mode != "chat" else question),
            }
        )
        self.chat_history.append({"role": "assistant", "content": text})
        return text
