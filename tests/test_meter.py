import asyncio
import unittest
from datetime import datetime

from keepgram import media
from keepgram.meter import Meter, duration, finish_at

MB = 1024 * 1024


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Estimates(unittest.TestCase):
    def test_speed_and_time_left(self):
        clock = Clock()
        m = Meter(100 * MB, 2, clock)
        self.assertIsNone(m.speed())  # nothing to go on yet
        for i in range(1, 11):  # 1 MB a second for 10 seconds
            clock.t += 1
            m.partial("#1 download", i * MB)
        self.assertAlmostEqual(m.speed(), 1 * MB, delta=0.05 * MB)
        self.assertAlmostEqual(m.seconds_left(), 90, delta=5)
        self.assertEqual(m.fraction, 0.1)

    def test_follows_a_change_of_speed(self):
        clock = Clock()
        m = Meter(10_000 * MB, 1, clock)
        done = 0
        for _ in range(600):  # ten minutes at 1 MB/s
            clock.t += 1
            done += MB
            m.partial("x", done)
        for _ in range(300):  # then five minutes at 4 MB/s
            clock.t += 1
            done += 4 * MB
            m.partial("x", done)
        # the last two minutes decide, not the slow start
        self.assertAlmostEqual(m.speed(), 4 * MB, delta=0.2 * MB)

    def test_units_done_failed_and_skipped(self):
        clock = Clock()
        m = Meter(300 * MB, 3, clock)
        clock.t += 10
        m.partial("a download", 50 * MB)
        m.finish_unit(100 * MB)  # done (or failed): its whole size is behind us, partials gone
        self.assertEqual(m.progress, 100 * MB)
        m.skip_unit(100 * MB)  # someone else copied it: no longer part of the job
        self.assertEqual((m.total, m.units), (200 * MB, 2))
        self.assertEqual(m.fraction, 0.5)

    def test_wording(self):
        self.assertEqual(duration(30), "less than a minute")
        self.assertEqual(duration(25 * 60), "about 25 min")
        self.assertEqual(duration(3 * 3600 + 20 * 60), "about 3 h 20 min")
        self.assertEqual(duration(2 * 86400 + 4 * 3600), "about 2 days 4 h")
        now = datetime(2026, 11, 2, 21, 0)
        self.assertEqual(finish_at(40 * 60, now), "around 9:40 PM")
        self.assertEqual(finish_at(6 * 3600 + 10 * 60, now), "around 3:10 AM tomorrow")
        self.assertEqual(finish_at(3 * 86400, now), "around Thu 9:00 PM")

    def test_menu_task_screen_shows_the_whole_job(self):
        from keepgram.ui.app import KeepgramApp
        from keepgram.ui.task import TaskScreen
        from textual.widgets import Label

        async def go():
            app = KeepgramApp()
            async with app.run_test(size=(110, 30)) as pilot:
                await pilot.pause(0.2)
                release = asyncio.Event()

                async def work(t):
                    clock = Clock()
                    media.METER = m = Meter(357 * 1024 * MB, 1059, clock)
                    for i in range(1, 20):
                        clock.t += 1
                        media.Progress("#27 download")(i * 3 * MB, 57 * MB)
                    m.finish_unit(114 * MB)
                    await release.wait()
                    media.METER = None

                app.push_screen(TaskScreen(["keepgram", "Copy"], "Copying", work))
                await pilot.pause(0.6)
                screen = app.screen
                self.assertTrue(screen.query_one("#all-row").display)
                detail = str(screen.query_one("#all-detail", Label).render())
                self.assertIn("1 of 1059 done", detail)
                self.assertIn("left · done around", detail)
                self.assertIn("left", screen.query_one("TopBar")._info)
                release.set()
                await pilot.pause(0.4)

        asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
