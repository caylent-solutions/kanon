"""Unittests for the subcmds module (mostly __init__.py than subcommands)."""

import optparse
import unittest

from kanon_cli.repo import subcmds


class AllCommands(unittest.TestCase):
    """Check registered all_commands."""

    def test_required_basic(self):
        """Basic checking of registered commands."""

        for cmd in {
            "cherry-pick",
            "help",
            "init",
            "start",
            "sync",
            "upload",
            "envsubst",
        }:
            self.assertIn(cmd, subcmds.all_commands)

    def test_naming(self):
        """Verify we don't add things that we shouldn't."""
        for cmd in subcmds.all_commands:
            self.assertNotIn(".", cmd)

            self.assertNotIn("_", cmd)

            self.assertFalse(cmd.startswith("__"))

    def test_help_desc_style(self):
        """Force some consistency in option descriptions.

        Python's optparse & argparse has a few default options like --help.
        Their option description text uses lowercase sentence fragments, so
        enforce our options follow the same style so UI is consistent.

        We enforce:
        * Text starts with lowercase.
        * Text doesn't end with period.
        """
        for name, cls in subcmds.all_commands.items():
            cmd = cls()
            parser = cmd.OptionParser
            for option in parser.option_list:
                if option.help == optparse.SUPPRESS_HELP:
                    continue

                c = option.help[0]
                self.assertEqual(
                    c.lower(),
                    c,
                    msg=f"subcmds/{name}.py: {option.get_opt_string()}: "
                    f'help text should start with lowercase: "{option.help}"',
                )

                self.assertNotEqual(
                    option.help[-1],
                    ".",
                    msg=f"subcmds/{name}.py: {option.get_opt_string()}: "
                    f'help text should not end in a period: "{option.help}"',
                )

    def test_cli_option_style(self):
        """Force some consistency in option flags."""
        for name, cls in subcmds.all_commands.items():
            cmd = cls()
            parser = cmd.OptionParser
            for option in parser.option_list:
                for opt in option._long_opts:
                    self.assertNotIn(
                        "_",
                        opt,
                        msg=f"subcmds/{name}.py: {opt}: only use dashes in options, not underscores",
                    )

    def test_cli_option_dest(self):
        """Block redundant dest= arguments."""

        def _check_dest(opt):
            if opt.dest is None or not opt._long_opts:
                return

            long = opt._long_opts[0]
            assert long.startswith("--")

            implicit_dest = long[2:].replace("-", "_")
            if implicit_dest == opt.dest:
                bad_opts.append((str(opt), opt.dest))

        optparse.Option.CHECK_METHODS.insert(0, _check_dest)

        all_bad_opts = {}
        for name, cls in subcmds.all_commands.items():
            bad_opts = all_bad_opts[name] = []
            cmd = cls()

            cmd.OptionParser

        errmsg = None
        for name, bad_opts in sorted(all_bad_opts.items()):
            if bad_opts:
                if not errmsg:
                    errmsg = "Omit redundant dest= when defining options.\n"
                errmsg += f"\nSubcommand {name} (subcmds/{name}.py):\n"
                errmsg += "".join(f"    {opt}: dest='{dest}'\n" for opt, dest in bad_opts)
        if errmsg:
            self.fail(errmsg)

        assert optparse.Option.CHECK_METHODS.pop(0) is _check_dest
