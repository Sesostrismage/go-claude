# Go Teacher

Play Go against KataGo's human-style AI in your browser, with Claude sitting
next to you as a coach. The opponent plays at whatever rank you choose, and a
side panel gives you commentary, hints, and move suggestions — all grounded in
real KataGo analysis rather than invented evaluations.

## What it does

- **Play a full game** on a 9×9, 13×13, or 19×19 board, as Black or White.
- **Human-style opponent.** Moves are sampled from KataGo's human-style network
  (`b18c384nbt-humanv0`) at a rank you pick, from 20 kyu up to 3 dan, so the AI
  feels like an opponent near your level instead of a superhuman engine.
- **A coach powered by Claude.** Every position is analysed by KataGo's main
  network, and that analysis is fed to Claude so its advice reflects the actual
  board. Four ways to use it:
  - **Comment** — grade your most recent move (good, questionable, or a
    mistake) and explain why, including how many points it cost versus the best
    move.
  - **Hint** — a Socratic nudge toward the right area, without giving away a
    move.
  - **Suggest move** — the top KataGo candidate with coordinates and a plain
    explanation of why it works.
  - **Chat** — ask the coach anything about the position.
- **Auto-comment toggle.** Have the coach comment automatically after each of
  your moves.
- **Live winrate and score bar** under the board, plus capture counts, and a
  final result when the game ends (KataGo's score estimate after two passes,
  or e.g. "W+R" after a resignation).
- **Winrate graph** of the whole game under the board — click any point to
  jump to that position.
- **Game review navigation.** Step through the game move by move (◀ ▶) while
  the live game waits; the board, winrate, and territory update to the viewed
  position.
- **Territory overlay.** Toggle KataGo's live ownership map to see which areas
  each side controls.
