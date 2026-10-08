# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from typing import Optional

from rich.prompt import Prompt


def format_prompt_with_current(base_prompt: str, current_value: Optional[str]) -> str:
    if current_value:
        return f"{base_prompt} (current: {current_value})"
    return base_prompt


def prompt_with_default(
    prompt_text: str,
    current_value: Optional[str] = None,
    default_if_none: Optional[str] = None,
    password: bool = False,
) -> Optional[str]:
    default_value = current_value if current_value is not None else default_if_none

    formatted_prompt = format_prompt_with_current(prompt_text, current_value)

    result = Prompt.ask(formatted_prompt, default=default_value, password=password)

    if not result and default_value is None:
        return None

    return result


def prompt_secure_field(
    field_name: str,
    current_value: Optional[str] = None,
    console=None,
) -> Optional[str]:
    if current_value:
        prompt_text = f"{field_name} [current: ****SET****]"
        if console:
            console.print(f"[dim]Leave empty to preserve current {field_name.lower()}[/dim]")
    else:
        prompt_text = field_name

    result = Prompt.ask(prompt_text, password=True, default="")

    if not result and current_value:
        return current_value

    if not result:
        return None

    return result


__all__ = [
    "format_prompt_with_current",
    "prompt_with_default",
    "prompt_secure_field",
]
