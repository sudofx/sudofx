from __future__ import annotations

import base64
import json
from pathlib import Path
import tempfile
import unittest

from applications.conversation.transport import decrypt_text, encrypt_text, write_encrypted_reply


class ConversationTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        material = bytes(range(64))
        self.key = base64.urlsafe_b64encode(material).decode("ascii").rstrip("=")

    def test_round_trip_keeps_plaintext_out_of_envelope(self) -> None:
        message = "Earlier we were testing whether continuity survives process replacement."
        envelope = encrypt_text(message, key_value=self.key)
        self.assertNotIn(message, envelope)
        self.assertEqual(decrypt_text(envelope, key_value=self.key), message)

    def test_tamper_is_rejected_before_decryption(self) -> None:
        envelope = json.loads(encrypt_text("hello", key_value=self.key))
        ciphertext = envelope["ct"]
        envelope["ct"] = ("A" if ciphertext[:1] != "A" else "B") + ciphertext[1:]
        with self.assertRaises(ValueError):
            decrypt_text(json.dumps(envelope), key_value=self.key)

    def test_reply_projection_contains_only_ciphertext(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            response = root / "response.txt"
            reply = root / "reply.json"
            plaintext = "This reply should never be committed in plaintext."
            response.write_text(plaintext, encoding="utf-8")

            import os
            previous = os.environ.get("CONVERSATION_TRANSPORT_KEY")
            os.environ["CONVERSATION_TRANSPORT_KEY"] = self.key
            try:
                write_encrypted_reply(response, reply, "request-1")
            finally:
                if previous is None:
                    os.environ.pop("CONVERSATION_TRANSPORT_KEY", None)
                else:
                    os.environ["CONVERSATION_TRANSPORT_KEY"] = previous

            projected = reply.read_text(encoding="utf-8")
            self.assertNotIn(plaintext, projected)
            document = json.loads(projected)
            self.assertEqual(document["request_id"], "request-1")
            recovered = decrypt_text(
                json.dumps(document["payload"], separators=(",", ":")),
                key_value=self.key,
            )
            self.assertEqual(recovered, plaintext)


if __name__ == "__main__":
    unittest.main()
