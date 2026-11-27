"""Verify the app starts the FlashHead server itself when none is running."""
import sys
import time
import tkinter as tk

sys.path.insert(0, r"C:\Users\mosas.ASUS-GAMING\lip_sync_service")
from realtime_app import App

AVATAR = r"C:\AvatarProject\avatar_grid\Jinx.png"

root = tk.Tk()
app = App(root)
app.avatar_path = AVATAR
app.avatar_var.set(AVATAR)
app.connect_server()

t0 = time.time()
last = [None]


def tick():
    st = app.status.cget("text")
    if st != last[0]:
        last[0] = st
        print("%6.1fs  %s" % (time.time() - t0, st), flush=True)
    if app.connected:
        print("CONNECTED after %.1fs" % (time.time() - t0), flush=True)
        root.after(200, root.destroy)
        return
    if time.time() - t0 > 480:
        print("TIMEOUT", flush=True)
        root.destroy()
        return
    root.after(500, tick)


root.after(300, tick)
root.mainloop()
