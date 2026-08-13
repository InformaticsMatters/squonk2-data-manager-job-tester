"""Tests for jote's Job Definition schema validation.

These focus on the requirement (issue #13) that jote validates against a
decoder new enough to have closed the open parts of the Job Definition
schema. Decoder 2.7.0 constrains an output's 'annotation-properties' to
'fields-descriptor', 'derived-from' and 'service-execution'; before that an
unrecognised (or misplaced) annotation validated silently.
"""

from typing import Any

import yaml

from jote.jote import _validate_schema


def _write_definition(tmp_path: Any, annotation_properties: dict[str, Any]) -> str:
    """Writes a minimal Job Definition whose single output variable carries
    the given annotation properties, returning its filename.
    """
    definition: dict[str, Any] = {
        "kind": "DataManagerJobDefinition",
        "kind-version": "2021.1",
        "collection": "test",
        "jobs": {
            "demo": {
                "version": "1.0.0",
                "name": "test",
                "image": {
                    "name": "blob",
                    "tag": "1.0.0",
                    "project-directory": "/data",
                    "working-directory": "/data",
                },
                "command": "echo hello",
                "variables": {
                    "outputs": {
                        "type": "object",
                        "properties": {
                            "outputFile": {
                                "title": "Output file",
                                "creates": "{{ outputFile }}",
                                "type": "file",
                                "annotation-properties": annotation_properties,
                            }
                        },
                    }
                },
            }
        },
    }
    definition_file = tmp_path / "job-definition.yaml"
    definition_file.write_text(yaml.dump(definition), encoding="UTF-8")
    return str(definition_file)


_FIELDS_DESCRIPTOR: dict[str, Any] = {
    "origin": "squonk2-job",
    "description": "Something",
    "fields": {"smiles": {"type": "string", "description": "Molecule"}},
}


def test_validate_schema_accepts_annotations(tmp_path):
    # Given a definition whose 'derived-from' sits beside 'fields-descriptor'
    definition_filename = _write_definition(
        tmp_path,
        {"derived-from": "inputFile", "fields-descriptor": dict(_FIELDS_DESCRIPTOR)},
    )

    # When we validate it
    # Then it complies with the schema
    assert _validate_schema(definition_filename)


def test_validate_schema_rejects_misplaced_derived_from(tmp_path):
    # Given a definition whose 'derived-from' is nested inside
    # 'fields-descriptor' (so the annotation is silently never applied)
    fields_descriptor = dict(_FIELDS_DESCRIPTOR)
    fields_descriptor["derived-from"] = "inputFile"
    definition_filename = _write_definition(
        tmp_path, {"fields-descriptor": fields_descriptor}
    )

    # When we validate it
    # Then it does not comply with the schema
    assert not _validate_schema(definition_filename)


def test_validate_schema_rejects_unknown_annotation(tmp_path):
    # Given a definition carrying an unrecognised annotation
    definition_filename = _write_definition(tmp_path, {"derived-form": "inputFile"})

    # When we validate it
    # Then it does not comply with the schema
    assert not _validate_schema(definition_filename)
