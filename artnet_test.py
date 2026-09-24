"""Send test Art-Net to the venue previz, standing in for Resolume.

    python3 artnet_test.py                  # rainbow chase on universe 0 -> 127.0.0.1
    python3 artnet_test.py --look red       # hold one look: red, blue, white, warm, off
    python3 artnet_test.py --host 2.0.0.50  # aim at a real node instead

Six RGBW pars at addresses 1, 6, 11, 16, 21, 26, channel order r g b w dim;
the same patch build_venue.py gives the Blender pars. Standard library only.
"""
import argparse, colorsys, math, socket, time

PARS, FOOTPRINT, START = 6, 5, 1
LOOKS = {
    "red": (255, 0, 0, 0, 255),
    "blue": (0, 40, 255, 0, 255),
    "white": (0, 0, 0, 255, 255),
    "warm": (255, 90, 10, 120, 200),
    "off": (0, 0, 0, 0, 0),
}


def artdmx(universe, seq, dmx):
    return (b"Art-Net\x00" + (0x5000).to_bytes(2, "little") + (14).to_bytes(2, "big")
            + bytes([seq, 0, universe & 0xFF, universe >> 8]) + len(dmx).to_bytes(2, "big") + bytes(dmx))


def chase(t, i):
    h = (t * 0.2 + i / PARS) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 1, 1)
    dim = 0.5 + 0.5 * math.sin(t * 3 + i)
    return int(r * 255), int(g * 255), int(b * 255), 0, int(dim * 255)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--universe", type=int, default=0)
    ap.add_argument("--look", choices=sorted(LOOKS))
    ap.add_argument("--fps", type=float, default=40)
    a = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    print(f"Art-Net -> {a.host}:6454 universe {a.universe} ({a.look or 'chase'}), ctrl-c to stop")
    t0, seq = time.monotonic(), 1
    try:
        while True:
            t = time.monotonic() - t0
            dmx = bytearray(512)
            for i in range(PARS):
                vals = LOOKS[a.look] if a.look else chase(t, i)
                o = START - 1 + i * FOOTPRINT
                dmx[o:o + FOOTPRINT] = bytes(vals)
            sock.sendto(artdmx(a.universe, seq, dmx), (a.host, 6454))
            seq = seq % 255 + 1
            time.sleep(1 / a.fps)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
