from __future__ import annotations

import unittest

from applications.conversation.provider import (
    _provider_prompt,
    _references_previous_exchange,
    _requested_web_tools,
)


class ConversationProviderTests(unittest.TestCase):
    """Protect adjacent-turn meaning at the fresh-provider trust boundary."""

    def test_referential_follow_up_is_framed_with_previous_exchange(self) -> None:
        """The live task must make its antecedent obvious, not merely present."""
        conversation = {
            "current_message": "What details can you tell me about them?",
            "previous_exchange": {
                "human": "Explain WAKE and sudofx.",
                "assistant": "WAKE is an application; sudofx is its engine.",
                "authority": "transient_active_window",
            },
        }
        context = {"state": {"app:conversation": conversation}}

        prompt = _provider_prompt(context, conversation)

        self.assertTrue(_references_previous_exchange(conversation["current_message"]))
        self.assertIn("CURRENT HUMAN MESSAGE", prompt)
        self.assertIn("IMMEDIATELY PREVIOUS EXCHANGE", prompt)
        self.assertIn("Explain WAKE and sudofx.", prompt)

    def test_adjacent_public_urls_can_be_revisited_only_for_a_reference(self) -> None:
        """A follow-up can ground details without granting general URL replay."""
        previous = (
            "WAKE https://github.com/sudofx/wake and "
            "sudofx https://github.com/sudofx/sudofx"
        )
        referential = "What details can you tell me about them?"
        unrelated = "Help me write a poem."

        conversation = {
            "current_message": referential,
            "previous_exchange": {"human": previous, "assistant": "Earlier answer."},
        }
        self.assertEqual(_requested_web_tools(conversation), ("read_public_url",))
        self.assertFalse(_references_previous_exchange(unrelated))
        conversation["current_message"] = unrelated
        self.assertEqual(_requested_web_tools(conversation), ())


if __name__ == "__main__":
    unittest.main()
