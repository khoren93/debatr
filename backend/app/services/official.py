"""The site's own account (`users.official`, set by `python -m app.manage official`): the
gallery shows the site's logo as its avatar and marks it, and only it may carry the brand's name.
"""

import unicodedata

BRAND = "debatr"

# Cyrillic and Greek letters read as the brand's Latin ones: look-alikes ("Debatr" typed with a
# Cyrillic "e") and the Russian spelling ("Дебатр"). Escapes, since the letters themselves
# look like the Latin ones they stand for.
LOOKALIKES = str.maketrans(
    {
        "\u0430": "a",  # cyrillic small letter a
        "\u0431": "b",  # cyrillic small letter be
        "\u0432": "b",  # cyrillic small letter ve
        "\u044c": "b",  # cyrillic small letter soft sign
        "\u0433": "r",  # cyrillic small letter ghe
        "\u0434": "d",  # cyrillic small letter de
        "\u0501": "d",  # cyrillic small letter komi de
        "\u0435": "e",  # cyrillic small letter ie
        "\u0451": "e",  # cyrillic small letter io
        "\u0440": "r",  # cyrillic small letter er
        "\u0442": "t",  # cyrillic small letter te
        "\u03b1": "a",  # greek small letter alpha
        "\u03b2": "b",  # greek small letter beta
        "\u03b5": "e",  # greek small letter epsilon
        "\u03c1": "r",  # greek small letter rho
        "\u03c4": "t",  # greek small letter tau
    }
)


def reserved_name(name: str) -> bool:
    """A name only the official account may carry: anything that spells the brand, whatever the
    case, spacing, punctuation or look-alike letters ("DEBATR", "Debatr Team", "d.e.b.a.t.r")."""
    folded = unicodedata.normalize("NFKC", name).casefold().translate(LOOKALIKES)
    return BRAND in "".join(ch for ch in folded if ch.isalnum())
