"""Run one call to Salesforce off the UI thread — shared by every dialog that talks to Salesforce."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from worklog.services import salesforce as sf_client

# Salesforce calls that outlive their dialog are parked here until they finish,
# so a running QThread is never garbage-collected.
_running_salesforce_calls: set = set()


class SalesforceCall(QThread):
    """Runs one call to Salesforce off the UI thread.

    `work` gets the client and returns the result. Emits (True, result) or
    (False, error text).
    """

    finished_with = pyqtSignal(bool, object)

    def __init__(self, creds: sf_client.SalesforceCredentials, client_factory, work) -> None:
        super().__init__()
        self._creds = creds
        self._client_factory = client_factory
        self._work = work

    def run(self) -> None:
        try:
            result = self._work(self._client_factory(self._creds))
        except sf_client.SalesforceError as exc:
            self.finished_with.emit(False, str(exc))
        except Exception as exc:  # never let a worker thread die silently
            self.finished_with.emit(False, f"Unerwarteter Fehler: {exc}")
        else:
            self.finished_with.emit(True, result)


def start_salesforce_call(
    creds: sf_client.SalesforceCredentials, client_factory, work, on_finished
) -> SalesforceCall:
    """Start `work(client)` in the background; `on_finished(ok, result_or_error_text)` runs in the UI thread."""
    call = SalesforceCall(creds, client_factory, work)
    call.finished_with.connect(on_finished)
    call.finished.connect(lambda c=call: _running_salesforce_calls.discard(c))
    _running_salesforce_calls.add(call)
    call.start()
    return call
