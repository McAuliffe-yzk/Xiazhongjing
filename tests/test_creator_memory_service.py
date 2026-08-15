from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services import xiangzhongjing_store
from services.creator_memory_service import (
    memory_engine_status,
    record_dialogue_feedback,
    retrieve_creator_context,
    save_summary_checkpoint,
    should_refresh_session_summary,
    sync_reference_document_chunks,
)


class CreatorMemoryServiceTests(unittest.TestCase):
    def test_reference_documents_are_chunked_and_retrieved_with_sources(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "memory.db"
        ):
            xiangzhongjing_store.save_reference_document(
                "创业日记.docx",
                "我参加了一场黑客松。\n\n后来开始创业，才知道行动不是热血口号，而是每天真实地把事情向前推。\n\n回忆会在疲惫的时候支撑我。",
                {"maturity": "final_script"},
            )
            status = sync_reference_document_chunks()
            context = retrieve_creator_context("创业疲惫时，什么支撑我继续行动", limit=4)

        self.assertEqual(status["documents"], 1)
        self.assertGreaterEqual(status["total_chunks"], 1)
        self.assertTrue(context["sources"])
        first = context["sources"][0]
        self.assertEqual(first["source_type"], "history_document")
        self.assertEqual(first["source_filename"], "创业日记.docx")
        self.assertIn("支撑", first["content"])

    def test_message_feedback_can_confirm_and_forget_cross_session_memory(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "feedback.db"
        ):
            session = xiangzhongjing_store.create_dialogue_session(
                "", "mirror", "mirror-self", "关于主体性的对话"
            )
            message = xiangzhongjing_store.add_dialogue_message(
                session["id"],
                "assistant",
                "我不是不愿意跟随别人，我只是越来越无法背叛自己的本心。",
            )
            remembered = record_dialogue_feedback(message["id"], "remember")
            context = retrieve_creator_context("我为什么无法背叛本心", limit=3)
            forgotten = record_dialogue_feedback(message["id"], "forget")
            status = memory_engine_status()

        self.assertEqual(remembered["action"], "remember")
        self.assertTrue(remembered["memory"])
        self.assertTrue(any(item["source_type"] == "creator_memory" for item in context["sources"]))
        self.assertEqual(forgotten["action"], "forget")
        self.assertEqual(status["active_memories"], 0)
        self.assertEqual(status["forgotten_memories"], 1)

    def test_session_summary_refresh_is_incremental(self):
        with TemporaryDirectory() as tmpdir, patch.object(
            xiangzhongjing_store, "DB_PATH", Path(tmpdir) / "checkpoint.db"
        ):
            session = xiangzhongjing_store.create_dialogue_session(
                "", "mirror", "mirror-self", "增量摘要"
            )
            self.assertFalse(should_refresh_session_summary(session["id"], 17))
            self.assertTrue(should_refresh_session_summary(session["id"], 18))
            save_summary_checkpoint(session["id"], 18, "message-18")
            self.assertFalse(should_refresh_session_summary(session["id"], 29))
            self.assertTrue(should_refresh_session_summary(session["id"], 30))


if __name__ == "__main__":
    unittest.main()
