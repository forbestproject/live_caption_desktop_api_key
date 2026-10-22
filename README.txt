Windows 11 Live Captions -> AI Practice Answers
==============================================

This is a Python desktop app, not an installer or prebuilt EXE.
It captures a screen region with OCR and shows suggested answers in a separate window.
It is intended for mock interview practice or situations where use is authorized.
Get consent before transmitting other people's speech to an external API.

SETUP
1. Install Python 3.10+ for Windows from https://www.python.org/downloads/windows/
   Enable "Add Python to PATH" during setup.
2. Install Tesseract OCR for Windows, e.g. from
   https://github.com/UB-Mannheim/tesseract/wiki
   Ensure tesseract.exe is on PATH, or configure its location in Python.
3. Open PowerShell in this folder and run:
     py -m pip install -r requirements.txt
4. Obtain an OpenAI API key at https://platform.openai.com/api-keys
   You may need to enable API billing separately from ChatGPT.
5. In PowerShell (current session only), enter:
     $env:OPENAI_API_KEY = "YOUR_PRIVATE_KEY"
   DO NOT put the key in the app or share it.
6. In the SAME PowerShell window run:
     py live_caption_assistant.py

USAGE
1. Press Win + Ctrl + L to enable Windows 11 Live Captions.
2. Click "Select caption area" and drag over only the caption text on the screen.
3. Click "Start reading". Your captions appear in the top text area.
4. When a question appears, the app sends its text to the OpenAI API and places
   a sample answer into the lower pane.
5. For testing without captions, type into the top pane and click "Generate answer now".

LIMITATIONS
- Live Captions has no straightforward documented public caption-stream export.
  This app reads on-screen captions with OCR. Accuracy depends on screen scale,
  typography, language, motion and whether the captions are visible.
- Selecting a caption region does not work if a caption window is obscured.
- Auto question recognition is heuristic. There may be false positives or misses.
- No transcript or API key is saved by the app. Selected region coordinates are
  persisted in a file in your home directory.
- API requests incur usage charges and require an internet connection.
- Select a sensible region that does not include this app's answer pane.
- This code has been syntax checked but not tested on a real Windows machine.

TROUBLESHOOTING
- "Tesseract not found": add Tesseract install path to Windows PATH and restart PowerShell.
- "API key not found": launch the app in the same PowerShell session as the $env command.
- Empty captions: select a tighter region containing readable text.
- Wrong words: increase Windows caption text size, select a tighter capture area.
- Model not found: choose a model enabled for your API project.

NEW: AUTO-SAVE COMPLETED SENTENCES
----------------------------------
The app now appends each detected completed sentence on its own line to:
  %USERPROFILE%\Documents\LiveCaptions\captions.txt
For example, 'Tell me about yourself.' is written as soon as OCR observes
its final '.', '?' or '!'. The file is UTF-8 and is preserved across runs.
You do NOT need an API key for sentence recording (only for AI answers).

Important limitations: Windows Live Captions does not expose an official
caption export stream to this app. It uses screenshots + OCR and heuristics
to stitch together caption changes. On fast scrolling, missing punctuation,
overlapping words, or OCR errors it may omit, duplicate, or mangle sentences.
If Live Captions omits sentence-ending punctuation, it cannot reliably decide
that the sentence ended, and text remains buffered until punctuation appears.
Stop does not save unfinished fragments. The transcript includes only text
visible in the selected capture area. Obtain consent before recording others.

FIX: CAPTION-AREA SELECTOR ON WINDOWS
-------------------------------------
Removed the incompatible override-redirect + fullscreen combination that
raised TclError when clicking Select caption area. The selector now uses
Tkinter's native fullscreen overlay.
