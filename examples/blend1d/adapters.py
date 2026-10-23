"""Example plugin: a project-specific adapter for 1D blend spaces."""

from luaugen.adapters import Unsupported, adapter, single


@adapter("blend1d")
def blend1d(inputs, options):
    out = {}
    for space in single(inputs, "blend1d").data["blendSpaces"]:
        samples = sorted(space["samples"], key=lambda s: s["at"])
        positions = [s["at"] for s in samples]
        if len(set(positions)) != len(positions):
            # Two clips at one position: which one wins is a design decision,
            # not something the compiler should guess.
            raise Unsupported("%s has duplicate sample positions" % space["name"])
        if space["name"] in out:
            raise Unsupported("duplicate blend space %r" % space["name"])
        out[space["name"]] = {
            "parameter": space["parameter"],
            "positions": positions,
            "clips": [s["clip"] for s in samples],
        }
    return out
