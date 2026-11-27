"""
Test script: run FlashHead lip-sync in real-time GUI mode.
Talks to Sapphire's existing FlashHead server (http://127.0.0.1:5017) via HTTP.
The Sapphire plugin itself is NOT modified.

Usage:
    python test_existing.py --audio C:\path\to\audio.mp3 --avatar C:\path\to\avatar.png

Defaults: Jinx.png + lauren-crazy.mp3 -> shows live lip-sync window
"""
import sys
import os

# Add lib path
sys.path.insert(0, str(Path(__file__).parent))

from realtime_app import FlashHeadApp

def main():
    root = Tk()
    app = FlashHeadApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()