"""l2_decks -- deck generation + the TCAD simulator integration: render(params)->decks, validate(params). Template library + model registry. Reuses *.scm/*.cmd, validator.py.

The BSIM-CMG side of this layer is implemented in `cardgen.py`: it renders a
candidate parameter set into a SPICE `.model` card and the HSPICE decks that
exercise it. The TCAD side remains an interface stub -- the structure decks are
vendor files and are not carried in this repository.
"""

from .cardgen import render_card, write_card, write_deck, DEFAULT_STRUCTURE
