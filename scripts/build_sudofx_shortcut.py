from __future__ import annotations

import plistlib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "sudofx Continue.shortcut"

def uid():
    return str(uuid.uuid4()).upper()

def text_token(text, attachments=None):
    return {
        "Value": {"string": text, "attachmentsByRange": attachments or {}},
        "WFSerializationType": "WFTextTokenString",
    }

def dict_field(items):
    return {
        "Value": {
            "WFDictionaryFieldValueItems": [
                {"WFItemType": 0, "WFKey": k, "WFValue": v} for k, v in items
            ]
        },
        "WFSerializationType": "WFDictionaryFieldValue",
    }

credential_uuid = uid()

authorization = text_token(
    "Bearer \ufffc",
    {"{7, 1}": {
        "Type": "ActionOutput",
        "OutputUUID": credential_uuid,
        "OutputName": "Text",
    }},
)

workflow = {
    "WFWorkflowActions": [
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
            "WFWorkflowActionParameters": {
                "UUID": credential_uuid,
                "WFTextActionText": "",
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
            "WFWorkflowActionParameters": {
                "UUID": uid(),
                "WFURL": "https://api.github.com/repos/sudofx/sudofx/actions/workflows/sudofx.yml/dispatches",
                "WFHTTPMethod": "POST",
                "ShowHeaders": True,
                "WFHTTPHeaders": dict_field([
                    (text_token("Authorization"), authorization),
                    (text_token("Accept"), text_token("application/vnd.github+json")),
                    (text_token("X-GitHub-Api-Version"), text_token("2026-03-10")),
                ]),
                "WFHTTPBodyType": "JSON",
                "WFJSONValues": dict_field([
                    (text_token("ref"), text_token("master")),
                    (
                        text_token("inputs"),
                        dict_field([
                            (text_token("action"), text_token("auto")),
                        ]),
                    ),
                ]),
                "WFShowWebView": False,
            },
        },
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.notification",
            "WFWorkflowActionParameters": {
                "UUID": uid(),
                "WFNotificationActionTitle": text_token("sudofx"),
                "WFNotificationActionBody": text_token("sudofx is continuing the current milestone."),
                "WFNotificationActionSound": True,
            },
        },
    ],
    "WFWorkflowClientVersion": "2700.0.4",
    "WFWorkflowHasOutputFallback": False,
    "WFWorkflowHasShortcutInputVariables": False,
    "WFWorkflowIcon": {
        "WFWorkflowIconGlyphNumber": 61440,
        "WFWorkflowIconStartColor": 431817727,
    },
    "WFWorkflowImportQuestions": [
        {
            "ActionIndex": 0,
            "Category": "Parameter",
            "DefaultValue": "",
            "ParameterKey": "WFTextActionText",
            "Text": "Paste the repository-scoped GitHub credential for this Shortcut.",
        }
    ],
    "WFWorkflowInputContentItemClasses": [],
    "WFWorkflowMinimumClientVersion": 900,
    "WFWorkflowMinimumClientVersionString": "900",
    "WFWorkflowName": "sudofx Continue",
    "WFWorkflowOutputContentItemClasses": [],
    "WFWorkflowTypes": ["NCWidget"],
}

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("wb") as fh:
    plistlib.dump(workflow, fh, fmt=plistlib.FMT_BINARY, sort_keys=False)
print(OUT)
