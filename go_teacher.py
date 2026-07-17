#!/usr/bin/env python3
"""
Go Teacher - play against KataGo's human-style AI with Claude as your coach.

Play in your browser. The opponent plays at a rank you choose (via KataGo's
human-style network). A coach panel gives commentary, hints, and move
suggestions grounded in real KataGo analysis - on demand via buttons, or
automatically if you enable the toggle.

SETUP (one time):
1. pip install flask anthropic
2. Download KataGo and unzip it somewhere:
   https://github.com/lightvector/KataGo/releases
   Pick the build that matches your hardware - the OpenCL build
   (katago-vX.Y.Z-opencl-windows-x64.zip) runs on most GPUs; there are
   also CUDA and CPU (Eigen) builds.
3. Download two networks:
   - Main network: https://katagotraining.org/networks/
     (grab the strongest confidently-rated b18c384nbt network, .bin.gz)
   - Human-style network: from the KataGo releases page (v1.15.0+):
     b18c384nbt-humanv0.bin.gz
4. Fill in the paths in goteacher/config.py.
5. Run:  python go_teacher.py   then open http://localhost:8123

First launch with OpenCL will spend a few minutes auto-tuning for your GPU.
This only happens once.

Code layout: this file is just the entry point. The implementation lives in
the goteacher/ package:
  goteacher/config.py    - paths, model, and server settings
  goteacher/rules.py     - Go rules and board state (Game)
  goteacher/engine.py    - KataGo process wrapper
  goteacher/coach.py     - Claude-powered coach
  goteacher/server.py    - Flask app, routes, and main()
  goteacher/templates/   - browser frontend (index.html)
"""

from goteacher.server import main

if __name__ == "__main__":
    main()
