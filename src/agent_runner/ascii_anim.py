from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AsciiAnimation:
    name: str
    frames: tuple[str, ...]


ANIMATIONS: tuple[AsciiAnimation, ...] = (
    AsciiAnimation(
        name="baseball",
        frames=(
            "  o\n /|>   _\n / \\  / \\\nPitcher set",
            " \\o    _\n  |\\  / \\\n / \\    o\nPitch incoming",
            "  o/   _\n /|   / \\\n / \\ --*\nCrack!",
            "   o   _\n  /|\\ / \\\n  / \\  ^\nHome run trot",
        ),
    ),
    AsciiAnimation(
        name="boxing",
        frames=(
            " o   o \n/|\\ /|\\\n/ \\ / \\\nTouch gloves",
            " o_  o \n/|  /|\\\n/ \\ / \\\nLeft jab",
            " o  _o \n/|\\  |\\\n/ \\ / \\\nCounter punch",
            " o   o \n/|\\_/|\\\n/ \\ / \\\nBell rings",
        ),
    ),
    AsciiAnimation(
        name="horse-race",
        frames=(
            " ,--.\n( oo>\n / ) \\\nRace starts",
            "  ,--.\n _( oo>\n/__/ ) \\\nThey run",
            "   ,--.\n __ ( oo>\n/___/ ) \\\nNeck and neck",
            "    ,--.\n ___( oo>\n/____ ) \\\nPhoto finish",
        ),
    ),
    AsciiAnimation(
        name="bowling",
        frames=(
            " o\n/|\\\n/ \\\nRoll up",
            "  o---->\n /|\\\n / \\\nBall away",
            "      o--->\n      ||||\n      ||||\nPins wait",
            "       *\n      \\\\|//\n       /|\\\\\nStrike",
        ),
    ),
    AsciiAnimation(
        name="train",
        frames=(
            "==[]====\n  ||\n--==----\nAll aboard",
            " ==[]====\n   ||\n---==---\nRolling",
            "  ==[]====\n    ||\n----==--\nPassing through",
            "   ==[]====\n     ||\n-----==-\nGone by",
        ),
    ),
    AsciiAnimation(
        name="ship",
        frames=(
            "  |\\\n /|.\\\\\n/_|__\\\\\nCalm sea",
            "   |\\\n  /|.\\\\\n~/_|__\\\\~\nMaking way",
            "    |\\\n   /|.\\\\\n~~/_|__\\\\~~\nCrossing map",
            "     |\\\n    /|.\\\\\n~~~/_|__\\\\~~~\nOnward",
        ),
    ),
    AsciiAnimation(
        name="rocket",
        frames=(
            "  /^\\\\\n  |-|\n  | |\n /___\\\\\nFueling",
            "  /^\\\\\n  |-|\n  | |\n /___\\\\\n  / \\\nIgnition",
            "  /^\\\\\n  |-|\n /___\\\\\n  / \\\n  **\nLiftoff",
            "   /^\\\\\n   |-|\n  /___\\\\\n   **\n   **\nUpward",
        ),
    ),
    AsciiAnimation(
        name="goblin-terminal",
        frames=(
            " (..)\n<(  )>\n /  \\\\\nGoblin typing",
            " (..)\n<(/ )>\n /  \\\\\nMore typing",
            " (..)\n<() \\\\>\n /  \\\\\nStill typing",
            " (..)\n<(  )>\n /__\\\\\nCackling",
        ),
    ),
    AsciiAnimation(
        name="printer",
        frames=(
            " ______\n| ____ |\n||____||\n|______|\nReady",
            " ______\n| ____ |\n||____||\n|__==__|\nWhirring",
            " ______\n| ____ |\n||____||\n|_====_|\nPrinting",
            "   ||\n ______\n| ____ |\n||____||\nDone",
        ),
    ),
    AsciiAnimation(
        name="radar",
        frames=(
            " .----.\n |\\\\   |\n | \\\\  |\n '----'\nSweep",
            " .----.\n | \\\\  |\n |  \\\\ |\n '----'\nSweep",
            " .----.\n |  // |\n | //  |\n '----'\nReturn",
            " .----.\n | //  |\n |//   |\n '----'\nReturn",
        ),
    ),
    AsciiAnimation(
        name="campfire",
        frames=(
            "  ()\n <||>\n  /\\\\\nCampfire",
            "  /\\\n <||>\n  /\\\\\nCrackle",
            "  {} \n <||>\n  /\\\\\nGlow",
            "  /\\\n <||>\n _/\\\\_\nWarmth",
        ),
    ),
    AsciiAnimation(
        name="slot-machine",
        frames=(
            " .------.\n[7|?|*] |\n '------'\nPulling...",
            " .------.\n[?|*|7] /\n '------'\nSpinning...",
            " .------.\n[*|7|7] |\n '------'\nStill spinning...",
            " .------.\n[7|7|7] /\n '------'\nJackpot",
        ),
    ),
)


def random_animation() -> AsciiAnimation:
    return random.choice(ANIMATIONS)
