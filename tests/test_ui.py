"""The menus, driven headlessly (Textual's pilot) - offline: no login, so
nothing reaches Telegram."""

import asyncio
import json
import unittest
from types import SimpleNamespace

from textual.widgets import Button

from keepgram import paths
from keepgram.ui import flows, touch
from keepgram.ui.app import KeepgramApp
from keepgram.ui.dialogs import Ask, Choice, Result
from keepgram.ui.screens import HOME, HomeScreen, SettingsScreen
from keepgram.ui.task import TaskScreen
from keepgram.ui.widgets import KeyboardBox, SafeOptionList

LONG_NOTE = "Found 694 file(s) in 44 chat(s).\n\n" + "\n".join(
    f"• Saved Files {n}: {n * 7} forwards from a bot, {n * 3} photos" for n in range(1, 31))


async def working(t):
    t.log("copied Movie part 1.mkv into Saved Files 3")
    await asyncio.sleep(30)


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

                home.highlighted = [key for key, _, _ in HOME].index("settings")
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


class Phone(unittest.TestCase):
    """Termux shows its keyboard on a tap only while the program isn't taking
    the mouse (touch.py), so the menus let go of it where typing is wanted."""

    def setUp(self):
        self.was = touch.PHONE, touch.FREE_FOR
        touch.PHONE = True

    def tearDown(self):
        touch.PHONE, touch.FREE_FOR = self.was

    def test_a_text_box_lets_go_of_the_mouse(self):
        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(48, 20)) as pilot:
                await pilot.pause(0.3)
                self.assertFalse(getattr(app, "mouse_free", False))  # in the lists taps choose
                app.push_screen(Ask("Log in: the code", "Telegram just sent it to your Telegram app."))
                await pilot.pause(0.4)
                self.assertTrue(app.mouse_free)  # a tap anywhere brings the keyboard now
                await pilot.press("escape")
                await pilot.pause(0.4)
                self.assertFalse(app.mouse_free)

        asyncio.run(go())

    def test_the_log_has_a_read_only_keyboard_box(self):
        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(48, 20)) as pilot:
                await pilot.pause(0.3)
                app.push_screen(TaskScreen(["keepgram", "Test"], "Working", working))
                await pilot.pause(0.3)
                self.assertFalse(app.screen.query_one(KeyboardBox).can_focus)  # read-only: takes no typing
                await pilot.click(KeyboardBox)
                self.assertTrue(app.mouse_free)  # let go at once - Termux decides about this tap ~300 ms on
                await pilot.resize_terminal(48, 12)  # the keyboard came up
                await pilot.pause(0.4)
                self.assertFalse(app.mouse_free)  # taps go to the menus again

                touch.FREE_FOR = 0.3
                await pilot.click(KeyboardBox)
                self.assertTrue(app.mouse_free)
                await pilot.pause(0.8)  # no keyboard came (it was up already): taken back after a while
                self.assertFalse(app.mouse_free)

                await pilot.press("ctrl+c")  # the box takes no keys: they still reach the screen
                await pilot.pause(0.2)
                self.assertTrue(app.screen.job.stopped)

        asyncio.run(go())

    def test_a_computer_keeps_the_mouse(self):
        touch.PHONE = False

        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause(0.3)
                app.push_screen(TaskScreen(["keepgram", "Test"], "Working", working))
                await pilot.pause(0.3)
                self.assertFalse(app.screen.query(KeyboardBox))
                app.push_screen(Ask("Upload a folder", "Type or paste the folder's path."))
                await pilot.pause(0.4)
                self.assertFalse(getattr(app, "mouse_free", False))

        asyncio.run(go())


class SmallScreens(unittest.TestCase):
    """A phone with its keyboard up (48x20) or turned sideways (110x12): a card's
    long part gives up rows, so its title and its answers stay on screen."""

    def card_fits(self, size, card, answers):
        async def go():
            app = KeepgramApp()
            async with app.run_test(size=size) as pilot:
                await pilot.pause(0.2)
                app.push_screen(card)
                await pilot.pause(0.5)
                dialog = app.screen.query_one(".dialog")
                self.assertEqual(dialog.max_scroll_y, 0, size)  # the card itself doesn't scroll
                self.assertGreaterEqual(app.screen.query_one(".dialog-title").region.y, 0, size)
                shown = app.screen.query_one(answers).region
                self.assertLessEqual(shown.bottom, size[1] - 1, size)  # whole, above the key bar

        asyncio.run(go())

    def test_a_long_note_leaves_the_options_whole(self):
        for size in ((48, 20), (110, 12), (48, 42), (100, 30)):
            self.card_fits(size, Choice("694 file(s) to keep", LONG_NOTE,
                                        [("go", "Copy all 694 file(s) now"), ("no", "Not now")], default="no"),
                           SafeOptionList)

    def test_a_long_result_keeps_its_ok(self):
        for size in ((48, 20), (110, 12)):
            self.card_fits(size, Result("What it did lately", LONG_NOTE), Button)

    def test_the_log_gets_the_rows(self):
        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(48, 20)) as pilot:
                await pilot.pause(0.2)
                app.push_screen(TaskScreen(["keepgram", "Test"], "Working", working))
                app.screen.bar = ("Movie part 12.mkv", 600_000_000, 1_200_000_000)
                await pilot.pause(0.5)
                self.assertGreaterEqual(app.screen.query_one("#output").region.height, 10)
                # the file's bar keeps its % inside it (an id clash with Textual's own "#bar" pushed it out)
                bar = app.screen.query_one("#file-bar")
                self.assertLessEqual(bar.query_one("#percentage").region.right, bar.region.right)

        asyncio.run(go())


class OneConnectAtATime(unittest.TestCase):
    def test_a_menu_item_waits_for_the_start_up_connect(self):
        """Both used to open this keepgram's copy of the login at once - two
        clients on one session file lock each other out."""

        class Connected:
            def is_connected(self):
                return True

        async def go():
            app = SimpleNamespace(client=None, me=None, cfg={})
            lock = flows._connecting(app)
            await lock.acquire()  # the start-up connect is still going
            item = asyncio.ensure_future(flows.ensure_client(app))
            await asyncio.sleep(0.05)
            self.assertFalse(item.done())  # it waits instead of connecting a second time
            app.client = Connected()  # ... the start-up connect got there
            lock.release()
            self.assertIs(await item, app.client)  # and the item uses that connection

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
