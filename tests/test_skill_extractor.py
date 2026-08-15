import unittest

from devcompass.enrichment import SkillExtractor, section_filtered_text


ALIASES = [
    (1, "Java", "Java", "normal"),
    (2, "JavaScript", "JavaScript", "normal"),
    (2, "JavaScript", "JS", "normal"),
    (3, "Go", "Golang", "normal"),
    (3, "Go", "Go", "ambiguous_contextual"),
    (4, "R", "R", "ambiguous_contextual"),
    (5, "C", "C", "ambiguous_contextual"),
    (6, "C++", "C++", "normal"),
    (7, "C#", "C#", "normal"),
    (8, "Python", "Python", "normal"),
    (9, "Kubernetes", "Kubernetes", "normal"),
    (10, "MongoDB Atlas", "MongoDB Atlas", "normal"),
    (11, "Cloudflare", "Cloudflare", "normal"),
    (12, "Rust", "Rust", "normal"),
    (13, "Node.js", "Node.js", "normal"),
    (14, ".NET", ".NET", "normal"),
    (15, "TypeScript", "TypeScript", "normal"),
    (16, "React", "React", "normal"),
    (17, "AWS", "AWS", "normal"),
    (18, "GCP", "GCP", "normal"),
    (19, "OpenAI", "OpenAI", "normal"),
    (20, "GPT", "GPT", "normal"),
    (21, "Anthropic", "Anthropic", "normal"),
    (22, "Claude", "Claude", "normal"),
]


class SkillExtractorTest(unittest.TestCase):
    def setUp(self):
        self.extractor = SkillExtractor(
            [
                {
                    "skill_id": skill_id,
                    "skill_name": skill_name,
                    "alias_text": alias_text,
                    "match_policy": match_policy,
                }
                for skill_id, skill_name, alias_text, match_policy in ALIASES
            ]
        )

    def names(self, text, company=None):
        return {
            row["skill_name"]
            for row in self.extractor.extract(text, company)
        }

    def test_long_alias_and_ambiguous_boundaries(self):
        cases = [
            ("Experience with JavaScript and Java", {"JavaScript", "Java"}),
            ("We use Golang and Go for backend, plus Rust", {"Go", "Rust"}),
            ("Go to Market strategy and business development", set()),
            ("Our last funding was a Series C round", set()),
            ("Washington, D.C. metro area required", set()),
            ("We'd love for you to join. WE'D really appreciate it", set()),
            ("R&D team focused on machine learning with Python", {"Python"}),
            ("Proficient in C++, C#, and Python", {"C++", "C#", "Python"}),
            ("Familiar with Node.js and .NET", {"Node.js", ".NET"}),
            (
                "Skilled in JavaScript, TypeScript, and modern JS frameworks like React",
                {"JavaScript", "TypeScript", "React"},
            ),
            ("Strong C, C++, or Rust background required", {"C", "C++", "Rust"}),
            (
                "We use Kubernetes, AWS, and GCP for our infrastructure",
                {"Kubernetes", "AWS", "GCP"},
            ),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.names(text), expected)

    def test_section_filter(self):
        text = """Who we are
MongoDB Atlas and Cloudflare
Salary
Competitive pay
Requirements
Python and Kubernetes
"""
        self.assertEqual(
            self.names(section_filtered_text(text)),
            {"Python", "Kubernetes"},
        )

    def test_company_self_mention(self):
        self.assertEqual(
            self.names("Requirements\nMongoDB Atlas", "MongoDB"),
            {"MongoDB Atlas"},
        )
        self.assertEqual(
            self.names("Requirements\nMongoDB Atlas", "Stripe"),
            {"MongoDB Atlas"},
        )
        self.assertEqual(
            self.names("Requirements\nCloudflare", "Cloudflare"),
            set(),
        )
        self.assertEqual(
            self.names(
                "Requirements\nCloudflare, Kubernetes, and Python",
                "Cloudflare",
            ),
            {"Cloudflare", "Kubernetes", "Python"},
        )
        self.assertEqual(
            self.names("Requirements\nC++ and C", "Anthropic"),
            {"C++", "C"},
        )

    def test_company_name_skill_merge(self):
        self.assertEqual(
            self.names("Requirements\nExperience with GPT and OpenAI models"),
            {"GPT"},
        )
        self.assertEqual(
            self.names("Requirements\nOpenAI required.", "Stripe"),
            {"GPT"},
        )
        self.assertEqual(
            self.names("Requirements\nOpenAI required.", "OpenAI"),
            set(),
        )
        self.assertEqual(
            self.names(
                "Requirements\nOpenAI, Kubernetes, and Python required.",
                "OpenAI",
            ),
            {"GPT", "Kubernetes", "Python"},
        )
        self.assertEqual(
            self.names("Requirements\nAnthropic required.", "Anthropic"),
            set(),
        )
        self.assertEqual(
            self.names(
                "Requirements\nAnthropic, Kubernetes, and Python required.",
                "Anthropic",
            ),
            {"Claude", "Kubernetes", "Python"},
        )


if __name__ == "__main__":
    unittest.main()
