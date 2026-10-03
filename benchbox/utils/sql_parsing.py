from __future__ import annotations


def find_matching_parenthesis(text: str, open_index: int) -> int:

    depth = 0
    in_single_quote = False
    index = open_index

    while index < len(text):
        char = text[index]
        if char == "'":
            if in_single_quote and index + 1 < len(text) and text[index + 1] == "'":
                index += 2
                continue
            in_single_quote = not in_single_quote
        elif not in_single_quote:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
        index += 1

    raise ValueError("Unbalanced parentheses in SQL expression")


__all__ = ["find_matching_parenthesis"]