- **Undo and Resign.** Take back your last move (and the AI's reply), or end
  the game.
- **SGF export.** Download the game to review in other tools or upload to Go
  servers.
- **Move numbers toggle** on the stones, and an optional **confirm-move mode**
  (click once to preview, click again to submit — prevents misclicks;
  right-click cancels).
- **Pick the coach model** (Sonnet, Opus, or Haiku) from a dropdown; Sonnet is
  the default.

## Requirements

- **Windows** with a reasonably modern GPU (the OpenCL build of KataGo runs on
  most GPUs; CUDA and CPU builds are also available).
- **Python 3.10+**.
- Python packages: `flask` and `anthropic`.
- **KataGo** plus two networks (see installation below).
- An **Anthropic API key** for the coach features. Without one the game still
  plays; only the coaching is disabled.

## Installation

1. **Install the Python dependencies.**

   ```
   pip install -r requirements.txt
   ```

2. **Download KataGo.** Grab the OpenCL Windows build from the
   [KataGo releases page](https://github.com/lightvector/KataGo/releases)
   (`katago-vX.Y.Z-opencl-windows-x64.zip`) and unzip it into a `katago/`
   folder at the project root, so `katago/katago.exe` exists.

3. **Download the two networks** into the same `katago/` folder:
   - **Main network** from [katagotraining.org/networks](https://katagotraining.org/networks/)
     — the strongest confidently-rated `b18c384nbt` network (`.bin.gz`), saved
     as `kata1-b18c384nbt-latest.bin.gz`.
   - **Human-style network** from the KataGo releases page (v1.15.0+):
     `b18c384nbt-humanv0.bin.gz`.

4. **Get an Anthropic API key.** Sign in at the
   [Anthropic Console](https://console.anthropic.com), then go to
   [API Keys](https://console.anthropic.com/settings/keys) and create a new
   key (it starts with `sk-ant-`). You'll need to set up billing on the
   account, since coach requests are billed per use. Copy the key when it's
   shown — you won't be able to view it again afterwards. See the
   [official quickstart](https://docs.claude.com/en/docs/get-started) for more
   detail.

5. **Provide the API key** in any one of these ways:
   - Create a `.env` file at the project root containing
     `ANTHROPIC_API_KEY=sk-ant-...`, or
   - Set an `ANTHROPIC_API_KEY` environment variable, or
   - Fill in `ANTHROPIC_API_KEY` in `goteacher/config.py`.

The file paths in `goteacher/config.py` are resolved relative to the project
root, so as long as your `katago/` folder and the model filenames match the
names above, no path editing is needed. If your filenames differ, adjust
`goteacher/config.py`.

## Usage

From the project root:

```
python go_teacher.py
```

Then open <http://localhost:8123> in your browser.

The first launch with OpenCL spends a few minutes auto-tuning KataGo for your
GPU. This happens only once.

In the browser: choose board size, opponent rank, and your colour, then click
**New game**. Click an intersection to play. Use the coach buttons or the chat
box at any time, and flip the coach model with the dropdown if you want a
stronger or faster coach.

During and after the game: use **Undo / Resign / SGF** in the status bar, the
◀ ▶ buttons (or a click on the winrate graph) to review earlier positions, and
the **Confirm moves / Move numbers / Territory** checkboxes to tune the board.
Reviewing never alters the game — jump back to the latest move to keep
playing.

## Configuration

All settings live in `goteacher/config.py`:

| Setting | Purpose | Default |
| --- | --- | --- |
| `KATAGO_EXE`, `MAIN_MODEL`, `HUMAN_MODEL` | Paths to the KataGo executable and networks, relative to the project root | `katago/…` |
| `ANTHROPIC_API_KEY` | Inline API key (usually left blank in favour of `.env` or an env var) | `""` |
| `COACH_MODELS` | Label → model-string map offered in the UI dropdown | Sonnet / Opus / Haiku |
| `DEFAULT_COACH_MODEL` | Which of the above is preselected | Sonnet |
| `PORT` | Local web server port | `8123` |
| `ANALYSIS_VISITS` | KataGo visits per analysis query (higher = stronger and slower) | `150` |

## Project layout

```
go_teacher.py          Entry point — just launches the server
goteacher/
  config.py            Paths, models, and server settings
  rules.py             Go rules and board state (Game)
  engine.py            KataGo process wrapper (analysis + human-style moves)
  coach.py             Claude-powered coach
  server.py            Flask app, routes, and main()
  templates/
    index.html         Browser frontend (board, controls, coach panel)
katago/                KataGo executable and networks (not tracked in git)
```

## How the coaching stays accurate

After every move the board position is sent to KataGo and the analysis is
stored. When you ask the coach something, the relevant analysis snapshots are
passed to Claude with each one explicitly labelled: which move it follows, who
played that move (you or the opponent), whose turn it is, and therefore which
colour the listed candidate moves belong to. The current position is always
marked as the one matching the on-screen winrate bar. This keeps the coach from
confusing whose move was whose or mixing up an earlier position with the one in
front of you.

Alongside the winrate and score, the coach receives KataGo's **expected
continuation** for each candidate move (so it can cite the sequence the engine
actually predicts instead of imagining one) and a regional summary of KataGo's
**ownership estimate** (so claims about whose area is whose come from the
engine). It is instructed to treat all of these as authoritative over its own
impression of the board, and to say so plainly rather than guess when something
would require reading out a sequence.

### A caveat worth reading

The numbers are trustworthy — point loss, winrate, score lead, and which move
KataGo prefers are engine output passed through unchanged. The *explanations*
are a language model's narration of those numbers, and that layer is the weak
link: LLMs are unreliable at Go-specific reasoning and can produce fluent,
plausible-sounding commentary that is simply wrong, especially about ladders,
capturing races, and life and death. The measures above narrow the room for
invention but do not eliminate it. Treat the coach as a helpful study partner
that is sometimes confidently mistaken, not as an authority — and if a stronger
player tells you it said something silly, believe the player.

## Troubleshooting

- **"KataGo exited during startup."** Almost always a wrong model path or a
  config issue. Check the `[katago]` log lines printed in the terminal.
- **Coach says it's unavailable.** No Anthropic API key was found. Add one via
  `.env`, an environment variable, or `config.py`.
- **"human model not found" warning.** The `b18c384nbt-humanv0.bin.gz` file
  isn't where expected; the opponent falls back to the main network with
  reduced visits. Put the human-style network in `katago/`.

## License

Released under the [MIT License](LICENSE) — you're free to use, copy, modify,
and distribute it for any purpose, including commercially, as long as the
copyright and license notice are kept.
