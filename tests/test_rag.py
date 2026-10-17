import unittest

from sotonship_rag.documents import chunk_text
from sotonship_rag.embeddings import cosine_similarity


class RagTests(unittest.TestCase):
    def test_chunk_text_keeps_all_paragraphs(self):
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunk_text(text, max_chars=35, overlap=5)
        joined = " ".join(chunks)
        self.assertIn("First paragraph.", joined)
        self.assertIn("Second paragraph.", joined)
        self.assertIn("Third paragraph.", joined)

    def test_cosine_similarity(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)


if __name__ == "__main__":
    unittest.main()
