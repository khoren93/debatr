"""The crowd and studio sounds of the videos: how they are made.

The sounds are not in git (frontend/public/sfx is ignored): this script makes them with
ElevenLabs Sound Effects (`POST /v1/sound-generation`, ~11 credits a second) and installs them;
on a server, copy the installed folder into frontend/public/sfx before building the frontend.
Without the folder the videos simply play without them.

    cd backend
    uv run python ../scripts/sfx/generate.py takes [--only crowd-ooh-1] [--takes 3]
    # listen to scripts/sfx/out/<id>/take-N.mp3 (out/index.html), delete the takes you dislike
    uv run python ../scripts/sfx/generate.py install

`takes` needs ELEVENLABS_API_KEY (the environment or the repo's .env) and costs money; `install`
re-encodes every take with ffmpeg (mono, 96 kbps, loudness -18 LUFS) into frontend/public/sfx
and writes its manifest.json (the files of every kind): the video picks one of a kind's files
per cue (frontend/src/video/sfx.ts decides what plays when).
"""

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
PUBLIC = ROOT / "frontend" / "public" / "sfx"
ENDPOINT = "https://api.elevenlabs.io/v1/sound-generation"


@dataclass(frozen=True)
class Sound:
    id: str
    prompt: str
    seconds: float
    influence: float = 0.5


CLUB = "live hip-hop rap battle crowd in a packed underground club, no music, no beat"
STUDIO = "TV talk show studio audience of about forty people, no music"

SOUNDS = [
    # Rap battle: a punchline lands.
    Sound("crowd-ooh-1", f"Crowd goes 'ooooh!' together after a savage diss, {CLUB}", 2.5),
    Sound("crowd-ooh-2", f"Loud collective 'oooh' with a few shouts after a brutal insult, {CLUB}", 2.5),
    Sound("crowd-ooh-3", f"Shocked crowd 'ohhh' reaction, hands over mouths, {CLUB}", 2.5),
    Sound("crowd-ooh-4", f"Rising 'oooooh' from the crowd, people reacting to a burn, {CLUB}", 2.5),
    # The best punchline of a round.
    Sound("crowd-erupt-1", f"Crowd erupts after a devastating punchline: hollering, 'OHHH!', whistles, {CLUB}", 3.0),
    Sound("crowd-erupt-2", f"Wild explosion of shouts and cheers, people jumping and yelling, {CLUB}", 3.0),
    Sound("crowd-erupt-3", f"Crowd goes crazy, screaming and whistling after a knockout bar, {CLUB}", 3.0),
    # A roast that is funny.
    Sound("crowd-laugh-1", f"Crowd bursts out laughing and hollering at a funny roast, {CLUB}", 2.5),
    Sound("crowd-laugh-2", f"Big laugh and clapping from the crowd at a joke, some 'ayy!', {CLUB}", 2.5),
    # "ROUND N" and the biggest punch.
    Sound("impact-1", "Deep cinematic sub bass boom impact hit with a short tail, no music, no voices", 1.5, 0.7),
    Sound("impact-2", "Punchy heavy drum impact slam with low rumble, trailer hit, no music, no voices", 1.5, 0.7),
    # The battle's winner.
    Sound("crowd-roar-1", f"Huge crowd roars and cheers for the winner, air horns blasting, {CLUB}", 4.0),
    Sound("crowd-roar-2", f"Arena crowd celebrating a victory, chanting and cheering with air horns, {CLUB}", 4.0),
    # Debate: a zinger lands.
    Sound("studio-ooh-1", f"Restrained 'ooh' from a polite audience after a sharp remark, {STUDIO}", 2.0),
    Sound("studio-ooh-2", f"Audience reacts with a soft impressed 'oooh', {STUDIO}", 2.0),
    Sound("studio-ooh-3", f"Short murmur of 'ooh' and a few chuckles from the audience, {STUDIO}", 2.0),
    # Debate: the verdict, the end of the last round.
    Sound("applause-1", f"Short warm applause, {STUDIO}", 3.0),
    Sound("applause-2", f"Enthusiastic applause with a couple of cheers, {STUDIO}", 3.0),
    Sound("studio-laugh-1", f"Light chuckle and laughter at a witty line, {STUDIO}", 2.0),
    Sound("studio-murmur-1", f"Surprised murmuring and a few gasps from the audience, {STUDIO}", 2.0),
    Sound("whoosh-1", "Clean cinematic whoosh transition, swoosh, no music, no voices", 1.0, 0.7),
    Sound("whoosh-2", "Fast airy swish transition sound effect, no music, no voices", 1.0, 0.7),
    Sound("verdict-sting-1", "Short tense snare drum roll building into a cymbal crash, game show reveal", 2.5),
]


def api_key() -> str:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key and (ROOT / ".env").exists():
        for line in (ROOT / ".env").read_text().splitlines():
            if line.startswith("ELEVENLABS_API_KEY="):
                key = line.split("=", 1)[1].split(" #", 1)[0].strip().strip('"')
    if not key:
        sys.exit("ELEVENLABS_API_KEY is not set")
    return key


def takes(only: set[str], count: int) -> None:
    key = api_key()
    with httpx.Client(timeout=120) as client:
        for sound in SOUNDS:
            if only and sound.id not in only:
                continue
            folder = OUT / sound.id
            folder.mkdir(parents=True, exist_ok=True)
            for n in range(1, count + 1):
                path = folder / f"take-{n}.mp3"
                if path.exists():
                    continue
                response = client.post(
                    ENDPOINT,
                    params={"output_format": "mp3_44100_128"},
                    headers={"xi-api-key": key},
                    json={
                        "text": sound.prompt,
                        "duration_seconds": sound.seconds,
                        "prompt_influence": sound.influence,
                    },
                )
                if response.status_code != 200:
                    sys.exit(f"{sound.id}: HTTP {response.status_code} {response.text[:300]}")
                path.write_bytes(response.content)
                print(f"{sound.id} take {n}: {len(response.content) // 1024} KB")


def kind_of(sound_id: str) -> str:
    """ "crowd-ooh-2" -> "crowd-ooh": the cue a sound plays for (frontend video/sfx.ts)."""
    return sound_id.rsplit("-", 1)[0]


def install() -> None:
    """Every take left in out/ into frontend/public/sfx (made afresh) with its manifest."""
    PUBLIC.mkdir(parents=True, exist_ok=True)
    for old in [*PUBLIC.glob("*.mp3"), PUBLIC / "manifest.json"]:
        old.unlink(missing_ok=True)
    files: dict[str, list[str]] = {}
    for sound in SOUNDS:
        for src in sorted((OUT / sound.id).glob("take-*.mp3")):
            name = f"{sound.id}-t{src.stem.removeprefix('take-')}.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", "loudnorm=I=-18:TP=-2",
                 "-ac", "1", "-ar", "44100", "-b:a", "96k", str(PUBLIC / name)],
                check=True,
            )
            files.setdefault(kind_of(sound.id), []).append(name)
    (PUBLIC / "manifest.json").write_text(json.dumps({"files": files}, indent=1) + "\n")
    count = sum(len(v) for v in files.values())
    print(f"{count} sounds of {len(files)} kinds in {PUBLIC.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("takes", help="generate takes to listen to (paid)")
    make.add_argument("--only", nargs="*", default=[], help="sound ids")
    make.add_argument("--takes", type=int, default=3)
    commands.add_parser("install", help="install every take into frontend/public/sfx")
    args = parser.parse_args()
    if args.command == "takes":
        takes(set(args.only), args.takes)
    else:
        install()


if __name__ == "__main__":
    main()
