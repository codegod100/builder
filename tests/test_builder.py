from __future__ import annotations

import unittest

from builder.main import build_parser, chunked, format_bytes, render_progress, shell_join, unique


class BuilderTests(unittest.TestCase):
    def test_format_bytes(self) -> None:
        self.assertEqual(format_bytes(42), "42 B")
        self.assertEqual(format_bytes(2048), "2.0 KiB")
        self.assertEqual(format_bytes(5 * 1024 * 1024), "5.0 MiB")

    def test_unique_preserves_order(self) -> None:
        self.assertEqual(unique(["a", "b", "a", "c", "b"]), ["a", "b", "c"])

    def test_chunked_splits_sequences(self) -> None:
        self.assertEqual(list(chunked(["a", "b", "c", "d", "e"], 2)), [["a", "b"], ["c", "d"], ["e"]])

    def test_shell_join_quotes_spaces(self) -> None:
        self.assertEqual(
            shell_join(["ssh", "builder", "nix-store", "--realise", "/tmp/a b"]),
            "ssh builder nix-store --realise '/tmp/a b'",
        )

    def test_render_progress_known_total(self) -> None:
        rendered = render_progress(50, 100, started_at=0.0)
        self.assertIn("%", rendered)
        self.assertIn("100 B", rendered)

    def test_parser_collects_repeated_options(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--ssh-option=-p",
                "--ssh-option=2222",
                "--nix-option",
                "builders-use-substitutes",
                "true",
                "host",
                ".#pkg",
            ]
        )

        self.assertEqual(args.ssh_option, ["-p", "2222"])
        self.assertEqual(args.nix_option, [["builders-use-substitutes", "true"]])
        self.assertEqual(args.installables, [".#pkg"])


if __name__ == "__main__":
    unittest.main()
