"""The menus, driven headlessly (Textual's pilot) - offline: no login, so
nothing reaches Telegram."""

import asyncio
import json
import unittest

from keepgram import paths
from keepgram.ui.app import KeepgramApp
from keepgram.ui.dialogs import Choice
from keepgram.ui.screens import HomeScreen, SettingsScreen


class Menus(unittest.TestCase):
    def test_home_settings_and_back(self):
        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, HomeScreen)
                home = app.screen.query_one("#home")
                self.assertEqual(home.highlighted, 0)  # the first item is ready: Enter works at once
                await pilot.press("enter")
                await pilot.pause(0.3)
                # opened My channels and groups - which, with no login here, first asks for one
                self.assertIn("ChatsScreen", [type(sc).__name__ for sc in app.screen_stack])
                for _ in range(5):  # Esc out of the login question, its note, and the screen
                    if isinstance(app.screen, HomeScreen):
                        break
                    await pilot.press("escape")
                    await pilot.pause(0.2)
                self.assertIsInstance(app.screen, HomeScreen)

                home.highlighted = 7  # Settings
                await pilot.press("enter")
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, SettingsScreen)
                await pilot.press("enter")  # first row, Telegram Premium: auto / on / off
                await pilot.pause(0.3)
                self.assertIsInstance(app.screen, Choice)
                await pilot.press("down", "enter")  # opens on the current value (Auto); one down is "On"
                await pilot.pause(0.3)
                self.assertIs(json.loads(paths.CONFIG.read_text())["premium"], True)
                await pilot.press("enter")  # opens on "On" now
                await pilot.pause(0.3)
                await pilot.press("up", "enter")  # back to "Auto"
                await pilot.pause(0.3)
                self.assertEqual(json.loads(paths.CONFIG.read_text())["premium"], "auto")
                self.assertNotIn("_limits", json.loads(paths.CONFIG.read_text()))  # learned values aren't saved

                await pilot.press("down", "enter")  # File pictures -> a choice
                await pilot.pause(0.3)
                self.assertIsInstance(app.screen, Choice)
                await pilot.press("escape")
                await pilot.pause(0.2)
                await pilot.press("escape")
                await pilot.pause(0.2)
                self.assertIsInstance(app.screen, HomeScreen)
                await pilot.press("q")
                await pilot.pause(0.2)

        asyncio.run(go())


class EagerTasks(unittest.TestCase):
    def test_telethon_can_send_inside_the_menus(self):
        """A real terminal gives the menus Textual's eager tasks; Telethon's send
        loop must still run - so the menus turn them off."""
        from keepgram.ui.app import normal_tasks

        async def go():
            loop = asyncio.get_running_loop()
            loop.set_task_factory(asyncio.eager_task_factory)  # what App.run() does
            normal_tasks()
            self.assertIsNone(loop.get_task_factory())
            # and the pattern Telethon uses now works: a loop started before the flag is set still runs
            state = {"connected": False, "sent": False}

            async def send_loop():
                while state["connected"]:
                    state["sent"] = True
                    return

            task = loop.create_task(send_loop())
            state["connected"] = True
            await task
            self.assertTrue(state["sent"])

        asyncio.run(go())


class SafeDefaults(unittest.TestCase):
    def test_yes_no_questions_open_on_the_safe_answer(self):
        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause(0.2)
                answers = []
                choice = Choice("Copy all 1059 files?", "", [("go", "Copy all now"), ("no", "Not now")], default="no")
                app.push_screen(choice, answers.append)
                await pilot.pause(0.2)
                await pilot.press("enter")  # a stray Enter
                await pilot.pause(0.2)
                self.assertEqual(answers, ["no"])

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
