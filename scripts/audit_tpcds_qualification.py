from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import re
from pathlib import Path
from typing import Any

_SECTION = re.compile(r"B\.(\d+)\s+(?:query|Query)(\d+)\.tpl")
_PARAMETER = re.compile(r"(?:•\s*)?([A-Z][A-Z0-9_]*(?:\.\d+)?)\s*=\s*")


def extract_appendix_values(text: str) -> dict[str, dict[str, str]]:
    text = text.replace("\x00", "")
    sections = list(_SECTION.finditer(text))
    if [int(match.group(1)) for match in sections] != list(range(1, 100)):
        raise ValueError("Specification must contain all 99 Appendix B sections in order")
    result: dict[str, dict[str, str]] = {}
    for index, match in enumerate(sections):
        end = sections[index + 1].start() if index + 1 < len(sections) else text.index("Appendix C:", match.end())
        section = text[match.end() : end]
        if "Qualification Substitution Parameters" not in section:
            raise ValueError(f"Missing qualification table: Q{match.group(1)}")
        values = section.split("Qualification Substitution Parameters", 1)[1].split("Comment:", 1)[0]
        values = re.sub(r"TPC Benchmark.*?Page \d+ of \d+", "", values)
        parameters = list(_PARAMETER.finditer(values))
        row: dict[str, str] = {}
        for position, parameter in enumerate(parameters):
            raw_key = parameter.group(1)
            key = (
                raw_key.rsplit(".", 1)[0] + "." + raw_key.rsplit(".", 1)[1].zfill(2)
                if "." in raw_key
                else raw_key + ".01"
            )
            value_end = parameters[position + 1].start() if position + 1 < len(parameters) else len(values)
            value = re.sub(r"\s+", " ", values[parameter.end() : value_end].strip(" \n\t•:")).strip()
            if key in row or not value:
                raise ValueError(f"Duplicate or empty qualification value: Q{match.group(1)} {key}")
            row[key] = value
        if not row:
            raise ValueError(f"Empty qualification table: Q{match.group(1)}")
        result[match.group(1)] = row
    return result


def audit(pdf: Path, parameters: Path) -> dict[str, Any]:
    if importlib.metadata.version("pypdf") != "6.0.0":
        raise ValueError("Specification extraction requires pypdf==6.0.0")
    reader = importlib.import_module("pypdf").PdfReader(pdf)
    pages = [page.extract_text() for page in reader.pages]
    extracted = extract_appendix_values("\n".join(pages))
    document = json.loads(parameters.read_text(encoding="utf-8"))
    if document["not_in_template"] != {"71": ["MANAGER.01"]}:
        raise ValueError("Unknown unused qualification parameter")
    extracted["71"].pop("MANAGER.01")
    if extracted != document["values"]:
        differences = {
            number: {
                key: {"specification": values.get(key), "committed": document["values"].get(number, {}).get(key)}
                for key in values.keys() | document["values"].get(number, {}).keys()
                if values.get(key) != document["values"].get(number, {}).get(key)
            }
            for number, values in extracted.items()
            if values != document["values"].get(number)
        }
        raise ValueError(json.dumps(differences, sort_keys=True))
    return {
        "specification": "TPC-DS 4.0.0",
        "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "parameters_sha256": hashlib.sha256(parameters.read_bytes()).hexdigest(),
        "canonical_values_sha256": hashlib.sha256(
            json.dumps(extracted, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "queries": 99,
        "values": sum(map(len, extracted.values())),
        "extraction_dependency": "pypdf==6.0.0",
        "query_pdf_pages": {
            match.group(1): number + 1 for number, page in enumerate(pages) for match in _SECTION.finditer(page)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(audit(args.pdf, args.parameters), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
