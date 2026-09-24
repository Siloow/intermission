# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["syphon-python", "numpy"]
# ///
"""Syphon -> Blender bridge for the venue previz.

    uv run syphon_bridge.py --list          # show Syphon servers
    uv run syphon_bridge.py                 # first server whose name/app contains "Arena"
    uv run syphon_bridge.py Resolume        # match by name or app name
    uv run syphon_bridge.py --demo          # moving test pattern, no Syphon needed

Blender's Python (3.13) has no syphon-python build, so this runs as its own
process under uv (Python 3.12) and hands frames over through a memory-mapped
file, .live/screen.rgba next to this script:

    16-byte header  b"VSCR", width, height, frame counter (uint32 LE)
    width*height*4  RGBA8, rows bottom-up (Blender's order)

venue_live.py inside Blender polls that file. Frames are scaled to --size
(default 960x540 at 30 fps): the previz needs to show what's on the screen, not
full res, and every pixel costs time in Blender's image upload.
"""
import argparse, math, os, struct, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, ".live", "screen.rgba")
HEADER = struct.Struct("<4sIII")


class Sink:
    def __init__(self, w, h):
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        self.w, self.h, self.frame = w, h, 0
        self.mm = np.memmap(OUT, np.uint8, "w+", shape=HEADER.size + w * h * 4)
        self.px = self.mm[HEADER.size:].reshape(h, w, 4)
        self.mm[:HEADER.size] = np.frombuffer(HEADER.pack(b"VSCR", w, h, 0), np.uint8)
        self._ys = self._xs = None
        self._src = None

    def write_topdown(self, img, bgra=False):
        """img: (H, W, 4) uint8, top row first (Metal / Syphon order)."""
        sh, sw = img.shape[:2]
        if self._src != (sh, sw):
            self._src = (sh, sw)
            # nearest-neighbour index maps, flipped vertically for Blender
            self._ys = ((np.arange(self.h)[::-1] + 0.5) * sh / self.h).astype(np.intp)
            self._xs = ((np.arange(self.w) + 0.5) * sw / self.w).astype(np.intp)
        small = img[self._ys[:, None], self._xs[None, :]]
        if bgra:
            self.px[..., 0] = small[..., 2]
            self.px[..., 1] = small[..., 1]
            self.px[..., 2] = small[..., 0]
        else:
            self.px[..., :3] = small[..., :3]
        self.px[..., 3] = 255
        self.frame = (self.frame + 1) & 0xFFFFFFFF
        # counter last, so the reader sees a new number only after the pixels
        self.mm[:HEADER.size] = np.frombuffer(HEADER.pack(b"VSCR", self.w, self.h, self.frame), np.uint8)


def demo(sink, fps=30):
    """Moving bands + a sweeping bar: enough to see motion and colour on the screen."""
    h, w = 540, 960
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    print(f"[bridge] demo pattern -> {OUT}  (ctrl-c to stop)")
    t0 = time.monotonic()
    while True:
        t = time.monotonic() - t0
        img = np.empty((h, w, 4), np.uint8)
        ph = x / w * 6.283 + t
        img[..., 0] = (127 + 127 * np.sin(ph)).astype(np.uint8)
        img[..., 1] = (127 + 127 * np.sin(ph + 2.1 + y / h * 3)).astype(np.uint8)
        img[..., 2] = (127 + 127 * np.sin(ph + 4.2)).astype(np.uint8)
        bar = int((t * 0.25 % 1.0) * w)
        img[:, max(0, bar - 12):bar + 12, :3] = 255
        img[: h // 12, : int(w * (0.5 + 0.5 * math.sin(t))), :3] = 255  # "top" marker
        sink.write_topdown(img)
        time.sleep(1 / fps)


def list_servers(directory):
    """directory.servers from syphon-python 0.1.1 raises KeyError for any server
    that publishes no icon, so read the raw descriptions ourselves."""
    from syphon.server_directory import SyphonServerDescription
    directory.update_run_loop()
    raw = directory._syphonServerDirectoryObjC.sharedDirectory().servers()
    return [SyphonServerDescription(str(s.get("SyphonServerDescriptionUUIDKey")),
                                    str(s.get("SyphonServerDescriptionNameKey") or ""),
                                    str(s.get("SyphonServerDescriptionAppNameKey") or ""),
                                    s.get("SyphonServerDescriptionIconKey"), s)
            for s in raw]


def pick_server(directory, query):
    servers = list_servers(directory)
    if not servers:
        return None, servers
    if query is None:
        query = "Arena"
    q = query.lower()
    for s in servers:
        if q in s.name.lower() or q in s.app_name.lower():
            return s, servers
    return None, servers


def run_syphon(sink, query, fps_cap):
    import Metal
    from syphon import SyphonMetalClient, SyphonServerDirectory
    from syphon.utils.raw import copy_mtl_texture_to_bytes

    directory = SyphonServerDirectory()
    directory.run_loop_interval = 0.2
    client, desc, last_report, frames = None, None, time.monotonic(), 0
    while True:
        if client is None or not client.is_valid:
            if client is not None:
                print(f"[bridge] lost '{desc.app_name} - {desc.name}', searching again")
                client = None
            desc, servers = pick_server(directory, query)
            if desc is None:
                names = ", ".join(f"'{s.app_name} - {s.name}'" for s in servers) or "none"
                print(f"[bridge] no server matching '{query or 'Arena'}' (have: {names}); retrying")
                time.sleep(2)
                continue
            client = SyphonMetalClient(desc)
            print(f"[bridge] receiving '{desc.app_name} - {desc.name}' -> {OUT}")

        if client.has_new_frame:
            tex = client.new_frame_image
            data = copy_mtl_texture_to_bytes(tex)
            img = np.frombuffer(data, np.uint8).reshape(tex.height(), tex.width(), 4)
            sink.write_topdown(img, bgra=tex.pixelFormat() == Metal.MTLPixelFormatBGRA8Unorm)
            frames += 1
            time.sleep(1 / fps_cap)
        else:
            time.sleep(0.002)

        now = time.monotonic()
        if now - last_report > 5:
            print(f"[bridge] {frames / (now - last_report):.1f} fps")
            frames, last_report = 0, now


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("server", nargs="?", help="Syphon server name or app name to match (default: Arena)")
    ap.add_argument("--list", action="store_true", help="list Syphon servers and exit")
    ap.add_argument("--demo", action="store_true", help="send a test pattern instead of Syphon")
    ap.add_argument("--size", default="960x540", help="frame size handed to Blender, WxH")
    ap.add_argument("--fps", type=float, default=30, help="max frames per second to Blender")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    if a.list:
        from syphon import SyphonServerDirectory
        directory = SyphonServerDirectory()
        directory.run_loop_interval = 0.5
        for _ in range(4):               # servers answer discovery asynchronously
            servers = list_servers(directory)
        for s in servers:
            print(f"  app='{s.app_name}'  name='{s.name}'")
        if not servers:
            print("  (no Syphon servers - is Resolume's Syphon output on?)")
        return

    w, h = (int(v) for v in a.size.lower().split("x"))
    sink = Sink(w, h)
    try:
        demo(sink) if a.demo else run_syphon(sink, a.server, a.fps)
    except KeyboardInterrupt:
        print("\n[bridge] stopped")


if __name__ == "__main__":
    main()
