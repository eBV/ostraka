#!/usr/bin/env python3
"""Build packs/demo.pack: ~10 hand-written articles covering eval questions.

Used for the eval harness smoke test, CI emulator runs, and Test Lab.
Regenerate with: python3 build_demo_pack.py
"""

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_pack

ARTICLES = {
"Tungsten": """'''Tungsten''', also known as '''wolfram''', is a [[chemical element]] with the symbol '''W''' and [[atomic number]] 74.
== Properties ==
Tungsten has the highest [[melting point]] of all known elements, 3422&#160;°C. Carbon sublimes rather than melting at atmospheric pressure, so tungsten holds the melting-point record among metals and all elements that melt.
== Uses ==
Its high melting point makes tungsten ideal for [[incandescent light bulb]] filaments, [[arc welding]] electrodes, and [[X-ray]] tube targets.
""",
"Harry S. Truman": """'''Harry S. Truman''' (May 8, 1884 – December 26, 1972) was the 33rd [[president of the United States]], serving from 1945 to 1953.
== The middle initial ==
The "S" in Truman's name does not stand for anything. It was chosen to honor both of his grandfathers, Anderson Shipp Truman and Solomon Young. Truman himself noted that the S should not be followed by a period, though convention usually adds one.
""",
"Burj Khalifa": """The '''Burj Khalifa''' is a [[skyscraper]] in [[Dubai]], [[United Arab Emirates]], with a total height of 828&#160;m (2,717&#160;ft). Completed in 2010, it is the [[List of tallest buildings|tallest building in the world]].
""",
"Shanghai Tower": """'''Shanghai Tower''' is a 632-metre (2,073&#160;ft), 128-story [[megatall skyscraper]] in [[Lujiazui]], [[Pudong]], [[Shanghai]]. It is the tallest building in China and the third-tallest in the world, 196 metres shorter than the [[Burj Khalifa]].
""",
"Moai": """The '''moai''' are [[monolithic]] human figures carved by the [[Rapa Nui]] people on [[Easter Island]] between 1250 and 1500 CE.
== History ==
Nearly half of the moai remain at [[Rano Raraku]], the main quarry where they were carved.
""",
"1977 Wimbledon Championships": """The '''1977 Wimbledon Championships''' was a [[tennis]] tournament played on outdoor grass courts. '''Virginia Wade''' defeated [[Betty Stove]] in the women's singles final. It was the centenary Wimbledon, held in the year of the [[Silver Jubilee of Elizabeth II|Queen's Silver Jubilee]].
""",
"Eiffel Tower": """The '''Eiffel Tower''' is a wrought-iron [[lattice tower]] in [[Paris]], completed in 1889 for the [[Exposition Universelle (1889)|1889 World's Fair]].
== Survival ==
The tower was built under a 20-year concession that expired in 1909. It was spared from demolition because [[Gustave Eiffel]] had installed scientific instruments on it and, decisively, a [[radio]] antenna whose military communications value proved indispensable.
""",
"Rayleigh scattering": """'''Rayleigh scattering''' is the scattering of light by particles much smaller than its wavelength, such as air molecules.
== Sky color ==
Short (blue) wavelengths scatter far more strongly than long (red) ones. Looking up on a clear day, we see blue light scattered from all directions. At sunset, sunlight travels through much more atmosphere; the blue is scattered away before reaching the eye, leaving the red and orange direct light.
""",
"Transmission Control Protocol": """The '''Transmission Control Protocol''' ('''TCP''') is a reliable, ordered, connection-oriented [[transport layer]] protocol. It is slower than [[User Datagram Protocol|UDP]] due to its acknowledgements and retransmissions, and is used for the [[World Wide Web|web]], [[email]], and file transfer.
""",
"User Datagram Protocol": """The '''User Datagram Protocol''' ('''UDP''') is an unreliable, unordered, connectionless [[transport layer]] protocol. It has very low overhead and is faster than [[Transmission Control Protocol|TCP]], making it suitable for video calls, online gaming, [[DNS]], and live streaming.
""",
"Refrigerator": """A '''refrigerator''' is a [[heat pump]]: it moves heat from its insulated interior to coils at the back, and the [[compressor]] adds waste heat in the process.
== Open-door myth ==
Leaving the refrigerator door open cannot cool a room. With the door open, the fridge dumps more heat into the room (the moved heat plus the compressor's waste heat) than it removes from the air. The net effect warms the kitchen.
""",
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "packs", "demo.pack"))
    args = ap.parse_args()
    out = os.path.normpath(args.out)

    d = tempfile.mkdtemp(prefix="demopack")
    xml = os.path.join(d, "demo.xml")
    with open(xml, "w") as f:
        f.write("<mediawiki>\n")
        for i, (title, text) in enumerate(ARTICLES.items()):
            f.write(f"<page><title>{title}</title><ns>0</ns><id>{i+1}</id>\n")
            f.write(f"<text>{text}</text></page>\n")
        f.write("</mediawiki>\n")

    ns = argparse.Namespace(input=xml, pack_name="demo", out=out,
                            max_articles=0)
    build_pack.MIN_PROSE_CHARS = 200
    rc = build_pack.build(ns)
    print(f"demo pack: {len(ARTICLES)} articles -> {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
