"""The feed hat prompts (docs/prompts/hats/).

A hat prompt holds one `{{all-hats}}` line for the shared ALL_HATS.md, which holds one
`{{custom_instructions}}` line for the human's own saved instructions for that hat. `{{hat}}`
stands for the hat's name wherever it appears. SENSEI.md also holds one `{{due}}` line for the
Sensei post due now.
"""

from __future__ import annotations

from importlib.resources import files

ALL_HATS = "{{all-hats}}"
CUSTOM_INSTRUCTIONS = "{{custom_instructions}}"
DUE = "{{due}}"
HAT = "{{hat}}"
NO_INSTRUCTIONS = "None yet."


def _fill_line(template: str, placeholder: str, text: str) -> str:
    lines = template.split("\n")
    if template.count(placeholder) != 1 or lines.count(placeholder) != 1:
        raise ValueError(f"a hat prompt must hold exactly one {placeholder} line")
    lines[lines.index(placeholder)] = text
    return "\n".join(lines)


def hat_template(hat: str) -> str:
    """The hat's prompt with ALL_HATS.md on its `{{all-hats}}` line and the hat's name for every `{{hat}}`.

    One `{{custom_instructions}}` line remains, plus the `{{due}}` line in SENSEI.md.
    """
    hats = files("coworld").joinpath("docs/prompts/hats")
    all_hats = hats.joinpath("ALL_HATS.md").read_text(encoding="utf-8").strip()
    template = _fill_line(hats.joinpath(f"{hat.upper()}.md").read_text(encoding="utf-8"), ALL_HATS, all_hats)
    return template.replace(HAT, hat)


def render_hat_prompt(template: str, instructions: str | None, due: str | None) -> str:
    """Put `due` on the one `{{due}}` line, then the saved instructions, or "None yet.", on the one
    `{{custom_instructions}}` line. `due` is None for a hat without a `{{due}}` line.

    The instructions go in last so text the human wrote is never read as a placeholder.
    """
    prompt = template if due is None else _fill_line(template, DUE, due)
    return _fill_line(prompt, CUSTOM_INSTRUCTIONS, instructions if instructions is not None else NO_INSTRUCTIONS)
