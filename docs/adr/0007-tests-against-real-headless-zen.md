# Tests run snippets against a real headless Zen, never a mock and never the user's browser

The test surface is the agent-facing interface: snippets go through the CLI against a headless Zen on a throwaway profile, using local fixture pages and a small fixture server, and assert what the page shows. There is no mock BiDi server. A real local stand-in exists, and a mock would hide exactly the browser quirks this project keeps tripping over: dialogs blocking input, wheel events ignored in background tabs, the accessibility locator hanging. Tests pick their own ports (`ZH_TEST_PORT`) and Marionette ports, and must never attach to the user's Zen on 9222.

Pure logic inside the daemon may also be tested in-process. The page settle module (`settle.py`) is fed recorded BiDi event sequences in `tests/test_settle.py`. That isn't a mock BiDi server: nothing pretends to be Zen, and the agent-facing waits are still tested against real Zen.
