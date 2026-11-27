"""The smoke test must wait for its process, even after SCM says stopped."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class ServiceCleanupTests(unittest.TestCase):
    def setUp(self):
        modules = {
            name: Mock()
            for name in (
                "httpx",
                "winreg",
                "win32api",
                "win32con",
                "win32event",
                "win32service",
                "win32serviceutil",
                "win32evtlog",
            )
        }
        spec = importlib.util.spec_from_file_location(
            "service_smoke", Path(__file__).with_name("windows-service-smoke.py")
        )
        self.smoke = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", modules):
            spec.loader.exec_module(self.smoke)

    def test_holds_the_running_service_process_before_scm_can_forget_its_pid(self):
        service = self.smoke.win32service
        service.QueryServiceStatusEx.return_value = {"ProcessId": 123}
        handle = self.smoke.open_service_process("EPServiceSmokeFixture")
        self.smoke.win32api.OpenProcess.assert_called_once_with(
            self.smoke.win32con.SYNCHRONIZE, False, 123
        )
        self.assertIs(handle, self.smoke.win32api.OpenProcess.return_value)
        self.assertEqual(service.CloseServiceHandle.call_count, 2)

    def test_stopped_service_process_must_signal_exit_before_cleanup(self):
        handle = Mock()
        self.smoke.win32event.WAIT_OBJECT_0 = 0
        self.smoke.win32event.WaitForSingleObject.return_value = 0
        self.smoke.wait_for_process_exit(handle)
        self.smoke.win32event.WaitForSingleObject.assert_called_once_with(
            handle, 45_000
        )
        handle.Close.assert_called_once_with()

    def test_start_pending_has_no_usable_pid_until_service_is_running(self):
        service = self.smoke.win32service
        service.QueryServiceStatusEx.return_value = {"ProcessId": 0}
        def running(*args):
            service.QueryServiceStatusEx.return_value = {"ProcessId": 123}
        self.smoke.win32serviceutil.WaitForServiceStatus.side_effect = running
        self.smoke.open_service_process("EPServiceSmokeFixture")
        self.smoke.win32serviceutil.WaitForServiceStatus.assert_called_once_with(
            "EPServiceSmokeFixture", service.SERVICE_RUNNING, 45
        )

    def test_timeout_is_reported_and_handle_is_closed(self):
        handle = Mock()
        self.smoke.win32event.WAIT_OBJECT_0 = 0
        self.smoke.win32event.WaitForSingleObject.return_value = 258
        with self.assertRaisesRegex(AssertionError, "service process did not exit"):
            self.smoke.wait_for_process_exit(handle)
        handle.Close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
